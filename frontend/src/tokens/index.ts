export type Verdict =
  | "supported"
  | "partially_supported"
  | "contradicted"
  | "insufficient_evidence"
  | "out_of_scope";

export type EvidenceRole = "supporting" | "contradicting" | "qualifying";

export interface VerdictStyle {
  label: string;
  icon: string;
  color: string;
  underline: "solid" | "dashed" | "dotted";
}

export interface RoleStyle {
  label: string;
  color: string;
}

// Keep in sync with tokens.css (tokens.test.ts enforces it).
export const VERDICT_STYLE: Record<Verdict, VerdictStyle> = {
  supported: { label: "Supported", icon: "✓", color: "#1a7f37", underline: "solid" },
  partially_supported: { label: "Partially supported", icon: "◐", color: "#b45309", underline: "solid" },
  contradicted: { label: "Contradicted", icon: "✕", color: "#c62828", underline: "solid" },
  insufficient_evidence: { label: "Insufficient evidence", icon: "?", color: "#6b7280", underline: "dashed" },
  out_of_scope: { label: "Out of scope", icon: "▨", color: "#9ca3af", underline: "dotted" },
};

export const ROLE_STYLE: Record<EvidenceRole, RoleStyle> = {
  supporting: { label: "Supporting", color: "#1a7f37" },
  contradicting: { label: "Contradicting", color: "#c62828" },
  qualifying: { label: "Qualifying", color: "#b45309" },
};

export const SELECTED_CLAIM_BACKGROUND = "#e5e7eb";
