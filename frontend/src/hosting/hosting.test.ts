/** SP07 Task 8: `frontend/firebase.json` serves the admin SPA with SPA fallback only and the SP05-style headers (PRD R1, R5). */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

interface Entry {
  target?: string;
  public?: string;
  ignore?: string[];
  rewrites?: { source: string; destination?: string; run?: unknown }[];
  headers?: { source: string; headers: { key: string; value: string }[] }[];
}

const cfg = JSON.parse(readFileSync(resolve(import.meta.dirname, "../../firebase.json"), "utf8")) as { hosting: Entry | Entry[] };
const entries = Array.isArray(cfg.hosting) ? cfg.hosting : [cfg.hosting];
const TARGETS = ["admin", "admin-staging"];
const byTarget = (t: string) => entries.find((e) => e.target === t)!;
const header = (e: Entry, source: string, key: string) =>
  e.headers?.find((h) => h.source === source)?.headers.find((h) => h.key === key)?.value;

function csp(e: Entry): Record<string, string[]> {
  const value = header(e, "**", "Content-Security-Policy");
  if (!value) throw new Error("no Content-Security-Policy header");
  const out: Record<string, string[]> = {};
  for (const part of value.split(";")) {
    const [name, ...sources] = part.trim().split(/\s+/);
    if (name) out[name] = sources;
  }
  return out;
}

/** The Cloud Run origin is only known after Terraform (it embeds the project number): the repo holds a placeholder the deploy substitutes. */
const BACKEND_ORIGIN = /^(__ADMIN_BACKEND_ORIGIN__|https:\/\/onolys-admin-backend-[a-z]+-\d+\.[a-z0-9-]+\.run\.app)$/;

describe("frontend/firebase.json", () => {
  it("has one hosting entry per admin target, serving dist", () => {
    expect(entries.map((e) => e.target).sort()).toEqual(TARGETS);
    for (const e of entries) expect(e.public).toBe("dist");
  });

  it.each(TARGETS)("%s has the SPA fallback as its only rewrite (no /v1, no /eval-api)", (target) => {
    expect(byTarget(target).rewrites).toEqual([{ source: "**", destination: "/index.html" }]);
  });

  it.each(TARGETS)("%s carries the CSP", (target) => {
    const c = csp(byTarget(target));
    expect(c["default-src"]).toEqual(["'self'"]);
    expect(c["script-src"]).toEqual(["'self'", "https://apis.google.com"]);
    expect(c["style-src"]).toEqual(["'self'"]);
    expect(c["img-src"]).toEqual(["'self'", "data:"]);
    expect(c["frame-ancestors"]).toEqual(["'none'"]);
    expect(c["frame-src"]).toEqual(expect.arrayContaining(["https://accounts.google.com", "https://*.firebaseapp.com"]));
  });

  it.each(TARGETS)("%s limits connect-src to self, Identity Platform and the admin-backend origin", (target) => {
    const sources = csp(byTarget(target))["connect-src"];
    expect(sources).toEqual(expect.arrayContaining(["https://identitytoolkit.googleapis.com", "https://securetoken.googleapis.com"]));
    const rest = sources.filter((s) => !["'self'", "https://identitytoolkit.googleapis.com", "https://securetoken.googleapis.com"].includes(s));
    expect(rest).toHaveLength(1);
    expect(rest[0]).toMatch(BACKEND_ORIGIN);
  });

  it("allows no unsafe or wildcard-everything sources", () => {
    for (const e of entries) {
      for (const sources of Object.values(csp(e))) {
        expect(sources).not.toContain("'unsafe-inline'");
        expect(sources).not.toContain("'unsafe-eval'");
        expect(sources).not.toContain("*");
      }
      expect(csp(e)["connect-src"].join(" ")).not.toContain("run.app/*");
      expect(csp(e)["connect-src"].some((s) => s.includes("*"))).toBe(false);
    }
  });

  it.each(TARGETS)("%s sends the security and cache headers", (target) => {
    const e = byTarget(target);
    expect(header(e, "**", "Referrer-Policy")).toBe("no-referrer");
    expect(header(e, "**", "X-Content-Type-Options")).toBe("nosniff");
    expect(header(e, "**", "Cache-Control")).toBe("no-cache");
    expect(header(e, "/assets/**", "Cache-Control")).toBe("public, max-age=31536000, immutable");
    // hashed assets come after the catch-all so the immutable value wins
    expect(e.headers!.findIndex((h) => h.source === "/assets/**")).toBeGreaterThan(e.headers!.findIndex((h) => h.source === "**"));
  });

  it("never serves firebase.json or dotfiles", () => {
    for (const e of entries) expect(e.ignore).toEqual(expect.arrayContaining(["firebase.json", "**/.*", "**/node_modules/**"]));
  });
});
