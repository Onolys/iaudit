/** SP05 Task 12: production build output satisfies `style-src 'self'` and ships no mock worker or inline script. */
import { mkdtempSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { build } from "vite";
import { WEB_ROOT } from "./csp";

let out = "";
const all = (d: string): string[] => readdirSync(d, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? all(join(d, e.name)) : [join(d, e.name)]));

beforeAll(async () => {
  out = mkdtempSync(join(tmpdir(), "onolys-web-dist-"));
  await build({ root: WEB_ROOT, mode: "production", logLevel: "silent", build: { outDir: out, emptyOutDir: true }, configFile: join(WEB_ROOT, "vite.config.ts") });
}, 170_000);
afterAll(() => rmSync(out, { recursive: true, force: true }));

describe("production build", () => {
  it("index.html has no inline <style>, style attribute or inline script", () => {
    const html = readFileSync(join(out, "index.html"), "utf8");
    expect(html).not.toMatch(/<style[\s>]/i);
    expect(html).not.toMatch(/\sstyle\s*=/i);
    expect(html).not.toMatch(/<script(?![^>]*\ssrc=)[^>]*>/i);
  });

  it("styles are emitted as .css files, none injected from JS as a <style> element", () => {
    const files = all(out);
    expect(files.some((f) => f.endsWith(".css"))).toBe(true);
    for (const f of files.filter((x) => x.endsWith(".js"))) {
      expect(readFileSync(f, "utf8"), f).not.toMatch(/createElement\(["']style["']\)/);
    }
  });

  it("ships no mock service worker and no MSW code", () => {
    const files = all(out);
    expect(files.filter((f) => /mockServiceWorker/.test(f))).toEqual([]);
    for (const f of files.filter((x) => x.endsWith(".js"))) expect(readFileSync(f, "utf8"), f).not.toMatch(/mockServiceWorker/);
  });
});
