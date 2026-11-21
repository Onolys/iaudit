/** `/` (PRD R5, D16): the caller's sessions, newest first, with status chips, usage and an empty state. */
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { unwrap } from "../../api/client";
import { describeError } from "../../api/errors";
import { useApiClient } from "../../auth/useApiClient";
import { formatResetTime } from "../../lib/format";
import { ErrorCard } from "../session/ErrorCard";
import { STATUS_CHIP } from "./chips";

const PAGE = 20;
const date = (iso: string) => new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });

export function Dashboard() {
  const client = useApiClient();
  const sessions = useInfiniteQuery({
    queryKey: ["sessions"],
    staleTime: 0,
    gcTime: 0,
    retry: false,
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) =>
      unwrap(await client.GET("/sessions", { params: { query: { limit: PAGE, cursor: pageParam } } })),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const usage = useQuery({
    queryKey: ["usage"],
    queryFn: async () => unwrap(await client.GET("/usage")),
  });
  const atCap = usage.data ? usage.data.runs_today >= usage.data.daily_cap : false;

  const items = sessions.data?.pages.flatMap((p) => p.items) ?? [];

  let body;
  if (sessions.isPending) {
    body = <p className="form-note">Loading your sessions…</p>;
  } else if (sessions.isError) {
    const e = describeError(sessions.error);
    body = (
      <ErrorCard code={e.code} reference={e.requestId}>
        <button type="button" className="link-button" onClick={() => void sessions.refetch()}>
          Try again
        </button>
      </ErrorCard>
    );
  } else if (items.length === 0) {
    body = (
      <div className="empty-state">
        <p>Onolys rates a recorded session against the MITI and shows you where it agrees with your own rating, line by line.</p>
        <p>
          <Link className="btn btn-primary" to="/sessions/new">
            New session
          </Link>{" "}
          <Link to="/sample-report">See a sample report</Link>
        </p>
      </div>
    );
  } else {
    body = (
      <>
        <ul className="session-list">
          {items.map((s) => {
            const chip = STATUS_CHIP[s.status];
            return (
              <li key={s.id} className="session-row">
                <Link to={`/sessions/${s.id}`}>{s.title ?? date(s.created_at)}</Link>{" "}
                <span className="chip" data-tone={chip.tone}>
                  {chip.text}
                </span>{" "}
                <span className="form-note">{date(s.created_at)}</span>
                {s.latest_report_version ? (
                  <>
                    {" "}
                    <Link to={`/sessions/${s.id}/reports/${s.latest_report_version}`}>Report v{s.latest_report_version}</Link>
                  </>
                ) : null}
              </li>
            );
          })}
        </ul>
        {sessions.hasNextPage ? (
          <p>
            <button type="button" className="btn btn-secondary" disabled={sessions.isFetchingNextPage} onClick={() => void sessions.fetchNextPage()}>
              Load more
            </button>
          </p>
        ) : null}
      </>
    );
  }

  return (
    <>
      <h1>Sessions</h1>
      {usage.data ? (
        <p className="form-note">
          {usage.data.runs_today} of {usage.data.daily_cap} runs today
        </p>
      ) : null}
      {atCap ? (
        <p className="notice">You've reached today's limit. You can run again after {formatResetTime(usage.data?.resets_at)}.</p>
      ) : null}
      {items.length > 0 ? (
        <p>
          <Link className="btn btn-primary" to="/sessions/new">
            New session
          </Link>
        </p>
      ) : null}
      {body}
    </>
  );
}
