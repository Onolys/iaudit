import { afterEach, describe, expect, it, vi } from "vitest";
import { activeUploadCount, getJob, registerJob, UploadJob, type UploadTarget } from "./uploader";

class FakeXhr {
  static all: FakeXhr[] = [];
  method = "";
  url = "";
  headers: Record<string, string> = {};
  body: unknown;
  status = 0;
  aborted = false;
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  ontimeout: (() => void) | null = null;
  upload: { onprogress: ((e: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } = {
    onprogress: null,
  };
  constructor() {
    FakeXhr.all.push(this);
  }
  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }
  setRequestHeader(k: string, v: string) {
    this.headers[k] = v;
  }
  send(body: unknown) {
    this.body = body;
  }
  abort() {
    this.aborted = true;
    this.onabort?.();
  }
  progress(loaded: number, total: number) {
    this.upload.onprogress?.({ lengthComputable: true, loaded, total });
  }
  finish(status: number) {
    this.status = status;
    this.onload?.();
  }
  fail() {
    this.onerror?.();
  }
}

const file = new Blob([new Uint8Array(1000)], { type: "audio/mpeg" });
const target = (n: number): UploadTarget => ({
  upload_url: `https://up.example/u${n}`,
  required_headers: { "Content-Type": "audio/mpeg", "x-goog-content-length-range": "0,314572800" },
});
const tick = () => new Promise((r) => setTimeout(r, 0));
const last = () => FakeXhr.all[FakeXhr.all.length - 1]!;

function make(opts: { fresh?: number } = {}) {
  let n = opts.fresh ?? 1;
  const requestTarget = vi.fn(async () => target(++n));
  const complete = vi.fn(async () => undefined);
  const job = new UploadJob({
    file,
    first: target(1),
    requestTarget,
    complete,
    createXhr: () => new FakeXhr() as unknown as XMLHttpRequest,
  });
  return { job, requestTarget, complete };
}

afterEach(() => {
  FakeXhr.all = [];
});

describe("UploadJob", () => {
  it("PUTs the file with exactly the required_headers and nothing else", async () => {
    const { job } = make();
    void job.start();
    await tick();
    const x = last();
    expect(x.method).toBe("PUT");
    expect(x.url).toBe("https://up.example/u1");
    expect(x.headers).toEqual(target(1).required_headers);
    expect(x.body).toBe(file);
  });

  it("reports progress, then completes and calls audio/complete once", async () => {
    const { job, complete } = make();
    void job.start();
    await tick();
    last().progress(250, 1000);
    expect(job.getState()).toMatchObject({ phase: "uploading", loaded: 250, total: 1000 });
    last().progress(1000, 1000);
    last().finish(200);
    await tick();
    expect(complete).toHaveBeenCalledTimes(1);
    expect(job.getState().phase).toBe("done");
  });

  it("cancel aborts the XHR, stops, and does not retry or complete", async () => {
    const { job, requestTarget, complete } = make();
    void job.start();
    await tick();
    job.cancel();
    await tick();
    expect(last().aborted).toBe(true);
    expect(job.getState().phase).toBe("cancelled");
    expect(FakeXhr.all).toHaveLength(1);
    expect(requestTarget).not.toHaveBeenCalled();
    expect(complete).not.toHaveBeenCalled();
  });

  it("retries with a fresh URL up to 2 times (3 PUTs), then fails", async () => {
    const { job, requestTarget, complete } = make();
    void job.start();
    await tick();
    last().finish(403);
    await tick();
    expect(FakeXhr.all).toHaveLength(2);
    expect(last().url).toBe("https://up.example/u2");
    last().fail();
    await tick();
    expect(FakeXhr.all).toHaveLength(3);
    expect(last().url).toBe("https://up.example/u3");
    expect(last().headers).toEqual(target(3).required_headers);
    last().finish(500);
    await tick();
    expect(FakeXhr.all).toHaveLength(3);
    expect(requestTarget).toHaveBeenCalledTimes(2);
    expect(job.getState().phase).toBe("failed");
    expect(complete).not.toHaveBeenCalled();
  });

  it("succeeds when the second try works", async () => {
    const { job, complete } = make();
    void job.start();
    await tick();
    last().fail();
    await tick();
    last().finish(200);
    await tick();
    expect(job.getState().phase).toBe("done");
    expect(complete).toHaveBeenCalledTimes(1);
  });

  it("manual retry after failure requests a fresh URL and starts again", async () => {
    const { job, requestTarget } = make();
    void job.start();
    for (let i = 0; i < 3; i++) {
      await tick();
      last().fail();
    }
    await tick();
    expect(job.getState().phase).toBe("failed");
    void job.retry();
    await tick();
    expect(requestTarget).toHaveBeenCalledTimes(3);
    expect(FakeXhr.all).toHaveLength(4);
    expect(job.getState().phase).toBe("uploading");
  });

  it("a failed audio/complete is retried without re-uploading", async () => {
    const { job, complete } = make();
    complete.mockRejectedValueOnce(new Error("boom"));
    void job.start();
    await tick();
    last().finish(200);
    await tick();
    expect(job.getState().phase).toBe("failed");
    void job.retry();
    await tick();
    expect(FakeXhr.all).toHaveLength(1);
    expect(complete).toHaveBeenCalledTimes(2);
    expect(job.getState().phase).toBe("done");
  });
});

describe("beforeunload guard", () => {
  it("blocks unload only while an upload is active", async () => {
    const { job } = make();
    registerJob("s1", job);
    const idle = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(idle);
    expect(idle.defaultPrevented).toBe(false);
    expect(getJob("s1")).toBe(job);

    void job.start();
    await tick();
    expect(activeUploadCount()).toBe(1);
    const busy = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(busy);
    expect(busy.defaultPrevented).toBe(true);

    last().finish(200);
    await tick();
    const after = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(after);
    expect(after.defaultPrevented).toBe(false);
  });
});
