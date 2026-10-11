import { useReducer } from "react";
import { WarningsBanner } from "../transport";
import type { LoadResult } from "../transport";
import { Header } from "./Header";
import type { HeaderProps } from "./Header";
import { initialState, reviewReducer } from "./reviewState";
import { VerdictCounts } from "./VerdictCounts";

export function ReviewShell({
  result,
  headerProps,
}: {
  result: LoadResult;
  headerProps: Omit<HeaderProps, "children">;
}) {
  const { analysis } = result;
  const [state, dispatch] = useReducer(reviewReducer, analysis, initialState);
  return (
    <>
      <Header {...headerProps}>
        <VerdictCounts
          counts={analysis.counts.overall}
          active={state.nav?.scope === "all" ? state.nav.verdict : null}
          onPick={(verdict) => dispatch({ type: "navigate", analysis, verdict, scope: "all" })}
        />
      </Header>
      <WarningsBanner response={result.response} />
      <main className="app-main" />
    </>
  );
}
