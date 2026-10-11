import { readdirSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import * as api from "./index";

describe("contract index", () => {
  it("exports the PRD surface", () => {
    for (const name of [
      "validateRequest", "validateResponse", "analyzeResponse", "claimIdsFor",
      "notProcessedSections", "segmentSection", "walkSpan", "orderEvidence",
      "buildChunks", "sliceCodePoints", "codePointLength", "VERDICTS",
      "CONCERN_TYPES", "EVIDENCE_ROLES", "WARNING_CODES", "STATUSES",
    ]) {
      expect(api, name).toHaveProperty(name);
    }
  });
  it("imports no React, DOM or fetch", () => {
    const dir = new URL(".", import.meta.url);
    for (const f of readdirSync(dir).filter((f) => f.endsWith(".ts") && !f.endsWith(".test.ts"))) {
      const src = readFileSync(new URL(f, dir), "utf8");
      expect(src, f).not.toMatch(/from "react|document\.|window\.|fetch\(/);
    }
  });
});
