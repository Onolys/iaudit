/**
 * App-level uploader (PRD R3, D6). One PUT of the whole object with XMLHttpRequest, sending exactly
 * the API's `required_headers`; auto-retry with a fresh URL up to 2 times, then the user retries
 * by hand. Jobs live in a module-level registry so they survive navigation to the session page.
 */
export interface UploadTarget {
  upload_url: string;
  required_headers: Record<string, string>;
}

export type UploadPhase = "idle" | "uploading" | "completing" | "done" | "failed" | "cancelled";

export interface UploadState {
  phase: UploadPhase;
  loaded: number;
  total: number;
  /** 0 for the first PUT, 1 and 2 for the automatic retries. */
  attempt: number;
}

export interface UploadJobOptions {
  file: Blob;
  /** The URL already issued by `POST …/audio`; later tries call `requestTarget`. */
  first?: UploadTarget;
  requestTarget: () => Promise<UploadTarget>;
  /** `POST …/audio/complete`. */
  complete: () => Promise<unknown>;
  createXhr?: () => XMLHttpRequest;
}

export const MAX_AUTO_RETRIES = 2;

export class UploadJob {
  private state: UploadState;
  private listeners = new Set<() => void>();
  private xhr: XMLHttpRequest | null = null;
  private run = 0;
  private uploaded = false;
  private first: UploadTarget | undefined;

  constructor(private readonly opts: UploadJobOptions) {
    this.first = opts.first;
    this.state = { phase: "idle", loaded: 0, total: opts.file.size, attempt: 0 };
  }

  getState = (): UploadState => this.state;

  subscribe = (fn: () => void): (() => void) => {
    this.listeners.add(fn);
    return () => void this.listeners.delete(fn);
  };

  get active(): boolean {
    return this.state.phase === "uploading" || this.state.phase === "completing";
  }

  private set(patch: Partial<UploadState>) {
    this.state = { ...this.state, ...patch };
    this.listeners.forEach((l) => l());
  }

  /** Start (or restart after failure/cancel) the upload. */
  start(): Promise<void> {
    if (this.active) return Promise.resolve();
    const id = ++this.run;
    if (this.uploaded) return this.finish(id);
    return this.upload(id);
  }

  retry(): Promise<void> {
    return this.start();
  }

  cancel(): void {
    if (!this.active) return;
    this.run++;
    this.set({ phase: "cancelled" });
    this.xhr?.abort();
    this.xhr = null;
  }

  private async upload(id: number): Promise<void> {
    this.set({ phase: "uploading", loaded: 0, attempt: 0 });
    for (let attempt = 0; attempt <= MAX_AUTO_RETRIES; attempt++) {
      try {
        const target = this.first ?? (await this.opts.requestTarget());
        this.first = undefined;
        if (id !== this.run) return;
        this.set({ attempt, loaded: 0 });
        await this.put(target, id);
        this.uploaded = true;
        break;
      } catch {
        this.first = undefined; // a used or expired URL is never reused
        if (id !== this.run) return;
        if (attempt === MAX_AUTO_RETRIES) {
          this.set({ phase: "failed" });
          return;
        }
      }
    }
    if (id !== this.run) return;
    return this.finish(id);
  }

  private async finish(id: number): Promise<void> {
    this.set({ phase: "completing", loaded: this.state.total });
    try {
      await this.opts.complete();
      if (id === this.run) this.set({ phase: "done" });
    } catch {
      if (id === this.run) this.set({ phase: "failed" });
    }
  }

  private put(target: UploadTarget, id: number): Promise<void> {
    return new Promise((resolve, reject) => {
      const xhr = this.opts.createXhr ? this.opts.createXhr() : new XMLHttpRequest();
      this.xhr = xhr;
      xhr.open("PUT", target.upload_url);
      for (const [k, v] of Object.entries(target.required_headers)) xhr.setRequestHeader(k, v);
      xhr.upload.onprogress = (e) => {
        if (id === this.run && e.lengthComputable) this.set({ loaded: e.loaded, total: e.total });
      };
      xhr.onload = () => (xhr.status >= 200 && xhr.status < 300 ? resolve() : reject(new Error(`PUT ${xhr.status}`)));
      xhr.onerror = () => reject(new Error("network"));
      xhr.ontimeout = () => reject(new Error("timeout"));
      xhr.onabort = () => reject(new Error("aborted"));
      xhr.send(this.opts.file);
    });
  }
}

// ---- registry + unload guard ------------------------------------------------

const jobs = new Map<string, UploadJob>();
const registryListeners = new Set<() => void>();

export function registerJob(sessionId: string, job: UploadJob): void {
  jobs.set(sessionId, job);
  registryListeners.forEach((l) => l());
}

export function getJob(sessionId: string): UploadJob | undefined {
  return jobs.get(sessionId);
}

export function subscribeRegistry(fn: () => void): () => void {
  registryListeners.add(fn);
  return () => void registryListeners.delete(fn);
}

export function activeUploadCount(): number {
  let n = 0;
  jobs.forEach((j) => {
    if (j.active) n++;
  });
  return n;
}

if (typeof window !== "undefined") {
  window.addEventListener("beforeunload", (e) => {
    if (activeUploadCount() > 0) {
      e.preventDefault();
      e.returnValue = ""; // legacy browsers need a value to show the prompt
    }
  });
}
