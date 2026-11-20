/**
 * Report sections (PRD R4, D17), driven by the report JSON: `layout[]` gives order and titles,
 * sections the UI does not know are skipped, labels/references come from the report. Pure: no
 * fetching, so `/sample-report` can reuse it.
 */
import type { ReactNode } from "react";
import type { ClaimVerdict, Line, Report } from "../../api/report";
import { diffChip } from "./chips";
import { lineId } from "./lines";

export interface SectionsProps {
  report: Report;
  onSelect: (id: string) => void;
  /** Runs again (reasons_audit failed note). Omit to hide the button (sample report). */
  onRunAgain?: () => void;
  runAgainDisabled?: boolean;
}

const VERDICT: Record<Exclude<ClaimVerdict, "out_of_scope">, string> = {
  supported: "Supported",
  partially_supported: "Partly supported",
  contradicted: "Not supported",
  insufficient_evidence: "Not enough evidence",
};
const ROLE: Record<string, string> = {
  supporting: "Supports",
  contradicting: "Contradicts",
  qualifying: "Adds a qualification",
};
const WARNING_TEXT: Record<string, string> = {
  fewer_tips: "We could only find a few tips this time.",
  tips_failed: "We couldn't write tips this time.",
  reason_withheld_tone: "One of your reasons was not shown, to keep the report fair in tone.",
  short_session: "This was a short session, so the readings are less certain.",
};
const SKIPPED_WARNINGS = new Set(["reasons_audit_failed"]); // already explained inside its section

const num = (n: number | null | undefined) => (n === null || n === undefined ? "–" : String(n));

export function LineButton({ id, quote, onSelect }: { id: string; quote: string; onSelect: (id: string) => void }) {
  return (
    <button type="button" className="line-chip" onClick={() => onSelect(id)}>
      “{quote}”
    </button>
  );
}

function Lines({ lines, id, onSelect }: { lines: Line[]; id: (i: number) => string; onSelect: (id: string) => void }) {
  if (lines.length === 0) return null;
  return (
    <ul className="line-list">
      {lines.map((l, i) => (
        <li key={i}>
          <LineButton id={id(i)} quote={l.quote} onSelect={onSelect} />
        </li>
      ))}
    </ul>
  );
}

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section className="report-section" aria-labelledby={`sec-${id}`}>
      <h2 id={`sec-${id}`}>{title}</h2>
      {children}
    </section>
  );
}

const runsNote = (r: Report) => (r.header.n_runs > 1 ? `Scores are based on ${r.header.n_runs} runs.` : null);

function Scorecard({ r, title }: { r: Report; title: string }) {
  const rated = r.header.has_clinician_rating;
  const note = runsNote(r);
  return (
    <Section id="scorecard" title={title}>
      {!rated ? <p className="form-note">No rating of yours was used for this report, so only Onolys's scores are shown.</p> : null}
      {note ? <p className="form-note">{note}</p> : null}
      <table className="report-table" aria-label="Scores per item">
        <thead>
          <tr>
            <th scope="col">Item</th>
            <th scope="col">You</th>
            <th scope="col">Onolys</th>
            <th scope="col">Difference</th>
          </tr>
        </thead>
        <tbody>
          {(r.scorecard ?? []).map((s) => {
            const chip = rated ? diffChip(s.diff) : null;
            return (
              <tr key={s.item_id}>
                <th scope="row">{s.label}</th>
                <td data-label="You">{rated ? num(s.clinician?.value) : "–"}</td>
                <td data-label="Onolys">{num(s.onolys?.value)}</td>
                <td data-label="Difference">
                  {chip ? (
                    <span className="chip" data-tone={chip.tone}>
                      {chip.text}
                    </span>
                  ) : (
                    "–"
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Section>
  );
}

function Disagreements({ r, title, labels, onSelect }: { r: Report; title: string; labels: Map<string, string>; onSelect: SectionsProps["onSelect"] }) {
  const blocks = [
    ...(r.globals ?? []).filter((g) => g.diff?.status === "differs").map((g) => ({ id: g.item_id, e: g.explanation })),
    ...(r.behaviours ?? []).filter((b) => b.diff?.status === "flagged").map((b) => ({ id: b.item_id, e: b.explanation })),
  ];
  if (blocks.length === 0) return null;
  return (
    <Section id="disagreements" title={title}>
      {blocks.map(({ id, e }) => (
        <article key={id} className="disagreement">
          <h3>{e?.headline || labels.get(id) || id}</h3>
          {(e?.body ?? []).map((p, i) => (
            <p key={i}>{p}</p>
          ))}
          {e?.onolys_lines?.length ? (
            <>
              <p className="line-heading">Lines Onolys relied on</p>
              <Lines lines={e.onolys_lines} id={(i) => lineId.explain(id, "o", i)} onSelect={onSelect} />
            </>
          ) : null}
          {e?.clinician_support_lines?.length ? (
            <>
              <p className="line-heading">Lines supporting your rating</p>
              <Lines lines={e.clinician_support_lines} id={(i) => lineId.explain(id, "c", i)} onSelect={onSelect} />
            </>
          ) : null}
        </article>
      ))}
    </Section>
  );
}

function Globals({ r, title, labels, onSelect }: { r: Report; title: string; labels: Map<string, string>; onSelect: SectionsProps["onSelect"] }) {
  const globals = r.globals ?? [];
  if (globals.length === 0) return null;
  const rated = r.header.has_clinician_rating;
  return (
    <Section id="globals" title={title}>
      {globals.map((g) => (
        <div key={g.item_id} className="global-item">
          <h3>{labels.get(g.item_id) ?? g.item_id}</h3>
          <p>
            <strong>Onolys: {num(g.onolys?.score)}</strong>
            {g.onolys?.reason ? ` — ${g.onolys.reason}` : null}
          </p>
          <Lines lines={g.onolys?.evidence ?? []} id={(i) => lineId.evidence(g.item_id, i)} onSelect={onSelect} />
          {rated && g.clinician?.value !== null && g.clinician?.value !== undefined ? (
            <p>
              <strong>You: {g.clinician.value}</strong>
              {g.clinician.reason ? ` — ${g.clinician.reason}` : null}
            </p>
          ) : null}
        </div>
      ))}
    </Section>
  );
}

function Behaviours({ r, title, labels, onSelect }: { r: Report; title: string; labels: Map<string, string>; onSelect: SectionsProps["onSelect"] }) {
  const rows = r.behaviours ?? [];
  if (rows.length === 0) return null;
  const rated = r.header.has_clinician_rating;
  const note = runsNote(r);
  return (
    <Section id="behaviours" title={title}>
      <p className="form-note">
        These are Onolys's instances; a tally-only self-rating can't be matched line by line.
        {note ? ` ${note}` : ""}
      </p>
      <table className="report-table" aria-label="Behaviour counts">
        <thead>
          <tr>
            <th scope="col">Behaviour</th>
            <th scope="col">You</th>
            <th scope="col">Onolys</th>
            <th scope="col">Instances</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((b) => {
            const more = Math.max(0, (b.instances_total ?? 0) - (b.instances?.length ?? 0));
            return (
              <tr key={b.item_id}>
                <th scope="row">{labels.get(b.item_id) ?? b.item_id}</th>
                <td data-label="You">{rated ? num(b.clinician_count) : "–"}</td>
                <td data-label="Onolys">{num(b.onolys_count?.values?.[0] ?? b.onolys_count?.mean)}</td>
                <td data-label="Instances">
                  {(b.instances ?? []).map((inst) => (
                    <button key={inst.id} type="button" className="line-chip" title={inst.rationale} onClick={() => onSelect(inst.id)}>
                      “{inst.quote}”
                    </button>
                  ))}
                  {more > 0 ? <span className="chip-more">+{more} more</span> : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Section>
  );
}

function Summaries({ r, title }: { r: Report; title: string }) {
  const items = r.summaries ?? [];
  if (items.length === 0) return null;
  return (
    <Section id="summaries" title={title}>
      <p className="form-note">These are reference levels, not pass marks.</p>
      <ul className="summary-list">
        {items.map((s) => {
          const top = Math.max(s.reference.good, s.onolys.value ?? 0, s.clinician?.value ?? 0) * 1.25 || 1;
          const pos = (v: number) => `${Math.min(100, (v / top) * 100)}%`;
          return (
            <li key={s.id}>
              <h3>{s.label}</h3>
              <p>
                Onolys {s.onolys.label}
                {s.clinician ? ` · You ${s.clinician.label}` : ""} · Fair {s.reference.fair} · Good {s.reference.good}
              </p>
              <div className="ref-track" aria-hidden="true">
                <span className="ref-tick" style={{ left: pos(s.reference.fair) }} data-kind="fair" />
                <span className="ref-tick" style={{ left: pos(s.reference.good) }} data-kind="good" />
                {s.clinician?.value != null ? <span className="ref-dot" style={{ left: pos(s.clinician.value) }} data-kind="you" /> : null}
                {s.onolys.value != null ? <span className="ref-dot" style={{ left: pos(s.onolys.value) }} data-kind="onolys" /> : null}
              </div>
              {s.note ? <p className="form-note">{s.note}</p> : null}
            </li>
          );
        })}
      </ul>
    </Section>
  );
}

function Reasons({ r, title, labels, onSelect, onRunAgain, runAgainDisabled }: { r: Report; title: string; labels: Map<string, string> } & Pick<SectionsProps, "onSelect" | "onRunAgain" | "runAgainDisabled">) {
  const audit = r.reasons_audit;
  if (!audit || audit.status === "skipped") return null;
  if (audit.status === "failed") {
    return (
      <Section id="reasons_audit" title={title}>
        <p>We couldn't check your reasons this time. The rest of your report is complete.</p>
        {onRunAgain ? (
          <button type="button" className="btn btn-secondary" disabled={runAgainDisabled} onClick={onRunAgain}>
            Run again
          </button>
        ) : null}
      </Section>
    );
  }
  return (
    <Section id="reasons_audit" title={title}>
      {audit.status === "partial" ? <p className="form-note">Some of your reasons could not be checked this time.</p> : null}
      {(audit.items ?? []).map((item) => {
        const claims = (item.claims ?? []).map((c, ci) => ({ c, ci })).filter(({ c }) => c.verdict !== "out_of_scope");
        if (claims.length === 0) return null;
        return (
          <div key={item.item_id} className="reason-item">
            <h3>{labels.get(item.item_id) ?? item.item_id}</h3>
            <p className="reason-text">Your reason: {item.reason}</p>
            {claims.map(({ c, ci }) => (
              <div key={ci} className="claim">
                <p>
                  <strong>{VERDICT[c.verdict as keyof typeof VERDICT] ?? c.verdict}</strong>: {c.span}
                </p>
                {c.explanation ? <p>{c.explanation}</p> : null}
                <ul className="line-list">
                  {(c.evidence ?? []).map((e, i) => (
                    <li key={i}>
                      <span className="line-role">{ROLE[e.role] ?? e.role}: </span>
                      <LineButton id={lineId.claim(item.item_id, ci, i)} quote={e.quote} onSelect={onSelect} />
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        );
      })}
    </Section>
  );
}

function Tips({ r, title, labels, onSelect }: { r: Report; title: string; labels: Map<string, string>; onSelect: SectionsProps["onSelect"] }) {
  const tips = [...(r.tips ?? [])].sort((a, b) => a.rank - b.rank);
  if (tips.length === 0) return null;
  return (
    <Section id="tips" title={title}>
      <ol className="tip-list">
        {tips.map((t) => (
          <li key={t.rank}>
            <p className="tip-tag">{labels.get(t.item_id) ?? t.item_id}</p>
            <p>{t.observation}</p>
            <p>
              <LineButton id={lineId.tip(t.rank)} quote={t.quote.text} onSelect={onSelect} />
            </p>
            <p>
              <strong>Try:</strong> {t.alternative}
            </p>
            <p className="form-note">{t.why_it_matters}</p>
          </li>
        ))}
      </ol>
    </Section>
  );
}

function Method({ r, title }: { r: Report; title: string }) {
  const m = r.method;
  if (!m) return null;
  return (
    <Section id="method" title={title}>
      <p>{m.statement}</p>
      {m.limits?.length ? (
        <ul>
          {m.limits.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      ) : null}
      {m.citation ? <p className="form-note">{m.citation}</p> : null}
    </Section>
  );
}

export function ReportSections(props: SectionsProps) {
  const { report: r, onSelect } = props;
  const labels = new Map((r.scorecard ?? []).map((s) => [s.item_id, s.label]));
  const notices = (r.warnings ?? []).filter((w) => !SKIPPED_WARNINGS.has(w.code));
  return (
    <>
      {(r.layout ?? []).map((l) => {
        switch (l.section) {
          case "scorecard":
            return <Scorecard key={l.section} r={r} title={l.title} />;
          case "disagreements":
            return <Disagreements key={l.section} r={r} title={l.title} labels={labels} onSelect={onSelect} />;
          case "globals":
            return <Globals key={l.section} r={r} title={l.title} labels={labels} onSelect={onSelect} />;
          case "behaviours":
            return <Behaviours key={l.section} r={r} title={l.title} labels={labels} onSelect={onSelect} />;
          case "summaries":
            return <Summaries key={l.section} r={r} title={l.title} />;
          case "reasons_audit":
            return <Reasons key={l.section} r={r} title={l.title} labels={labels} onSelect={onSelect} onRunAgain={props.onRunAgain} runAgainDisabled={props.runAgainDisabled} />;
          case "tips":
            return <Tips key={l.section} r={r} title={l.title} labels={labels} onSelect={onSelect} />;
          case "method":
            return <Method key={l.section} r={r} title={l.title} />;
          default:
            return null; // unknown section: skipped, so later report additions do not break the UI
        }
      })}
      {notices.map((w, i) => (
        <p key={i} className="quiet-notice" role="note">
          {WARNING_TEXT[w.code] ?? "There is a note about this report."}
          {w.item_id && r.scorecard?.some((s) => s.item_id === w.item_id) ? ` (${labels.get(w.item_id)})` : ""}
        </p>
      ))}
    </>
  );
}
