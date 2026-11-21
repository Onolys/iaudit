/**
 * `/sessions/:id/reports/:version` (PRD R4, D17): the evidence-linked report. Two panes on desktop
 * (report left, sticky transcript right), one column with a Transcript tab on mobile.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { unwrap } from "../../api/client";
import { ApiError, describeError } from "../../api/errors";
import type { Report } from "../../api/report";
import { useApiClient } from "../../auth/useApiClient";
import { formatResetTime } from "../../lib/format";
import { RatingCard } from "../rating/RatingCard";
import { ErrorCard } from "../session/ErrorCard";
import { TranscriptPanel } from "../transcript/TranscriptPanel";
import { useSelectedInstance } from "../transcript/useSelectedInstance";
import { reportHighlights } from "./lines";
import { ReportSections } from "./ReportSections";

/** Major version of the report schema this UI understands. */
const SUPPORTED_MAJOR = 0;
const major = (v: string | undefined) => Number.parseInt((v ?? "").split(".")[0] ?? "", 10);

export function ReportPage() {
  const { id = "", version = "" } = useParams();
  return <ReportView key={`${id}/${version}`} id={id} version={version} />;
}

function NotFound({ id }: { id: string }) {
  return (
    <>
      <h1>Report</h1>
      <p>We couldn't find that report.</p>
      <p>
        <Link to={`/sessions/${id}`}>Back to the session</Link>
      </p>
    </>
  );
}

function ReportView({ id, version }: { id: string; version: string }) {
  const valid = /^[1-9]\d*$/.test(version);
  return valid ? <LoadedReport id={id} version={Number(version)} /> : <NotFound id={id} />;
}

function LoadedReport({ id, version }: { id: string; version: number }) {
  const client = useApiClient();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [, select] = useSelectedInstance();
  const [tab, setTab] = useState<"report" | "transcript">("report");
  const [editingRating, setEditingRating] = useState(false);

  const view = useQuery({
    queryKey: ["report", id, version],
    staleTime: 0,
    gcTime: 0,
    retry: false,
    queryFn: async () =>
      unwrap(await client.GET("/sessions/{id}/reports/{version}", { params: { path: { id, version } } })),
  });
  const versions = useQuery({
    queryKey: ["reports", id],
    staleTime: 0,
    gcTime: 0,
    queryFn: async () => unwrap(await client.GET("/sessions/{id}/reports", { params: { path: { id } } })),
  });
  const usage = useQuery({
    queryKey: ["usage"],
    queryFn: async () => unwrap(await client.GET("/usage")),
  });
  const atCap = usage.data ? usage.data.runs_today >= usage.data.daily_cap : false;
  const resetsAt = formatResetTime(usage.data?.resets_at);

  const run = useMutation({
    mutationFn: async () => unwrap(await client.POST("/sessions/{id}/runs", { params: { path: { id } } })),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["usage"] });
      void navigate(`/sessions/${id}`);
    },
  });

  const report = view.data?.report as Report | undefined;
  const highlights = useMemo(() => (report ? reportHighlights(report) : []), [report]);

  if (view.isPending) {
    return (
      <>
        <h1>Report</h1>
        <p className="form-note">Loading report…</p>
      </>
    );
  }
  if (view.isError || !view.data || !report) {
    if (view.error instanceof ApiError && view.error.status === 404) return <NotFound id={id} />;
    const e = describeError(view.error);
    return (
      <>
        <h1>Report</h1>
        <ErrorCard code={e.code} reference={e.requestId}>
          <button type="button" className="link-button" onClick={() => void view.refetch()}>
            Try again
          </button>
        </ErrorCard>
      </>
    );
  }

  const newer = Number.isFinite(major(view.data.report_schema_version)) && major(view.data.report_schema_version) !== SUPPORTED_MAJOR;
  const h = report.header;
  const runError = run.error ? describeError(run.error, { resetsAt }) : null;
  const date = (iso: string) => new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  const details = [
    h.stt ? [h.stt.provider, h.stt.model].filter(Boolean).join(" ") : null,
    h.preset,
    h.code_version,
  ].filter(Boolean);
  const onSelect = (instanceId: string) => {
    select(instanceId);
    setTab("transcript");
  };

  return (
    <div className="report-page">
      <header className="report-header">
        <h1>Report</h1>
        {newer ? (
          <p className="notice" role="alert">
            This report was made by a newer version — refresh
          </p>
        ) : null}
        {h.change_goal ? <p className="report-goal">{h.change_goal}</p> : null}
        <p>
          {h.protocol?.label} · {date(view.data.created_at)}
          {h.models && Object.keys(h.models).length ? ` · ${[...new Set(Object.values(h.models))].join(", ")}` : ""}
        </p>
        <p className="form-note">Run details: {details.join(" · ") || "not recorded"}</p>
        <div className="report-actions">
          <label>
            Version{" "}
            <select
              value={String(version)}
              onChange={(e) => void navigate(`/sessions/${id}/reports/${e.target.value}`)}
            >
              {(versions.data?.items ?? [{ version, created_at: view.data.created_at }]).map((v) => (
                <option key={v.version} value={String(v.version)}>
                  v{v.version} · {date(v.created_at)}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="btn btn-primary" disabled={run.isPending || atCap} onClick={() => run.mutate()}>
            Run again
          </button>
          <button type="button" className="btn btn-secondary" aria-expanded={editingRating} onClick={() => setEditingRating((v) => !v)}>
            Add or edit my rating → Run again
          </button>
        </div>
        {atCap ? <p className="form-note">You've reached today's limit. You can run again after {resetsAt}.</p> : null}
        {runError ? <ErrorCard code={runError.code} reference={runError.requestId} resetsAt={resetsAt} /> : null}
      </header>

      {editingRating ? (
        <div className="report-rating">
          <RatingCard sessionId={id} submitLabel="Submit and run again" onSubmitted={async () => void (await run.mutateAsync())} />
        </div>
      ) : null}

      <div className="report-tabs" role="tablist" aria-label="Report or transcript">
        <button type="button" role="tab" aria-selected={tab === "report"} onClick={() => setTab("report")}>
          Report
        </button>
        <button type="button" role="tab" aria-selected={tab === "transcript"} onClick={() => setTab("transcript")}>
          Transcript
        </button>
      </div>

      <div className="report-panes" data-tab={tab}>
        <div className="report-main">
          <ReportSections report={report} onSelect={onSelect} onRunAgain={() => run.mutate()} runAgainDisabled={run.isPending || atCap} />
        </div>
        <section className="report-transcript" aria-label="Transcript">
          <TranscriptPanel sessionId={id} highlights={highlights} />
        </section>
      </div>
    </div>
  );
}
