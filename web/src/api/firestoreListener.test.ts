import { beforeEach, describe, expect, it, vi } from "vitest";

const fs = vi.hoisted(() => {
  const state = {
    next: undefined as ((s: unknown) => void) | undefined,
    error: undefined as ((e: Error) => void) | undefined,
    unsub: vi.fn(),
  };
  return {
    state,
    initializeFirestore: vi.fn<(app: unknown, opts: unknown, db: unknown) => unknown>(() => ({ kind: "db" })),
    memoryLocalCache: vi.fn(() => ({ kind: "memory" })),
    connectFirestoreEmulator: vi.fn(),
    doc: vi.fn((_db: unknown, col: string, id: string) => ({ path: `${col}/${id}` })),
    onSnapshot: vi.fn((_ref: unknown, next: (s: unknown) => void, error: (e: Error) => void) => {
      state.next = next;
      state.error = error;
      return state.unsub;
    }),
  };
});

vi.mock("firebase/app", () => ({ getApp: () => ({ name: "[DEFAULT]" }) }));
vi.mock("firebase/firestore", () => ({
  initializeFirestore: fs.initializeFirestore,
  memoryLocalCache: fs.memoryLocalCache,
  connectFirestoreEmulator: fs.connectFirestoreEmulator,
  doc: fs.doc,
  onSnapshot: fs.onSnapshot,
}));

import { createFirestoreStatusListener, resetFirestoreForTests } from "./firestoreListener";

const snap = (data: Record<string, unknown> | null) => ({ exists: () => data !== null, data: () => data });
const flush = () => new Promise((r) => setTimeout(r, 0));

beforeEach(() => {
  vi.clearAllMocks();
  fs.state.next = fs.state.error = undefined;
  resetFirestoreForTests();
});

describe("firestore status listener", () => {
  it("opens the configured database with a memory cache and listens on session_status/{id}", async () => {
    const l = createFirestoreStatusListener({ database: "staging" });
    l.subscribe("s1", vi.fn(), vi.fn());
    await flush();
    expect(fs.initializeFirestore).toHaveBeenCalledWith({ name: "[DEFAULT]" }, { localCache: { kind: "memory" } }, "staging");
    expect(fs.doc).toHaveBeenCalledWith({ kind: "db" }, "session_status", "s1");
    expect(fs.connectFirestoreEmulator).not.toHaveBeenCalled();
  });

  it("uses the (default) database when none is configured", async () => {
    createFirestoreStatusListener({}).subscribe("s1", vi.fn(), vi.fn());
    await flush();
    expect(fs.initializeFirestore.mock.calls[0][2]).toBe("(default)");
  });

  it("connects to the emulator host:port when configured, once", async () => {
    const l = createFirestoreStatusListener({ database: "(default)", emulator: "127.0.0.1:8080" });
    l.subscribe("s1", vi.fn(), vi.fn());
    l.subscribe("s2", vi.fn(), vi.fn());
    await flush();
    expect(fs.connectFirestoreEmulator).toHaveBeenCalledTimes(1);
    expect(fs.connectFirestoreEmulator).toHaveBeenCalledWith({ kind: "db" }, "127.0.0.1", 8080);
    expect(fs.initializeFirestore).toHaveBeenCalledTimes(1);
  });

  it("maps snapshots to status docs (Timestamp -> ISO) and a missing doc to null", async () => {
    const onStatus = vi.fn();
    createFirestoreStatusListener({}).subscribe("s1", onStatus, vi.fn());
    await flush();
    fs.state.next!(
      snap({
        uid: "u1",
        state: "running",
        step: "tips",
        progress: 70,
        error_code: null,
        latest_report_version: null,
        updated_at: { toDate: () => new Date("2026-01-02T03:04:05.000Z") },
        transcript_ready: true,
        speaker_confirmed: true,
        rating_submitted: true,
        has_rating: false,
      }),
    );
    expect(onStatus).toHaveBeenLastCalledWith({
      uid: "u1",
      state: "running",
      step: "tips",
      progress: 70,
      error_code: null,
      latest_report_version: null,
      updated_at: "2026-01-02T03:04:05.000Z",
      transcript_ready: true,
      speaker_confirmed: true,
      rating_submitted: true,
      has_rating: false,
    });
    fs.state.next!(snap(null));
    expect(onStatus).toHaveBeenLastCalledWith(null);
  });

  it("forwards listener errors such as permission-denied", async () => {
    const onError = vi.fn();
    createFirestoreStatusListener({}).subscribe("s1", vi.fn(), onError);
    await flush();
    const err = Object.assign(new Error("denied"), { code: "permission-denied" });
    fs.state.error!(err);
    expect(onError).toHaveBeenCalledWith(err);
  });

  it("unsubscribes the Firestore listener, including when leaving before it attached", async () => {
    const off = createFirestoreStatusListener({}).subscribe("s1", vi.fn(), vi.fn());
    await flush();
    off();
    expect(fs.state.unsub).toHaveBeenCalledTimes(1);

    const early = createFirestoreStatusListener({}).subscribe("s2", vi.fn(), vi.fn());
    early(); // before the lazy import resolved
    await flush();
    expect(fs.onSnapshot).toHaveBeenCalledTimes(1); // never attached for s2
  });

  it("reports a load failure through onError", async () => {
    fs.initializeFirestore.mockImplementationOnce(() => {
      throw new Error("boom");
    });
    const onError = vi.fn();
    createFirestoreStatusListener({}).subscribe("s1", vi.fn(), onError);
    await flush();
    expect(onError).toHaveBeenCalledTimes(1);
  });
});
