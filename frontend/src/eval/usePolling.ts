import { useEffect, useRef, useState } from "react";
import type { Result } from "../contract";

interface PollingOptions<T> {
  intervalMs?: number;
  enabled: boolean;
  isTerminal: (data: T) => boolean;
}
interface PollingState<T, E> {
  data: T | null;
  error: E | null;
  misses: number;
  stale: boolean;
}

/** Keep fn stable (useCallback); a replacement starts a fresh resource generation. */
export function usePolling<T, E>(
  fn: (signal: AbortSignal) => Promise<Result<T, E>>,
  { intervalMs = 1000, enabled, isTerminal }: PollingOptions<T>,
): PollingState<T, E> {
  const [state, setState] = useState<PollingState<T, E>>({ data: null, error: null, misses: 0, stale: false });
  const generation = useRef(0);
  const terminal = useRef(isTerminal);
  terminal.current = isTerminal;

  useEffect(() => {
    const currentGeneration = ++generation.current;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;
    const current = () => generation.current === currentGeneration;

    if (enabled) {
      setState({ data: null, error: null, misses: 0, stale: false });
      const poll = async () => {
        controller = new AbortController();
        const reply = await fn(controller.signal);
        if (!current()) return;
        if (reply.ok) {
          setState({ data: reply.value, error: null, misses: 0, stale: false });
          if (terminal.current(reply.value)) return;
        } else {
          setState((previous) => {
            const misses = previous.misses + 1;
            return { ...previous, error: reply.error, misses, stale: misses >= 3 };
          });
        }
        timer = setTimeout(() => void poll(), intervalMs);
      };
      void poll();
    }

    return () => {
      generation.current++;
      controller?.abort();
      clearTimeout(timer);
    };
  }, [fn, intervalMs, enabled]);

  return state;
}
