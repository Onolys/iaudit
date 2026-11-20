import { useEffect, useState, type RefObject } from "react";
import { describeError, type ErrorDescription } from "../../api/errors";
import { unwrap } from "../../api/client";
import type { components } from "../../api/schema";
import { getStatusListener, type SessionStatusDoc } from "../../api/statusListener";
import { useApiClient } from "../../auth/useApiClient";

export type StatusView =
  | { phase: "loading" }
  /** Doc from the live listener. */
  | { phase: "live"; doc: SessionStatusDoc; runStartedAt: number | null }
  /** The listener failed; this is the one `GET /sessions/{id}` snapshot. It no longer updates. */
  | { phase: "fallback"; doc: SessionStatusDoc }
  /** The fallback GET failed too (404 = unknown or someone else's session). */
  | { phase: "error"; error: ErrorDescription };

type Detail = components["schemas"]["SessionDetail"];

function detailToDoc(d: Detail): SessionStatusDoc {
  return {
    uid: "",
    state: d.status,
    step: d.step ?? null,
    progress: d.progress,
    error_code: d.error?.code ?? null,
    latest_report_version: d.latest_report_version ?? null,
    updated_at: new Date().toISOString(),
    ...d.flags,
  };
}

/** A session stuck in `transcribing` this long gets a `GET /sessions/{id}`, which makes the API settle it. */
export const STALE_NUDGE_AFTER_MS = 6 * 60_000;
/** While it stays `transcribing`, nudge at most this often. */
export const STALE_NUDGE_EVERY_MS = 60_000;

/**
 * Subscribe to `session_status/{id}` for the life of the page (PRD R4, D7). No polling:
 * on listener error / permission-denied / missing doc it makes ONE `GET /sessions/{id}`.
 * Mount with `key={id}` so each session starts from `loading`.
 */
export function useSessionStatus(id: string, quiet: RefObject<boolean>): StatusView {
  const client = useApiClient();
  const [view, setView] = useState<StatusView>({ phase: "loading" });

  useEffect(() => {
    let done = false;
    let fellBack = false;
    const sub: { off?: () => void } = {};
    // Stale nudge: the listener alone never triggers the API's lazy stale check.
    let nudgeTimer: ReturnType<typeof setTimeout> | undefined;
    let lastNudgeAt = 0;
    let firstSeenAt = 0;
    const stopNudge = () => {
      clearTimeout(nudgeTimer);
      nudgeTimer = undefined;
      firstSeenAt = 0;
    };
    const armNudge = (doc: SessionStatusDoc) => {
      clearTimeout(nudgeTimer);
      const now = Date.now();
      firstSeenAt ||= now;
      const since = Date.parse(doc.updated_at);
      const dueAt = Math.max(
        (Number.isNaN(since) ? firstSeenAt : since) + STALE_NUDGE_AFTER_MS,
        lastNudgeAt ? lastNudgeAt + STALE_NUDGE_EVERY_MS : 0,
      );
      nudgeTimer = setTimeout(() => {
        if (done || fellBack) return;
        lastNudgeAt = Date.now();
        // The listener shows the resulting `failed` by itself; the response and errors are ignored.
        void client
          .GET("/sessions/{id}", { params: { path: { id } } })
          .catch((e: unknown) => console.warn("stale nudge failed", describeError(e)));
        armNudge(doc);
      }, Math.max(0, dueAt - now));
    };

    const fallback = () => {
      if (done || fellBack || quiet.current) return;
      fellBack = true;
      stopNudge();
      sub.off?.();
      void client
        .GET("/sessions/{id}", { params: { path: { id } } })
        .then((r) => {
          if (done) return;
          setView({ phase: "fallback", doc: detailToDoc(unwrap(r)) });
        })
        .catch((e: unknown) => {
          if (!done) setView({ phase: "error", error: describeError(e) });
        });
    };

    sub.off = getStatusListener().subscribe(
      id,
      (doc) => {
        if (done || fellBack || quiet.current) return;
        if (doc === null) return fallback();
        if (doc.state === "transcribing") armNudge(doc);
        else stopNudge();
        setView((prev) => ({
          phase: "live",
          doc,
          runStartedAt:
            doc.state !== "running"
              ? null
              : prev.phase === "live" && prev.doc.state === "running" && prev.runStartedAt !== null
                ? prev.runStartedAt
                : Date.parse(doc.updated_at) || Date.now(),
        }));
      },
      fallback,
    );
    if (fellBack) sub.off();

    return () => {
      done = true;
      stopNudge();
      sub.off?.();
    };
  }, [id, client, quiet]);

  return view;
}
