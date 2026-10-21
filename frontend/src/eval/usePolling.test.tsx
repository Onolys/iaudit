// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Result } from "../contract";
import { usePolling } from "./usePolling";

type Item = { id: string; done: boolean };
type Failure = { reason: string };
type Reply = Result<Item, Failure>;
const running: Item = { id: "fictional-a", done: false };
const finished: Item = { id: "fictional-a", done: true };
const ok = (value: Item): Reply => ({ ok: true, value });
const failure: Reply = { ok: false, error: { reason: "offline" } };
const isTerminal = (item: Item) => item.done;

function deferredPoll() {
  const calls: { signal: AbortSignal; resolve: (reply: Reply) => void }[] = [];
  const fn = (signal: AbortSignal) => new Promise<Reply>((resolve) => calls.push({ signal, resolve }));
  return { fn, calls };
}
const tick = (ms = 1000) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });
const resolve = (poll: ReturnType<typeof deferredPoll>, index: number, reply: Reply) =>
  act(async () => { poll.calls[index].resolve(reply); });

beforeEach(() => vi.useFakeTimers());
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe("usePolling", () => {
  it("polls immediately and waits one second after settlement without overlapping", async () => {
    const poll = deferredPoll();
    const { result } = renderHook(() => usePolling(poll.fn, { enabled: true, isTerminal }));
    expect(poll.calls).toHaveLength(1);
    expect(result.current).toEqual({ data: null, error: null, misses: 0, stale: false });
    await tick(5000);
    expect(poll.calls).toHaveLength(1);
    await resolve(poll, 0, ok(running));
    expect(result.current.data).toEqual(running);
    await tick(999);
    expect(poll.calls).toHaveLength(1);
    await tick(1);
    expect(poll.calls).toHaveLength(2);
    await tick(5000);
    expect(poll.calls).toHaveLength(2);
  });

  it("honors a custom interval", async () => {
    const poll = deferredPoll();
    renderHook(() => usePolling(poll.fn, { enabled: true, intervalMs: 250, isTerminal }));
    await resolve(poll, 0, ok(running));
    await tick(249);
    expect(poll.calls).toHaveLength(1);
    await tick(1);
    expect(poll.calls).toHaveLength(2);
  });

  it("stops when a successful reply is terminal", async () => {
    const poll = deferredPoll();
    const { result } = renderHook(() => usePolling(poll.fn, { enabled: true, isTerminal }));
    await resolve(poll, 0, ok(finished));
    expect(result.current.data).toEqual(finished);
    await tick(10000);
    expect(poll.calls).toHaveLength(1);
  });

  it("keeps the last data through three misses and clears stale and error on recovery", async () => {
    const poll = deferredPoll();
    const { result } = renderHook(() => usePolling(poll.fn, { enabled: true, isTerminal }));
    await resolve(poll, 0, ok(running));
    for (const misses of [1, 2, 3]) {
      await tick();
      await resolve(poll, misses, failure);
      expect(result.current).toEqual({ data: running, error: { reason: "offline" }, misses, stale: misses >= 3 });
    }
    await tick();
    await resolve(poll, 4, ok(finished));
    expect(result.current).toEqual({ data: finished, error: null, misses: 0, stale: false });
  });

  it("counts failures before any data has arrived", async () => {
    const poll = deferredPoll();
    const { result } = renderHook(() => usePolling(poll.fn, { enabled: true, isTerminal }));
    await resolve(poll, 0, failure);
    expect(result.current).toEqual({ data: null, error: { reason: "offline" }, misses: 1, stale: false });
  });

  it("does not fetch while initially disabled and polls immediately on enable", async () => {
    const poll = deferredPoll();
    const { rerender } = renderHook(({ enabled }) => usePolling(poll.fn, { enabled, isTerminal }), { initialProps: { enabled: false } });
    await tick(10000);
    expect(poll.calls).toHaveLength(0);
    rerender({ enabled: true });
    expect(poll.calls).toHaveLength(1);
  });

  it("aborts on disable and ignores a late reply without scheduling another tick", async () => {
    const poll = deferredPoll();
    const { result, rerender } = renderHook(({ enabled }) => usePolling(poll.fn, { enabled, isTerminal }), { initialProps: { enabled: true } });
    rerender({ enabled: false });
    expect(poll.calls[0].signal.aborted).toBe(true);
    await resolve(poll, 0, ok(finished));
    expect(result.current.data).toBeNull();
    await tick(10000);
    expect(poll.calls).toHaveLength(1);
  });

  it("clears a pending timer on disable and restarts on enable", async () => {
    const poll = deferredPoll();
    const { rerender } = renderHook(({ enabled }) => usePolling(poll.fn, { enabled, isTerminal }), { initialProps: { enabled: true } });
    await resolve(poll, 0, ok(running));
    rerender({ enabled: false });
    await tick(10000);
    expect(poll.calls).toHaveLength(1);
    rerender({ enabled: true });
    expect(poll.calls).toHaveLength(2);
  });

  it("aborts in-flight work on unmount and drops its late completion", async () => {
    const poll = deferredPoll();
    const { unmount } = renderHook(() => usePolling(poll.fn, { enabled: true, isTerminal }));
    unmount();
    expect(poll.calls[0].signal.aborted).toBe(true);
    await resolve(poll, 0, ok(running));
    await tick(10000);
    expect(poll.calls).toHaveLength(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("clears the scheduled tick on unmount", async () => {
    const poll = deferredPoll();
    const { unmount } = renderHook(() => usePolling(poll.fn, { enabled: true, isTerminal }));
    await resolve(poll, 0, ok(running));
    unmount();
    expect(vi.getTimerCount()).toBe(0);
    await tick(10000);
    expect(poll.calls).toHaveLength(1);
  });

  it("resets data and misses for a replacement resource and drops the prior generation", async () => {
    const first = deferredPoll();
    const second = deferredPoll();
    const { result, rerender } = renderHook(({ fn }) => usePolling(fn, { enabled: true, isTerminal }), { initialProps: { fn: first.fn } });
    await resolve(first, 0, ok(running));
    await tick();
    await resolve(first, 1, failure);
    await tick();
    rerender({ fn: second.fn });
    expect(first.calls[2].signal.aborted).toBe(true);
    expect(result.current).toEqual({ data: null, error: null, misses: 0, stale: false });
    await resolve(second, 0, ok({ id: "fictional-b", done: false }));
    await resolve(first, 2, ok(finished));
    expect(result.current.data).toEqual({ id: "fictional-b", done: false });
    await tick();
    expect(first.calls).toHaveLength(3);
    expect(second.calls).toHaveLength(2);
  });

  it("does not restart when an inline terminal predicate changes identity", async () => {
    const poll = deferredPoll();
    const { result, rerender } = renderHook(({ terminal }) => usePolling(poll.fn, {
      enabled: true, isTerminal: (item) => terminal && item.done,
    }), { initialProps: { terminal: false } });
    await resolve(poll, 0, ok(running));
    expect(result.current.data).toEqual(running);
    rerender({ terminal: true });
    expect(poll.calls).toHaveLength(1);
    await tick();
    await resolve(poll, 1, ok(finished));
    await tick(10000);
    expect(poll.calls).toHaveLength(2);
  });
});
