import { claimIdsFor } from "../contract";
import type { ResponseAnalysis, Verdict } from "../contract";

export type Nav = { verdict: Verdict; scope: "all" | number; claimIds: string[]; position: number };
export type ReviewState = { selectedClaimId: string | null; nav: Nav | null };

export type ReviewAction =
  | { type: "selectClaim"; id: string }
  | { type: "navigate"; analysis: ResponseAnalysis; verdict: Verdict; scope: "all" | number }
  | { type: "step"; delta: 1 | -1 };

export const initialState = (analysis: ResponseAnalysis): ReviewState => ({
  selectedClaimId: analysis.orderedClaims[0]?.id ?? null,
  nav: null,
});

export function reviewReducer(state: ReviewState, action: ReviewAction): ReviewState {
  switch (action.type) {
    case "selectClaim": {
      const position = state.nav?.claimIds.indexOf(action.id) ?? -1;
      const nav = state.nav && position >= 0 ? { ...state.nav, position } : null;
      return { selectedClaimId: action.id, nav };
    }
    case "navigate": {
      const claimIds = claimIdsFor(action.analysis, action.verdict, action.scope);
      if (claimIds.length === 0) return state;
      return {
        selectedClaimId: claimIds[0],
        nav: { verdict: action.verdict, scope: action.scope, claimIds, position: 0 },
      };
    }
    case "step": {
      if (!state.nav) return state;
      const position = Math.min(Math.max(state.nav.position + action.delta, 0), state.nav.claimIds.length - 1);
      return { selectedClaimId: state.nav.claimIds[position], nav: { ...state.nav, position } };
    }
  }
}
