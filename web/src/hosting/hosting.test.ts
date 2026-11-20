/** SP05 Task 12: `web/firebase.json` carries the CSP, the headers and the rewrite order (PRD R8, D1, AC10). */
import { describe, expect, it } from "vitest";
import { allowedBy, cspOf, readHosting } from "./csp";

const entries = readHosting();
const byTarget = (t: string) => entries.find((e) => e.target === t)!;

describe("web/firebase.json", () => {
  it("has one hosting entry for the prod and the staging target", () => {
    expect(entries.map((e) => e.target).sort()).toEqual(["app", "app-staging"]);
    for (const e of entries) expect(e.public).toBe("dist");
  });

  it.each([
    ["app", "onolys-api-prod"],
    ["app-staging", "onolys-api-staging"],
  ])("%s rewrites /v1/** to Cloud Run %s before the SPA fallback", (target, service) => {
    const rewrites = byTarget(target).rewrites!;
    const api = rewrites.findIndex((r) => r.source === "/v1/**");
    const spa = rewrites.findIndex((r) => r.source === "**");
    expect(api).toBeGreaterThanOrEqual(0);
    expect(spa).toBeGreaterThan(api);
    expect(rewrites[api].run).toEqual({ serviceId: service, region: "us-central1" });
    expect(rewrites[spa].destination).toBe("/index.html");
  });

  it.each(["app", "app-staging"])("%s carries the CSP from PRD R8", (target) => {
    const csp = cspOf(byTarget(target));
    expect(csp["default-src"]).toEqual(["'self'"]);
    expect(csp["script-src"]).toEqual(expect.arrayContaining(["'self'"]));
    expect(csp["style-src"]).toEqual(["'self'"]);
    expect(csp["img-src"]).toEqual(["'self'", "data:"]);
    expect(csp["frame-ancestors"]).toEqual(["'none'"]);
    expect(csp["connect-src"]).toEqual(
      expect.arrayContaining([
        "'self'",
        "https://identitytoolkit.googleapis.com",
        "https://securetoken.googleapis.com",
        "https://firestore.googleapis.com",
        "https://storage.googleapis.com",
      ]),
    );
    expect(csp["frame-src"]).toEqual(expect.arrayContaining(["https://accounts.google.com", "https://*.firebaseapp.com"]));
  });

  it("allows no unsafe or wildcard-everything sources", () => {
    for (const e of entries) {
      for (const sources of Object.values(cspOf(e))) {
        expect(sources).not.toContain("'unsafe-inline'");
        expect(sources).not.toContain("'unsafe-eval'");
        expect(sources).not.toContain("*");
      }
    }
  });

  it("allows only the Google sign-in script outside our own origin", () => {
    for (const e of entries) {
      expect(cspOf(e)["script-src"]).toEqual(["'self'", "https://apis.google.com"]);
    }
  });

  it.each(["app", "app-staging"])("%s sends the security and cache headers", (target) => {
    const headers = byTarget(target).headers!;
    const find = (source: string, key: string) =>
      headers.find((h) => h.source === source)?.headers.find((h) => h.key === key)?.value;
    expect(find("**", "Referrer-Policy")).toBe("no-referrer");
    expect(find("**", "X-Content-Type-Options")).toBe("nosniff");
    expect(find("**", "Cache-Control")).toBe("no-cache");
    expect(find("/assets/**", "Cache-Control")).toBe("public, max-age=31536000, immutable");
    // hashed assets must come after the catch-all so the immutable value wins
    expect(headers.findIndex((h) => h.source === "/assets/**")).toBeGreaterThan(headers.findIndex((h) => h.source === "**"));
  });

  it("never serves the mock service worker", () => {
    for (const e of entries) expect(e.ignore).toContain("**/mockServiceWorker.js");
  });

  it("matcher sanity: wildcard and exact hosts", () => {
    expect(allowedBy(["https://*.firebaseapp.com"], "https://x.firebaseapp.com/__/auth")).toBe(true);
    expect(allowedBy(["https://*.firebaseapp.com"], "https://firebaseapp.com")).toBe(false);
    expect(allowedBy(["'self'"], "https://evil.example")).toBe(false);
  });
});
