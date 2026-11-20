import { describe, expect, it, vi } from "vitest";
import {
  createMemoryStatusEmitter,
  getStatusListener,
  setStatusListener,
  type SessionStatusDoc,
} from "./statusListener";

const doc = (over: Partial<SessionStatusDoc> = {}): SessionStatusDoc => ({
  uid: "u1",
  state: "created",
  step: null,
  progress: 0,
  error_code: null,
  latest_report_version: null,
  updated_at: "2026-01-01T00:00:00.000Z",
  transcript_ready: false,
  speaker_confirmed: false,
  rating_submitted: false,
  has_rating: false,
  ...over,
});

describe("memory status emitter", () => {
  it("delivers the current doc on subscribe, like an onSnapshot first snapshot", () => {
    const em = createMemoryStatusEmitter();
    em.emit("s1", doc({ state: "uploading", progress: 5 }));
    const cb = vi.fn();
    em.subscribe("s1", cb, vi.fn());
    expect(cb).toHaveBeenCalledTimes(1);
    expect(cb.mock.calls[0][0].state).toBe("uploading");
  });

  it("does not call back on subscribe when no doc exists yet", () => {
    const em = createMemoryStatusEmitter();
    const cb = vi.fn();
    em.subscribe("s1", cb, vi.fn());
    expect(cb).not.toHaveBeenCalled();
  });

  it("pushes later snapshots only to subscribers of that session", () => {
    const em = createMemoryStatusEmitter();
    const a = vi.fn();
    const b = vi.fn();
    em.subscribe("s1", a, vi.fn());
    em.subscribe("s2", b, vi.fn());
    em.emit("s1", doc({ state: "validating" }));
    expect(a).toHaveBeenCalledTimes(1);
    expect(b).not.toHaveBeenCalled();
  });

  it("stops delivering after unsubscribe", () => {
    const em = createMemoryStatusEmitter();
    const cb = vi.fn();
    const off = em.subscribe("s1", cb, vi.fn());
    off();
    em.emit("s1", doc());
    expect(cb).not.toHaveBeenCalled();
  });

  it("routes injected errors (permission-denied) to onError", () => {
    const em = createMemoryStatusEmitter();
    const onError = vi.fn();
    em.subscribe("s1", vi.fn(), onError);
    em.emitError("s1", new Error("permission-denied"));
    expect(onError).toHaveBeenCalledTimes(1);
  });

  it("emits a null doc when the session is removed", () => {
    const em = createMemoryStatusEmitter();
    const cb = vi.fn();
    em.emit("s1", doc());
    em.subscribe("s1", cb, vi.fn());
    em.remove("s1");
    expect(cb).toHaveBeenLastCalledWith(null);
  });

  it("clear drops all docs and subscribers", () => {
    const em = createMemoryStatusEmitter();
    const cb = vi.fn();
    em.emit("s1", doc());
    em.subscribe("s1", cb, vi.fn());
    cb.mockClear();
    em.clear();
    em.emit("s1", doc());
    expect(cb).not.toHaveBeenCalled();
  });
});

describe("listener registry", () => {
  it("throws until a listener is registered, then returns it", () => {
    setStatusListener(null);
    expect(() => getStatusListener()).toThrow(/status listener/i);
    const em = createMemoryStatusEmitter();
    setStatusListener(em);
    expect(getStatusListener()).toBe(em);
    setStatusListener(null);
  });
});
