/**
 * SP05 Task 12: privacy guarantees as tests (PRD R8, D10, AC8): every host the app can reach is in the CSP,
 * no analytics, no app data in browser storage, no PHI in titles or console output.
 */
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";
import { WEB_ROOT, allowedBy, cspOf, readHosting } from "./csp";

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((d) => {
    const p = join(dir, d.name);
    if (d.isDirectory()) return d.name === "mocks" || d.name === "test" ? [] : sourceFiles(p);
    return /\.(ts|tsx)$/.test(d.name) && !/\.test\.tsx?$/.test(d.name) && d.name !== "schema.d.ts" && !/\.d\.ts$/.test(d.name) ? [p] : [];
  });
}
const files = sourceFiles(join(WEB_ROOT, "src")).filter((f) => !f.includes("/hosting/"));
const read = (f: string) => readFileSync(f, "utf8");
const rel = (f: string) => relative(WEB_ROOT, f);

/** Hosts each SDK feature the app uses talks to, and the CSP directive that must allow it. Config, not code. */
const REACHABLE: { why: string; url: string; directive: string }[] = [
  { why: "API (relative /v1, Hosting rewrite)", url: "/v1/sessions", directive: "connect-src" },
  { why: "Auth: sign-in/sign-up/reset REST", url: "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword", directive: "connect-src" },
  { why: "Auth: token refresh", url: "https://securetoken.googleapis.com/v1/token", directive: "connect-src" },
  { why: "Auth popup: gapi loader (firebase/auth bundles https://apis.google.com/js/api.js)", url: "https://apis.google.com/js/api.js", directive: "script-src" },
  { why: "Auth popup: Google account chooser", url: "https://accounts.google.com/o/oauth2/auth", directive: "frame-src" },
  { why: "Auth popup/redirect helper iframe on a firebaseapp.com authDomain", url: "https://onolys.firebaseapp.com/__/auth/iframe", directive: "frame-src" },
  { why: "Auth helper iframe on our own authDomain (app.onolys.com)", url: "/__/auth/iframe", directive: "frame-src" },
  { why: "Firestore status listener (WebChannel)", url: "https://firestore.googleapis.com/google.firestore.v1.Firestore/Listen/channel", directive: "connect-src" },
  { why: "Audio upload to the signed GCS URL the API returns", url: "https://storage.googleapis.com/onolys-audio-prod/uploads/x", directive: "connect-src" },
];

describe("reachable hosts are in the CSP", () => {
  for (const entry of readHosting()) {
    for (const r of REACHABLE) {
      it(`${entry.target}: ${r.why}`, () => {
        expect(allowedBy(cspOf(entry)[r.directive], r.url)).toBe(true);
      });
    }
  }

  it("the app source names no absolute URL except the placeholder base in client.ts", () => {
    const found = files.flatMap((f) => [...read(f).matchAll(/https?:\/\/[^\s"'`)]+/g)].map((m) => `${rel(f)} ${m[0]}`));
    // doc comments may mention hosts; everything else must be a known one
    const code = files.flatMap((f) =>
      read(f)
        .split("\n")
        .filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l))
        .flatMap((l) => [...l.matchAll(/https?:\/\/[^\s"'`)]+/g)].map((m) => `${rel(f)} ${m[0]}`)),
    );
    expect(code).toEqual(["src/api/client.ts http://localhost"]);
    expect(found.length).toBeGreaterThanOrEqual(code.length);
  });

  it("env templates only point at the same origin or a CSP-allowed host", () => {
    const entry = readHosting()[0];
    const csp = cspOf(entry);
    for (const name of [".env.example", ".env.mock"]) {
      for (const line of read(join(WEB_ROOT, name)).split("\n")) {
        const m = /^(VITE_[A-Z_]+)=(.*)$/.exec(line.trim());
        if (!m || !m[2]) continue;
        const [, key, value] = m;
        if (key === "VITE_API_BASE_URL") expect(allowedBy(csp["connect-src"], value)).toBe(true);
        if (key === "VITE_FIREBASE_AUTH_DOMAIN") {
          // our own host (self) or a <project>.firebaseapp.com host
          expect(value === "app.onolys.com" || allowedBy(csp["frame-src"], `https://${value}`)).toBe(true);
        }
        if (key === "VITE_FIRESTORE_EMULATOR") throw new Error("emulator host must not be set in a committed template");
      }
    }
  });

  it("Firestore is initialised without a custom host and the emulator only when configured", () => {
    const src = read(join(WEB_ROOT, "src/api/firestoreListener.ts")).replace(/\/\*[\s\S]*?\*\//g, "");
    expect(src).not.toMatch(/\bhost\s*:/);
    expect(src).not.toMatch(/experimentalForceLongPolling|ssl\s*:\s*false/);
    expect(src).toMatch(/if \(config\.emulator\)/);
  });

  it("the API base URL default is relative", () => {
    expect(read(join(WEB_ROOT, "src/api/client.ts"))).toMatch(/DEFAULT_BASE_URL\s*=\s*"\/v1"/);
  });
});

describe("no analytics or telemetry", () => {
  const BAD = /firebase\/(analytics|performance|remote-config|messaging)|gtag|googletagmanager|google-analytics|sentry|datadog|mixpanel|segment\.|amplitude|posthog|hotjar|fullstory|logrocket|bugsnag|newrelic/i;

  it("source imports no analytics or error-reporting code", () => {
    for (const f of files) expect(read(f), rel(f)).not.toMatch(BAD);
  });

  it("only firebase/app, firebase/auth and firebase/firestore are imported", () => {
    const mods = new Set(files.flatMap((f) => [...read(f).matchAll(/["'](firebase\/[a-z-]+)["']/g)].map((m) => m[1])));
    expect([...mods].sort()).toEqual(["firebase/app", "firebase/auth", "firebase/firestore"]);
  });

  it("package.json has no analytics dependency", () => {
    const pkg = JSON.parse(read(join(WEB_ROOT, "package.json"))) as { dependencies: Record<string, string> };
    expect(Object.keys(pkg.dependencies).filter((d) => BAD.test(d))).toEqual([]);
  });

  it("index.html loads no remote script, font or style", () => {
    expect(read(join(WEB_ROOT, "index.html"))).not.toMatch(/(src|href)="https?:/);
  });
});

describe("no app data in browser storage", () => {
  it("source never touches localStorage, sessionStorage, IndexedDB, cookies or the Cache API", () => {
    for (const f of files) {
      expect(read(f), rel(f)).not.toMatch(/localStorage|sessionStorage|indexedDB|document\.cookie|\bcaches\.|serviceWorker\.register|setPersistence|persistentLocalCache/);
    }
  });

  it("Firestore uses a memory cache", () => {
    expect(read(join(WEB_ROOT, "src/api/firestoreListener.ts"))).toMatch(/memoryLocalCache\(\)/);
  });
});

describe("no PHI in titles or console output", () => {
  it("the document title is the static one in index.html and never assigned", () => {
    expect(read(join(WEB_ROOT, "index.html"))).toMatch(/<title>Onolys<\/title>/);
    for (const f of files) expect(read(f), rel(f)).not.toMatch(/document\.title|<title|react-helmet/);
  });

  it("the only console call logs span ids, not text", () => {
    const calls = files.flatMap((f) => [...read(f).matchAll(/console\.\w+\([^;]*\);/g)].map((m) => `${rel(f)} ${m[0]}`));
    expect(calls).toEqual(['src/lib/spans.ts console.warn("transcript: span does not match turn text", rejected.map((r) => r.id));']);
  });
});
