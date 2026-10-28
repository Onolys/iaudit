type Outcome<T> = { ok: true; value: T } | { ok: false; error: unknown };
type Sleep = (ms: number, signal?: AbortSignal) => Promise<void>;

/** Wait between attempts, including when an injected sleep ignores cancellation. */
function pause(ms: number, signal?: AbortSignal, sleep?: Sleep): Promise<void> {
  signal?.throwIfAborted();
  return new Promise((resolve, reject) => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const cleanup = () => {
      if (timer !== undefined) clearTimeout(timer);
      signal?.removeEventListener("abort", onAbort);
    };
    const done = () => { cleanup(); resolve(); };
    const fail = (error: unknown) => { cleanup(); reject(error); };
    const onAbort = () => fail(signal!.reason);
    signal?.addEventListener("abort", onAbort, { once: true });
    if (sleep) {
      try {
        sleep(ms, signal).then(done, fail);
      } catch (error) {
        fail(error);
      }
    } else {
      timer = setTimeout(done, ms);
    }
  });
}

/** Retry outcomes selected by the caller; attempts are numbered from one. */
export async function retry<T>(fn: (attempt: number, signal?: AbortSignal) => Promise<T>, o: {
  shouldRetry: (outcome: Outcome<T>) => boolean;
  attempts?: number; delayMs?: number; backoff?: number; canContinue?: () => boolean; signal?: AbortSignal;
  sleep?: Sleep;
}): Promise<T> {
  const { attempts = 2, delayMs = 0, backoff = 1, signal } = o;
  for (let attempt = 1; ; attempt++) {
    signal?.throwIfAborted();
    let outcome: Outcome<T>;
    try {
      outcome = { ok: true, value: await fn(attempt, signal) };
    } catch (error) {
      signal?.throwIfAborted();
      if (typeof error === "object" && error !== null && "name" in error && error.name === "AbortError") {
        throw error;
      }
      outcome = { ok: false, error };
    }
    signal?.throwIfAborted();
    const shouldRetry = o.shouldRetry(outcome);
    if (!shouldRetry || attempt >= attempts || (o.canContinue && !o.canContinue())) {
      if (outcome.ok) return outcome.value;
      throw outcome.error;
    }
    await pause(delayMs * backoff ** (attempt - 1), signal, o.sleep);
  }
}
