import type { AuditResponse } from "../contract";

export function WarningsBanner({ response }: { response: AuditResponse }) {
  if (response.status !== "partial" && response.warnings.length === 0) return null;
  return (
    <section role="status" aria-label="Audit warnings">
      <h2>
        {response.status === "partial"
          ? "Audit is partial: some sections were not processed"
          : "Audit completed with warnings"}
      </h2>
      {response.warnings.length > 0 ? (
        <ul>
          {response.warnings.map((w, i) => (
            <li key={i}>
              <strong>{w.code.replaceAll("_", " ")}</strong>: {w.message}
              {w.section_index !== undefined ? ` (Section ${w.section_index})` : ""}
              {w.claim_id !== undefined ? ` (claim ${w.claim_id})` : ""}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
