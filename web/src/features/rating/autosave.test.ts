import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createAutosaver, type SaveStatus } from "./autosave";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

const make = (save = vi.fn().mockResolvedValue(undefined), extra = {}) => {
  const statuses: SaveStatus[] = [];
  const a = createAutosaver({ save, onStatus: (s) => statuses.push(s), delayMs: 2000, retryMs: 5000, ...extra });
  return { a, save, statuses };
};

describe("autosaver", () => {
  it("saves once, about 2 s after the last change", async () => {
    const { a, save } = make();
    a.change();
    await vi.advanceTimersByTimeAsync(1500);
    a.change(); // restarts the wait
    await vi.advanceTimersByTimeAsync(1500);
    expect(save).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(600);
    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenCalledWith(false);
  });

  it("flush saves at once (blur) and the timer then does not save again", async () => {
    const { a, save } = make();
    a.change();
    await a.flush();
    expect(save).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(5000);
    expect(save).toHaveBeenCalledTimes(1);
  });

  it("flush with keepalive passes the flag; flush with nothing changed does nothing", async () => {
    const { a, save } = make();
    await a.flush({ keepalive: true });
    expect(save).not.toHaveBeenCalled();
    a.change();
    await a.flush({ keepalive: true });
    expect(save).toHaveBeenCalledWith(true);
  });

  it("reports saving then saved", async () => {
    const { a, statuses } = make();
    a.change();
    await a.flush();
    expect(statuses).toEqual(["saving", "saved"]);
  });

  it("retries after a failure and says so", async () => {
    const save = vi.fn().mockRejectedValueOnce(new Error("net")).mockResolvedValue(undefined);
    const { a, statuses } = make(save);
    a.change();
    await a.flush();
    expect(statuses.at(-1)).toBe("error");
    await vi.advanceTimersByTimeAsync(5100);
    expect(save).toHaveBeenCalledTimes(2);
    expect(statuses.at(-1)).toBe("saved");
  });

  it("stops (no retry) when the failure is permanent", async () => {
    const save = vi.fn().mockRejectedValue(new Error("422"));
    const { a, statuses } = make(save, { isPermanent: () => true });
    a.change();
    await a.flush();
    await vi.advanceTimersByTimeAsync(20000);
    expect(save).toHaveBeenCalledTimes(1);
    expect(statuses.at(-1)).toBe("invalid");
  });

  it("a change during a save is saved afterwards, in order", async () => {
    let release = () => {};
    const save = vi.fn().mockImplementationOnce(() => new Promise<void>((r) => (release = r))).mockResolvedValue(undefined);
    const { a } = make(save);
    a.change();
    const first = a.flush();
    await vi.advanceTimersByTimeAsync(0); // the save has started
    a.change();
    release();
    await first;
    await vi.advanceTimersByTimeAsync(2100);
    expect(save).toHaveBeenCalledTimes(2);
  });

  it("cancel drops a pending save; dispose stops timers", async () => {
    const { a, save } = make();
    a.change();
    a.cancel();
    await vi.advanceTimersByTimeAsync(5000);
    expect(save).not.toHaveBeenCalled();
    a.change();
    a.dispose();
    await vi.advanceTimersByTimeAsync(5000);
    expect(save).not.toHaveBeenCalled();
  });
});
