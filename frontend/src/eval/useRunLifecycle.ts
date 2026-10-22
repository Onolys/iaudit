import { useCallback, useEffect, useRef, useState } from "react";
import type { EvalApi } from "./evalApi";
import type { EvalError, RunDetail, RunRequest } from "./evalTypes";
import { usePolling } from "./usePolling";

interface Options {
  api: EvalApi;
  onRunsChanged?: () => void;
  onActiveRunChange?: (run: RunDetail | null) => void;
  onDownloaded: () => void;
  attachment?: { runId: string };
  onRunActiveChange?: (active: boolean) => void;
}
/** Owns all run/download requests; unmount cancels local work without aborting the server run. */
export function useRunLifecycle({ api, onRunsChanged, onActiveRunChange, onDownloaded, attachment, onRunActiveChange }: Options) {
  const [runId, setRunId] = useState<string | null>(null);
  const [epoch, setEpoch] = useState(0);
  const [busy, setBusy] = useState(false);
  const [aborting, setAborting] = useState(false);
  const [error, setError] = useState<EvalError | null>(null);
  const [conflict, setConflict] = useState<string | null>(null);
  const [missingDataset, setMissingDataset] = useState<string | null>(null);
  const [download, setDownload] = useState<{ dataset: string; attempt: number } | null>(null);
  const [downloadError, setDownloadError] = useState<string | EvalError | null>(null);
  const [downloadStarting, setDownloadStarting] = useState(false);
  const requests = useRef(new Set<AbortController>());
  const downloadRequest = useRef<AbortController | null>(null);
  const runStateRef = useRef<string | null>(null);
  const interaction = useRef(0);
  const callbacks = useRef({ onRunsChanged, onActiveRunChange, onDownloaded });
  callbacks.current = { onRunsChanged, onActiveRunChange, onDownloaded };
  const pollRun = useCallback(async (signal: AbortSignal) => {
    const result = await api.getRun(runId!, { signal });
    return result.ok ? { ok: true as const, value: { run: result.value, epoch } } : result;
  }, [api, runId, epoch]);
  const runPoll = usePolling(pollRun, { enabled: runId !== null, isTerminal: value => value.run.state !== "running" });
  const run = runPoll.data?.epoch === epoch && runPoll.data.run.run_id === runId ? runPoll.data.run : null;
  runStateRef.current = run?.state ?? null;
  // Tag each poll result with its attempt so data from a previous attempt is never mistaken for this one.
  const pollDownload = useCallback(async (signal: AbortSignal) => {
    const result = await api.getDownload(download!.dataset, { signal });
    return result.ok ? { ok: true as const, value: { status: result.value, attempt: download!.attempt } } : result;
  }, [api, download]);
  const downloadPoll = usePolling(pollDownload, { enabled: download !== null, isTerminal: value => value.status.status === "ready" || value.status.status === "failed" });

  useEffect(() => {
    const controller = new AbortController();
    const generation = interaction.current;
    void api.listRuns({ signal: controller.signal }).then(result => {
      if (controller.signal.aborted || interaction.current !== generation) return;
      // Health owns initial connection errors; a start conflict can still attach later.
      if (!result.ok) return;
      const active = result.value.find(value => value.state === "running");
      if (active) setRunId(active.run_id);
    });
    return () => { controller.abort(); requests.current.forEach(request => request.abort()); requests.current.clear(); };
  }, [api]);

  useEffect(() => {
    if (!attachment) return;
    interaction.current++;
    setError(null); setConflict(null); setRunId(attachment.runId); setEpoch(value => value + 1);
  }, [attachment]);

  useEffect(() => {
    if (!run) return;
    callbacks.current.onActiveRunChange?.(run);
    if (run.state !== "running") callbacks.current.onRunsChanged?.();
  }, [run]);

  useEffect(() => {
    if (!download || !downloadPoll.data || downloadPoll.data.attempt !== download.attempt) return;
    const status = downloadPoll.data.status;
    if (status.status === "ready") {
      setDownload(null); setMissingDataset(null); setDownloadError(null);
      callbacks.current.onDownloaded();
    } else if (status.status === "failed") {
      setDownloadError(status.error || "Download failed");
    }
  }, [downloadPoll.data, download]);

  async function start(request: RunRequest) {
    if (busy || run?.state === "running" || (runId && !run)) return;
    interaction.current++;
    const controller = new AbortController(); requests.current.add(controller);
    setBusy(true); setError(null); setConflict(null);
    const result = await api.startRun(request, { signal: controller.signal });
    requests.current.delete(controller);
    if (controller.signal.aborted) return;
    setBusy(false);
    if (result.ok) { setRunId(result.value.run_id); setEpoch(value => value + 1); callbacks.current.onRunsChanged?.(); return; }
    if (result.error.kind === "api" && result.error.code === "data_missing") setMissingDataset(request.dataset);
    else if (result.error.kind === "api" && result.error.code === "run_active") {
      const detail = result.error.detail;
      const id = detail && typeof detail === "object" && "run_id" in detail ? detail.run_id : null;
      if (typeof id === "string") setConflict(id);
      else setError(result.error);
    } else setError(result.error);
  }
  async function abort() {
    if (!runId || aborting) return;
    const controller = new AbortController(); requests.current.add(controller);
    setAborting(true); setError(null);
    const result = await api.abortRun(runId, { signal: controller.signal });
    requests.current.delete(controller);
    if (controller.signal.aborted) return;
    setAborting(false);
    if (result.ok) callbacks.current.onRunsChanged?.();
    // The server abort can outlast the POST timeout; a poll that already shows the run stopped wins.
    else if (!(result.error.kind === "timeout" && runStateRef.current !== null && runStateRef.current !== "running")) setError(result.error);
  }
  async function startDownload(dataset: string) {
    if (downloadStarting) return;
    const controller = new AbortController(); requests.current.add(controller); downloadRequest.current = controller;
    setDownloadStarting(true); setDownload(null); setDownloadError(null);
    const result = await api.startDownload(dataset, { signal: controller.signal });
    requests.current.delete(controller);
    if (controller.signal.aborted) return;
    downloadRequest.current = null;
    setDownloadStarting(false);
    if (result.ok) setDownload({ dataset, attempt: ++interaction.current });
    else setDownloadError(result.error);
  }
  /** A different dataset was selected: forget the previous dataset's download state. */
  function resetDownload() {
    downloadRequest.current?.abort(); downloadRequest.current = null;
    setDownloadStarting(false); setDownload(null); setDownloadError(null);
  }
  const downloading = downloadStarting || (!!download && !downloadError);
  const active = !!runId && (!run || run.state === "running");
  useEffect(() => { onRunActiveChange?.(active || busy); }, [active, busy, onRunActiveChange]);
  function attachConflict() {
    if (!conflict) return;
    interaction.current++; setRunId(conflict); setEpoch(value => value + 1); setConflict(null);
  }
  const progress = { error, conflict, run, aborting, downloading, downloadError, lostContact: !!(runPoll.stale && active || downloadPoll.stale && downloading), abort: () => void abort(), attachConflict };
  return { start, startDownload, missingDataset, downloading, downloadError, busy, active, resetDownload, progress };
}
