import { useCallback, useEffect, useRef, useState } from "react";
import type { AuditRequest } from "../contract";
import { isRetryable } from "./errors";
import type { LoadError, LoadResult } from "./errors";
import { auditRequest, readRequestFile } from "./runAudit";
import type { AuditDeps } from "./runAudit";

export type LoaderState =
  | { status: "idle" }
  | { status: "loading"; fileName: string; requestId?: string }
  | { status: "ok"; fileName: string; result: LoadResult }
  | { status: "error"; fileName?: string; error: LoadError };

export interface AuditLoader {
  state: LoaderState;
  loadFile: (file: File) => Promise<void>;
  retry: () => void;
  cancel: () => void;
  reset: () => void;
}

export function useAuditLoader(deps?: AuditDeps): AuditLoader {
  const [state, setState] = useState<LoaderState>({ status: "idle" });
  const stateRef = useRef<LoaderState>(state);
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const lastRequest = useRef<AuditRequest | null>(null);
  const depsRef = useRef(deps);
  depsRef.current = deps;

  const commit = useCallback((next: LoaderState) => {
    stateRef.current = next;
    setState(next);
  }, []);

  /** Start a new attempt: abort the previous one and invalidate its completions. */
  const begin = useCallback(() => {
    controller.current?.abort();
    const ctl = new AbortController();
    controller.current = ctl;
    return { ctl, gen: ++generation.current };
  }, []);

  const send = useCallback(
    async (request: AuditRequest, fileName: string, ctl: AbortController, gen: number) => {
      const current = () => generation.current === gen;
      if (ctl.signal.aborted) {
        if (current()) commit({ status: "error", fileName, error: { kind: "cancelled" } });
        return;
      }
      const result = await auditRequest(request, { signal: ctl.signal, deps: depsRef.current });
      if (!current()) return;
      // Cancel wins even when the work finished first (e.g. mock fixtures still loading).
      if (ctl.signal.aborted) {
        commit({ status: "error", fileName, error: { kind: "cancelled" } });
        return;
      }
      commit(result.ok ? { status: "ok", fileName, result: result.value } : { status: "error", fileName, error: result.error });
    },
    [commit],
  );

  const loadFile = useCallback(
    async (file: File) => {
      const { ctl, gen } = begin();
      lastRequest.current = null;
      commit({ status: "loading", fileName: file.name });
      const read = await readRequestFile(file);
      if (generation.current !== gen) return;
      if (!read.ok) {
        commit({ status: "error", fileName: file.name, error: read.error });
        return;
      }
      lastRequest.current = read.value;
      commit({ status: "loading", fileName: file.name, requestId: read.value.request_id });
      await send(read.value, file.name, ctl, gen);
    },
    [begin, commit, send],
  );

  const retry = useCallback(() => {
    const s = stateRef.current;
    const request = lastRequest.current;
    if (s.status !== "error" || !isRetryable(s.error) || !request) return;
    const fileName = s.fileName ?? "";
    const { ctl, gen } = begin();
    commit({ status: "loading", fileName, requestId: request.request_id });
    void send(request, fileName, ctl, gen);
  }, [begin, commit, send]);

  // The in-flight attempt resolves itself with `cancelled`.
  const cancel = useCallback(() => {
    if (stateRef.current.status === "loading") controller.current?.abort();
  }, []);

  const reset = useCallback(() => {
    controller.current?.abort();
    generation.current++;
    lastRequest.current = null;
    commit({ status: "idle" });
  }, [commit]);

  useEffect(
    () => () => {
      controller.current?.abort();
      generation.current++;
    },
    [],
  );

  return { state, loadFile, retry, cancel, reset };
}
