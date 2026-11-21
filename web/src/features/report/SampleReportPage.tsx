/**
 * `/sample-report` (PRD R1, D16): the bundled N=1 fixture report and transcript, rendered through the
 * same report components as the real page. Public, read-only, and makes no network request.
 */
import { useMemo, useState } from "react";
import { sampleReport, sampleTranscript } from "../../mocks/fixtures";
import { Transcript } from "../transcript/Transcript";
import { useSelectedInstance } from "../transcript/useSelectedInstance";
import { reportHighlights } from "./lines";
import { ReportSections } from "./ReportSections";

export function SampleReportPage() {
  const [selectedId, select] = useSelectedInstance();
  const [tab, setTab] = useState<"report" | "transcript">("report");
  const highlights = useMemo(() => reportHighlights(sampleReport), []);
  const goal = sampleReport.header.change_goal;
  return (
    <div className="report-page">
      <header className="report-header">
        <h1>Sample report</h1>
        <p className="notice">Sample</p>
        <p className="form-note">An example made from a made-up conversation, to show what a report looks like.</p>
        {goal ? <p className="report-goal">{goal}</p> : null}
      </header>
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
          <ReportSections
            report={sampleReport}
            onSelect={(id) => {
              select(id);
              setTab("transcript");
            }}
          />
        </div>
        <section className="report-transcript" aria-label="Transcript">
          <Transcript turns={sampleTranscript} highlights={highlights} selectedId={selectedId} />
        </section>
      </div>
    </div>
  );
}
