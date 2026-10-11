import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { ROLE_STYLE, selectedClaimBackground, VERDICT_STYLE } from "./index";

const css = readFileSync(new URL("./tokens.css", import.meta.url), "utf8");

describe("tokens", () => {
  it("exposes every value as a matching CSS custom property", () => {
    for (const [k, v] of Object.entries(VERDICT_STYLE)) {
      expect(css).toContain(`--verdict-${k.replaceAll("_", "-")}: ${v.color};`);
    }
    for (const [k, v] of Object.entries(ROLE_STYLE)) {
      expect(css).toContain(`--role-${k}: ${v.color};`);
    }
    expect(css).toContain(`--selected-claim-bg: ${selectedClaimBackground};`);
  });

  it("uses the fixed underline styles", () => {
    expect(VERDICT_STYLE.insufficient_evidence.underline).toBe("dashed");
    expect(VERDICT_STYLE.out_of_scope.underline).toBe("dotted");
    expect(VERDICT_STYLE.supported.underline).toBe("solid");
  });
});
