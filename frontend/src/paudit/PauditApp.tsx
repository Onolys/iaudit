import { useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent } from "react";
import { getConfig } from "../config";
import type { ProductViewProps } from "../productViews";
import "./paudit.css";
import { PACK_REF, getFixture, listFixtures, parseTranscript, runPaudit, speakersOf } from "./pauditApi";
import type { PauditDeps } from "./pauditApi";
import ResultView from "./ResultView";
import type { FixtureSummary, PauditParams, PauditResult } from "./types";

// All state lives in React memory only: no URL, storage or console output ever holds transcript text.
export default function PauditApp({ deps }: ProductViewProps) {
  const api: PauditDeps = useMemo(
    () => ({
      fetch: deps?.fetch ?? ((input, init) => fetch(input, init)),
      config: deps?.config ?? getConfig(),
      mockDelayMs: deps?.mockDelayMs,
    }),
    [deps],
  );
  const [pack, setPack] = useState(PACK_REF);
  const [text, setText] = useState("");
  const [speaker, setSpeaker] = useState("");
  const [goal, setGoal] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [nRuns, setNRuns] = useState("1");
  const [language, setLanguage] = useState<string | undefined>();
  const [fixtures, setFixtures] = useState<FixtureSummary[]>([]);
  const [fixtureName, setFixtureName] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const [details, setDetails] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<PauditResult | null>(null);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    const c = new AbortController();
    void listFixtures(api, c.signal).then(r => {
      if (!r.ok) return;
      setFixtures(r.value);
      setFixtureName(n => n || r.value[0]?.name || "");
    });
    return () => { c.abort(); abort.current?.abort(); };
  }, [api]);

  const parsed = useMemo(() => (text.trim() ? parseTranscript(text) : null), [text]);
  const speakers = parsed?.ok ? speakersOf(parsed.value) : [];

  const fail = (messages: string[], extra: string[] = []) => { setErrors(messages); setDetails(extra); };

  function applyParams(p: PauditParams) {
    setSpeaker(p.speaker_map?.subject ?? "");
    setGoal(p.change_goal ?? "");
    setFrom(p.coded_span ? String(p.coded_span.from_s) : "");
    setTo(p.coded_span ? String(p.coded_span.to_s) : "");
    setNRuns(String(p.n_runs ?? 1));
    setLanguage(p.language);
  }

  async function loadFixture() {
    const c = new AbortController();
    const r = await getFixture(api, fixtureName || "good_practice", c.signal);
    if (!r.ok) return fail([r.message]);
    setText(JSON.stringify(r.value.transcript, null, 2));
    applyParams(r.value.params);
    setPack(r.value.pack);
    setResult(null);
    fail([]);
  }

  async function onFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      setText(await file.text());
      setResult(null);
      fail([]);
    } catch {
      fail(["The file could not be read."]);
    }
    e.target.value = "";
  }

  function validate(): { params: PauditParams } | null {
    const problems: string[] = [];
    if (!text.trim()) problems.push("Transcript is required: paste JSON, upload a file or load a fixture.");
    else if (parsed && !parsed.ok) problems.push(parsed.message);
    if (!pack.trim()) problems.push("Pack is required.");
    if (!speaker) problems.push("Clinician speaker is required.");
    else if (parsed?.ok && !speakers.includes(speaker)) problems.push("Clinician speaker must be one of the transcript's speakers.");
    if (!goal.trim()) problems.push("Change goal is required.");
    let coded_span: PauditParams["coded_span"];
    if (from.trim() !== "" || to.trim() !== "") {
      const f = Number(from), t = Number(to);
      if (from.trim() === "" || to.trim() === "" || !Number.isFinite(f) || !Number.isFinite(t) || f > t) {
        problems.push("Coded span needs both numbers, with from at most to (or leave both empty).");
      } else coded_span = { from_s: f, to_s: t };
    }
    const n = Number(nRuns);
    if (!Number.isInteger(n) || n < 1 || n > 5) problems.push("n_runs must be a whole number from 1 to 5.");
    if (problems.length) { fail(problems); return null; }
    const params: PauditParams = { speaker_map: { subject: speaker }, change_goal: goal.trim(), n_runs: n };
    if (coded_span) params.coded_span = coded_span;
    if (language) params.language = language;
    return { params };
  }

  async function onRun() {
    const v = validate();
    if (!v || !parsed?.ok) return;
    fail([]);
    setResult(null);
    setBusy(true);
    const c = new AbortController();
    abort.current = c;
    const r = await runPaudit(api, { transcript: parsed.value, pack: pack.trim(), params: v.params }, c.signal);
    if (c.signal.aborted) return;
    setBusy(false);
    if (r.ok) setResult(r.value);
    else fail([r.message], (r.details ?? []).map(d => `${d.code}: ${d.message}`));
  }

  return (
    <div className="app" data-testid="paudit-view">
      <div className="paudit">
        <p className="paudit-note">Do not paste real PHI until a BAA is in place. Use synthetic or de-identified transcripts only.</p>
        <form className="paudit-form" noValidate onSubmit={e => { e.preventDefault(); void onRun(); }}>
          <div className="paudit-row">
            {fixtures.length > 1 ? (
              <label>Fixture
                <select value={fixtureName} onChange={e => setFixtureName(e.target.value)}>
                  {fixtures.map(f => <option key={f.name} value={f.name}>{f.name}</option>)}
                </select>
              </label>
            ) : null}
            <button type="button" onClick={() => void loadFixture()}>Load fixture</button>
            <label>Upload transcript JSON
              <input type="file" accept="application/json,.json" onChange={e => void onFile(e)} />
            </label>
          </div>
          <label>Transcript JSON
            <textarea value={text} spellCheck={false} onChange={e => setText(e.target.value)} />
          </label>
          <div className="paudit-row">
            <label>Pack<input value={pack} onChange={e => setPack(e.target.value)} /></label>
            <label>Clinician speaker
              <select value={speaker} onChange={e => setSpeaker(e.target.value)}>
                <option value="">Select a speaker</option>
                {speakers.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </label>
            <label>Runs (n_runs)
              <input type="number" min={1} max={5} value={nRuns} onChange={e => setNRuns(e.target.value)} />
            </label>
          </div>
          <label>Change goal<input value={goal} onChange={e => setGoal(e.target.value)} /></label>
          <div className="paudit-row">
            <label>Span from (s)<input type="number" min={0} value={from} onChange={e => setFrom(e.target.value)} /></label>
            <label>Span to (s)<input type="number" min={0} value={to} onChange={e => setTo(e.target.value)} /></label>
          </div>
          <div>
            <button type="submit" disabled={busy}>Run</button>{busy ? " Running..." : ""}
          </div>
        </form>
        {errors.length ? (
          <div role="alert">
            <ul className="paudit-errors">{errors.map(m => <li key={m}>{m}</li>)}</ul>
            {details.length ? <ul>{details.map(m => <li key={m}>{m}</li>)}</ul> : null}
          </div>
        ) : null}
        {result ? <ResultView result={result} /> : null}
      </div>
    </div>
  );
}
