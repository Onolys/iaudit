import { useEffect, useReducer, useRef } from "react";
import type { Verdict } from "../contract";
import { WarningsBanner } from "../transport";
import type { LoadResult } from "../transport";
import { Header } from "./Header";
import type { HeaderProps } from "./Header";
import { LeftPane } from "./LeftPane";
import { RightPane } from "./RightPane";
import { initialState, reviewReducer } from "./reviewState";
import { VerdictCounts } from "./VerdictCounts";

export function ReviewShell({
  result,
  headerProps,
}: {
  result: LoadResult;
  headerProps: Omit<HeaderProps, "children">;
}) {
  const { request, response, analysis } = result;
  const [state, dispatch] = useReducer(reviewReducer, analysis, initialState);
  const leftRef = useRef<HTMLDivElement>(null);
  // Only navigation and stepping scroll the text; direct clicks leave it where it is.
  const scrollNext = useRef(false);

  useEffect(() => {
    if (!scrollNext.current) return;
    scrollNext.current = false;
    const el = [...(leftRef.current?.querySelectorAll<HTMLElement>("[data-claim-id]") ?? [])].find(
      (e) => e.dataset.claimId === state.selectedClaimId,
    );
    el?.scrollIntoView?.({ block: "nearest" });
  }, [state.selectedClaimId, state.nav]);

  const navigate = (verdict: Verdict, scope: "all" | number) => {
    scrollNext.current = true;
    dispatch({ type: "navigate", analysis, verdict, scope });
  };

  return (
    <>
      <Header {...headerProps}>
        <VerdictCounts
          counts={analysis.counts.overall}
          active={state.nav?.scope === "all" ? state.nav.verdict : null}
          onPick={(verdict) => navigate(verdict, "all")}
        />
      </Header>
      <WarningsBanner response={response} />
      <main className="app-main">
        <div ref={leftRef} className="left-pane-scroll">
          <LeftPane
            request={request}
            response={response}
            analysis={analysis}
            state={state}
            onSelect={(id) => dispatch({ type: "selectClaim", id })}
            onNavigate={navigate}
          />
        </div>
        <RightPane
          request={request}
          analysis={analysis}
          state={state}
          onStep={(delta) => {
            scrollNext.current = true;
            dispatch({ type: "step", delta });
          }}
        />
      </main>
    </>
  );
}
