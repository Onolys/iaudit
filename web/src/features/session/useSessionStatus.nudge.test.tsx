import { renderHook, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  createMemoryStatusEmitter,
  setStatusListener,
  type SessionStatusDoc,
} from "../../api/statusListener";
import { useSessionStatus } from "./useSessionStatus";

const get = vi.fn();
vi.mock("../../auth/useApiClient", () => {
  const client = { GET: (...a: unknown[]) => get(...a) };
  return { useApiClient: () => client };
});

const MIN = 60_000;
const emitter = createMemoryStatusEmitter();
const doc = (state: SessionStatusDoc["state"], updated_at = new Date().toISOString()): SessionStatusDoc => ({
  uid: "u",
  state,
  step: null,
  progress: 10,
  error_code: null,
  latest_report_version: null,
  updated_at,
  transcript_ready: false,
  speaker_confirmed: false,
  rating_submitted: false,
  has_rating: false,
});
const quiet = { current: false };
const mount = () => renderHook(() => useSessionStatus("s1", quiet));
const advance = (ms: number) => act(() => void vi.advanceTimersByTime(ms));

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-20T10:00:00Z"));
  get.mockReset();
  get.mockResolvedValue({ data: {}, response: { ok: true } });
  emitter.clear();
  setStatusListener(emitter);
});
afterEach(() => vi.useRealTimers());

describe("useSessionStatus: stale transcribing nudge", () => {
  it("makes no call before 6 min, one at the threshold, then at most one per 60 s", () => {
    mount();
    act(() => emitter.emit("s1", doc("transcribing")));
    advance(6 * MIN - 1);
    expect(get).not.toHaveBeenCalled();
    advance(1);
    expect(get).toHaveBeenCalledTimes(1);
    expect(get.mock.calls[0]![0]).toBe("/sessions/{id}");
    advance(MIN - 1);
    expect(get).toHaveBeenCalledTimes(1);
    advance(1);
    expect(get).toHaveBeenCalledTimes(2);
    advance(3 * MIN);
    expect(get).toHaveBeenCalledTimes(5);
  });

  it("counts from the doc's updated_at: an already-old doc nudges at once", () => {
    mount();
    act(() => emitter.emit("s1", doc("transcribing", new Date(Date.now() - 7 * MIN).toISOString())));
    advance(0);
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("a fresh updated_at (progress) pushes the first nudge out", () => {
    mount();
    act(() => emitter.emit("s1", doc("transcribing")));
    advance(5 * MIN);
    act(() => emitter.emit("s1", doc("transcribing")));
    advance(5 * MIN);
    expect(get).not.toHaveBeenCalled();
    advance(MIN);
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("stops when the state changes", () => {
    mount();
    act(() => emitter.emit("s1", doc("transcribing")));
    advance(6 * MIN);
    expect(get).toHaveBeenCalledTimes(1);
    act(() => emitter.emit("s1", doc("failed")));
    advance(10 * MIN);
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("stops on unmount", () => {
    const { unmount } = mount();
    act(() => emitter.emit("s1", doc("transcribing")));
    advance(6 * MIN);
    unmount();
    advance(10 * MIN);
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("ignores a failing call and keeps nudging", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    get.mockRejectedValue(new Error("boom"));
    mount();
    act(() => emitter.emit("s1", doc("transcribing")));
    advance(6 * MIN);
    await act(async () => void (await Promise.resolve()));
    advance(MIN);
    expect(get).toHaveBeenCalledTimes(2);
    warn.mockRestore();
  });

  it("never nudges for other states", () => {
    mount();
    act(() => emitter.emit("s1", doc("running")));
    advance(20 * MIN);
    expect(get).not.toHaveBeenCalled();
  });
});
