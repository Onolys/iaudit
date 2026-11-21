import { describe, expect, it } from "vitest";
import { makeQueryClient } from "./queryClient";

describe("makeQueryClient", () => {
  it("keeps cached data only briefly, in memory (R8: no PHI persisted)", () => {
    const opts = makeQueryClient().getDefaultOptions().queries;
    expect(opts?.gcTime).toBeLessThanOrEqual(5 * 60 * 1000);
    expect(opts?.gcTime).toBeGreaterThan(0);
  });
});
