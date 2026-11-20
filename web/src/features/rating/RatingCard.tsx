/**
 * In-app rating card (PRD R4, D13, D15): filled while transcription runs, autosaved as a draft,
 * submitted with `final:true`. Only "Submit rating" / "No rating" satisfy the run gate.
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { unwrap } from "../../api/client";
import { ApiError, describeError } from "../../api/errors";
import { useApiClient } from "../../auth/useApiClient";
import { COUNTS, GLOBALS, LIMITS } from "../../protocol/miti-items";
import { createAutosaver, type Autosaver, type SaveStatus } from "./autosave";
import {
  buildCard,
  cardToForm,
  emptyForm,
  issuesFromApi,
  localIssues,
  softCount,
  type CountForm,
  type GlobalForm,
  type Issues,
  type RatingForm,
} from "./card";

const STATUS_TEXT: Record<SaveStatus, string> = {
  idle: "",
  saving: "Saving…",
  saved: "Draft saved",
  error: "Couldn't save — retrying",
  invalid: "Draft not saved — shorten the highlighted fields",
};

type Load = "loading" | "ready" | "error";
type Submitted = null | "submitted" | "no_rating";

const idOf = (path: string) => `rating-${path.replace(/\./g, "-")}`;
const fmt = (n: number) => n.toLocaleString("en-US");

function Field({ path, label, error, hint, children }: { path: string; label: string; error?: string; hint?: string; children: (props: { id: string; "aria-describedby"?: string; "aria-invalid"?: boolean }) => ReactNode }) {
  const id = idOf(path);
  const describedBy = [error ? `${id}-err` : null, hint ? `${id}-hint` : null].filter(Boolean).join(" ") || undefined;
  return (
    <div className="rating-field">
      <label htmlFor={id}>{label}</label>
      {hint ? <span className="form-note" id={`${id}-hint`}>{hint}</span> : null}
      {children({ id, "aria-describedby": describedBy, "aria-invalid": error ? true : undefined })}
      {error ? <span className="rating-error" id={`${id}-err`}>{error}</span> : null}
    </div>
  );
}

function Counter({ value, limit }: { value: string; limit: number }) {
  const c = softCount(value, limit);
  return (
    <span className={c.over ? "counter counter-over" : "counter"}>
      {fmt(c.length)} / {fmt(c.limit)}
      {c.over ? ` — over the limit by ${fmt(c.length - c.limit)}; shorten it before it can be saved` : ""}
    </span>
  );
}

function Text({ path, label, value, limit, error, rows = 3, hint, onChange }: { path: string; label: string; value: string; limit: number; error?: string; rows?: number; hint?: string; onChange: (v: string) => void }) {
  return (
    <Field path={path} label={label} error={error} hint={hint}>
      {(p) => (
        <>
          <textarea {...p} rows={rows} value={value} onChange={(e) => onChange(e.target.value)} />
          <Counter value={value} limit={limit} />
        </>
      )}
    </Field>
  );
}

export function RatingCard({ sessionId, debounceMs = 2000 }: { sessionId: string; debounceMs?: number }) {
  const client = useApiClient();
  const [load, setLoad] = useState<Load>("loading");
  const [attempt, setAttempt] = useState(0);
  const [form, setForm] = useState<RatingForm>(emptyForm);
  const formRef = useRef(form);
  const [status, setStatus] = useState<SaveStatus>("idle");
  const [issues, setIssues] = useState<Issues>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState<Submitted>(null);
  const [busy, setBusy] = useState(false);
  const saver = useRef<Autosaver | null>(null);

  // Restore: draft if present, else the last final revision.
  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const data = unwrap(await client.GET("/sessions/{id}/rating", { params: { path: { id: sessionId } } }));
        if (!live) return;
        const next = cardToForm(data.draft?.card ?? data.final?.card);
        formRef.current = next;
        setForm(next);
        setSubmitted(data.draft ? null : data.final ? (data.final.no_rating ? "no_rating" : "submitted") : null);
        setLoad("ready");
      } catch {
        if (live) setLoad("error");
      }
    })();
    return () => {
      live = false;
    };
  }, [client, sessionId, attempt]);

  // Autosave controller: debounce, blur and page-hide flushes all go through it.
  useEffect(() => {
    const s = createAutosaver({
      delayMs: debounceMs,
      onStatus: setStatus,
      isPermanent: (e) => e instanceof ApiError && e.code === "rating_invalid",
      save: async (keepalive) => {
        try {
          unwrap(
            await client.PUT("/sessions/{id}/rating", {
              params: { path: { id: sessionId } },
              body: { final: false, card: buildCard(formRef.current) },
              keepalive,
            }),
          );
          setIssues({});
        } catch (e) {
          if (e instanceof ApiError && e.code === "rating_invalid") setIssues(issuesFromApi(e));
          throw e;
        }
      },
    });
    saver.current = s;
    const hide = () => void s.flush({ keepalive: true });
    const onVisibility = () => {
      if (document.visibilityState === "hidden") hide();
    };
    window.addEventListener("pagehide", hide);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("pagehide", hide);
      document.removeEventListener("visibilitychange", onVisibility);
      void s.flush({ keepalive: true }); // leaving the page loses nothing
      s.dispose();
      saver.current = null;
    };
  }, [client, sessionId, debounceMs]);

  const edit = useCallback((fn: (f: RatingForm) => RatingForm) => {
    const next = fn(formRef.current);
    formRef.current = next;
    setForm(next);
    saver.current?.change();
  }, []);
  const setGlobal = (id: string, patch: Partial<GlobalForm>) =>
    edit((f) => ({ ...f, globals: { ...f.globals, [id]: { ...f.globals[id], ...patch } } }));
  const setCount = (id: string, patch: Partial<CountForm>) =>
    edit((f) => ({ ...f, counts: { ...f.counts, [id]: { ...f.counts[id], ...patch } } }));

  async function submit(noRating: boolean) {
    const found = localIssues(formRef.current, { noRating });
    setIssues(found);
    if (Object.keys(found).length) {
      setFormError("Some of your rating needs a change. Check the highlighted fields.");
      return;
    }
    setFormError(null);
    setBusy(true);
    saver.current?.cancel();
    try {
      await saver.current?.flush(); // nothing pending after cancel; waits for an in-flight draft
      unwrap(
        await client.PUT("/sessions/{id}/rating", {
          params: { path: { id: sessionId } },
          body: { final: true, ...(noRating ? { no_rating: true } : {}), card: buildCard(formRef.current, { noRating }) },
        }),
      );
      setSubmitted(noRating ? "no_rating" : "submitted");
    } catch (e) {
      if (e instanceof ApiError && e.code === "rating_invalid") {
        setIssues(issuesFromApi(e));
        setFormError(describeError(e).message);
      } else {
        setFormError(describeError(e).message);
      }
    } finally {
      setBusy(false);
    }
  }

  if (load === "loading") return <p className="form-note">Loading your rating…</p>;
  if (load === "error") {
    return (
      <p className="notice">
        We couldn't load your rating.{" "}
        <button type="button" className="link-button" onClick={() => {
            setLoad("loading");
            setAttempt((n) => n + 1);
          }}>
          Try again
        </button>
      </p>
    );
  }

  const err = (p: string) => issues[p];
  return (
    <form
      className="rating-card"
      aria-labelledby="rating-heading"
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        void submit(false);
      }}
      onBlur={() => void saver.current?.flush()}
    >
      <h2 id="rating-heading">Your rating</h2>
      <p className="form-note">
        Fill this in while we transcribe. It saves as you type. Onolys compares it with its own reading of the session.
      </p>
      <p className="form-note" aria-live="polite">
        {STATUS_TEXT[status]}
      </p>

      <Field path="change_goal" label="Change goal" error={err("change_goal")}>
        {(p) => <input {...p} type="text" value={form.changeGoal} onChange={(e) => edit((f) => ({ ...f, changeGoal: e.target.value }))} />}
      </Field>
      <fieldset className="rating-span">
        <legend>Coded from–to (optional)</legend>
        <span className="form-note">Only if you rated part of the recording.</span>
        <Field path="coded_span.from_s" label="Coded from (mm:ss)" error={err("coded_span")}>
          {(p) => <input {...p} type="text" inputMode="numeric" placeholder="mm:ss" value={form.spanFrom} onChange={(e) => edit((f) => ({ ...f, spanFrom: e.target.value }))} />}
        </Field>
        <Field path="coded_span.to_s" label="Coded to (mm:ss)">
          {(p) => <input {...p} type="text" inputMode="numeric" placeholder="mm:ss" value={form.spanTo} onChange={(e) => edit((f) => ({ ...f, spanTo: e.target.value }))} />}
        </Field>
      </fieldset>

      <h3>Global ratings</h3>
      {GLOBALS.map((g) => {
        const f = form.globals[g.id];
        const base = `globals.${g.id}`;
        return (
          <fieldset key={g.id} className="rating-item">
            <legend>{g.label}</legend>
            <Field path={`${base}.score`} label={`${g.label} score`} error={err(`${base}.score`)}>
              {(p) => (
                <select {...p} value={f.score} onChange={(e) => setGlobal(g.id, { score: e.target.value })}>
                  <option value="">Not rated</option>
                  {g.anchors.map((a, i) => (
                    <option key={a} value={String(i + 1)}>
                      {i + 1} — {a}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <Text path={`${base}.reason`} label={`${g.label} reason`} value={f.reason} limit={LIMITS.item} error={err(`${base}.reason`)} onChange={(v) => setGlobal(g.id, { reason: v })} />
            <Field path={`${base}.example.at_s`} label={`${g.label} example time (mm:ss, optional)`} error={err(`${base}.example.at_s`)}>
              {(p) => <input {...p} type="text" inputMode="numeric" placeholder="mm:ss" value={f.exTime} onChange={(e) => setGlobal(g.id, { exTime: e.target.value })} />}
            </Field>
            <Text path={`${base}.example.text`} label={`${g.label} example`} value={f.exText} limit={LIMITS.item} rows={2} error={err(`${base}.example.text`)} onChange={(v) => setGlobal(g.id, { exText: v })} />
          </fieldset>
        );
      })}

      <h3>Behaviour counts</h3>
      {COUNTS.map((c) => {
        const f = form.counts[c.id];
        const base = `counts.${c.id}`;
        return (
          <fieldset key={c.id} className="rating-item">
            <legend>{c.label}</legend>
            <Field path={`${base}.count`} label={`${c.label} count`} error={err(`${base}.count`)}>
              {(p) => <input {...p} type="number" min={0} step={1} value={f.count} onChange={(e) => setCount(c.id, { count: e.target.value })} />}
            </Field>
            <Text path={`${base}.note`} label={`${c.label} note`} value={f.note} limit={LIMITS.item} rows={2} error={err(`${base}.note`)} onChange={(v) => setCount(c.id, { note: v })} />
          </fieldset>
        );
      })}

      <Text
        path="notes"
        label="Additional notes / evaluation reasoning"
        value={form.notes}
        limit={LIMITS.notes}
        rows={6}
        error={err("notes")}
        hint="Not parsed into the card above. Onolys checks what you write here against the transcript."
        onChange={(v) => edit((f) => ({ ...f, notes: v }))}
      />

      {formError ? (
        <p className="form-error" role="alert">
          {formError}
        </p>
      ) : null}
      {submitted ? (
        <p className="form-note">
          {submitted === "submitted" ? "Rating submitted." : "Saved without a rating — Onolys will score the session on its own."} Changes you make now apply to your next run.
        </p>
      ) : null}
      <div className="rating-actions">
        <button type="submit" className="btn btn-primary" disabled={busy}>
          Submit rating
        </button>
        <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => void submit(true)}>
          No rating — just rate my session
        </button>
      </div>
    </form>
  );
}
