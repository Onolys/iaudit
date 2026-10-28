import { afterEach, describe, expect, it, vi } from "vitest";
import { retry } from "./retry";

afterEach(() => vi.useRealTimers());

describe("retry", () => {
  it("returns the first result and passes attempt 1 and the supplied signal", async () => {
    const controller = new AbortController();
    const calls: unknown[] = [];
    const result = await retry(async (attempt, signal) => {
      calls.push([attempt, signal]);
      return "done";
    }, { shouldRetry: () => false, signal: controller.signal });
    expect(result).toBe("done");
    expect(calls).toEqual([[1, controller.signal]]);
  });

  it("retries a rejected value once by default and exposes discriminated outcomes", async () => {
    const outcomes: unknown[] = [];
    const calls: number[] = [];
    const delays: number[] = [];
    expect(await retry(async (attempt) => {
      calls.push(attempt);
      return attempt === 1 ? "pending" : "done";
    }, {
      shouldRetry: (outcome) => { outcomes.push(outcome); return outcome.ok && outcome.value === "pending"; },
      sleep: async (ms) => { delays.push(ms); },
    })).toBe("done");
    expect(calls).toEqual([1, 2]);
    expect(outcomes).toEqual([{ ok: true, value: "pending" }, { ok: true, value: "done" }]);
    expect(delays).toEqual([0]);
  });

  it("retries an error then returns success", async () => {
    const failure = new Error("temporary");
    const outcomes: unknown[] = [];
    expect(await retry(async (attempt) => {
      if (attempt === 1) throw failure;
      return "recovered";
    }, { shouldRetry: (outcome) => { outcomes.push(outcome); return !outcome.ok; } })).toBe("recovered");
    expect(outcomes).toEqual([{ ok: false, error: failure }, { ok: true, value: "recovered" }]);
  });

  it("returns the last value on exhaustion", async () => {
    expect(await retry(async (attempt) => attempt, { shouldRetry: () => true })).toBe(2);
  });

  it("raises the last error on exhaustion", async () => {
    const errors = [new Error("first"), new Error("last")];
    await expect(retry(async (attempt) => { throw errors[attempt - 1]; }, {
      shouldRetry: () => true,
    })).rejects.toBe(errors[1]);
  });

  it("does not retry an error rejected by the predicate", async () => {
    const calls: number[] = [];
    const failure = new Error("permanent");
    await expect(retry(async (attempt) => { calls.push(attempt); throw failure; }, {
      shouldRetry: () => false,
    })).rejects.toBe(failure);
    expect(calls).toEqual([1]);
  });

  it("checks canContinue only between attempts and returns the last value", async () => {
    const events: string[] = [];
    expect(await retry(async (attempt) => { events.push(`attempt ${attempt}`); return "pending"; }, {
      shouldRetry: () => true,
      canContinue: () => { events.push("can continue"); return false; },
      sleep: async () => { events.push("sleep"); },
    })).toBe("pending");
    expect(events).toEqual(["attempt 1", "can continue"]);
  });

  it("raises the last error when canContinue stops retries", async () => {
    const failure = new Error("deadline");
    const calls: number[] = [];
    await expect(retry(async (attempt) => { calls.push(attempt); throw failure; }, {
      shouldRetry: () => true, canContinue: () => false,
    })).rejects.toBe(failure);
    expect(calls).toEqual([1]);
  });

  it("does not consult canContinue after a terminal outcome", async () => {
    let checks = 0;
    expect(await retry(async () => "done", {
      attempts: 1, shouldRetry: () => true, canContinue: () => { checks++; return true; },
    })).toBe("done");
    expect(checks).toBe(0);
  });

  it("uses exponential delays and forwards the signal to injected sleep", async () => {
    const controller = new AbortController();
    const delays: unknown[] = [];
    expect(await retry(async (attempt) => attempt, {
      shouldRetry: () => true, attempts: 4, delayMs: 10, backoff: 2, signal: controller.signal,
      sleep: async (ms, signal) => { delays.push([ms, signal]); },
    })).toBe(4);
    expect(delays).toEqual([[10, controller.signal], [20, controller.signal], [40, controller.signal]]);
  });

  it("defaults to constant backoff", async () => {
    const delays: number[] = [];
    await retry(async () => "pending", {
      shouldRetry: () => true, attempts: 3, delayMs: 5,
      sleep: async (ms) => { delays.push(ms); },
    });
    expect(delays).toEqual([5, 5]);
  });

  it("never retries an AbortError even if the predicate would allow it", async () => {
    const failure = new DOMException("cancelled", "AbortError");
    const calls: number[] = [];
    await expect(retry(async (attempt) => { calls.push(attempt); throw failure; }, {
      shouldRetry: () => true,
    })).rejects.toBe(failure);
    expect(calls).toEqual([1]);
  });

  it("rejects an already aborted signal before calling fn", async () => {
    const controller = new AbortController();
    const reason = new Error("stopped");
    controller.abort(reason);
    let calls = 0;
    await expect(retry(async () => { calls++; return "done"; }, {
      shouldRetry: () => true, signal: controller.signal,
    })).rejects.toBe(reason);
    expect(calls).toBe(0);
  });

  it("rejects immediately when aborted during the default sleep", async () => {
    vi.useFakeTimers();
    const controller = new AbortController();
    const calls: number[] = [];
    const pending = retry(async (attempt) => { calls.push(attempt); return "pending"; }, {
      shouldRetry: () => true, signal: controller.signal, delayMs: 10_000,
    });
    const rejected = expect(pending).rejects.toMatchObject({ name: "AbortError" });
    await vi.advanceTimersByTimeAsync(0);
    expect(vi.getTimerCount()).toBe(1);
    controller.abort();
    await rejected;
    expect(calls).toEqual([1]);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("rejects immediately on abort even when an injected sleep ignores the signal", async () => {
    const controller = new AbortController();
    let enteredSleep!: () => void;
    const sleeping = new Promise<void>((resolve) => { enteredSleep = resolve; });
    const calls: number[] = [];
    const pending = retry(async (attempt) => { calls.push(attempt); return "pending"; }, {
      shouldRetry: () => true, signal: controller.signal,
      sleep: async () => { enteredSleep(); await new Promise<void>(() => {}); },
    });
    const rejected = expect(pending).rejects.toMatchObject({ name: "AbortError" });
    await sleeping;
    controller.abort();
    await rejected;
    expect(calls).toEqual([1]);
  });
});
