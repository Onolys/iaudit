import { readFileSync } from "node:fs";
import { resolve } from "node:path";

export const WEB_ROOT = resolve(import.meta.dirname, "../..");

export interface HostingEntry {
  target?: string;
  public?: string;
  ignore?: string[];
  rewrites?: { source: string; destination?: string; run?: { serviceId: string; region: string } }[];
  headers?: { source: string; headers: { key: string; value: string }[] }[];
}

export function readHosting(): HostingEntry[] {
  const cfg = JSON.parse(readFileSync(resolve(WEB_ROOT, "firebase.json"), "utf8")) as { hosting: HostingEntry | HostingEntry[] };
  return Array.isArray(cfg.hosting) ? cfg.hosting : [cfg.hosting];
}

/** The `Content-Security-Policy` of one hosting entry, as `directive -> sources`. */
export function cspOf(entry: HostingEntry): Record<string, string[]> {
  const value = entry.headers?.flatMap((h) => h.headers).find((h) => h.key === "Content-Security-Policy")?.value;
  if (!value) throw new Error("no Content-Security-Policy header");
  const out: Record<string, string[]> = {};
  for (const part of value.split(";")) {
    const [name, ...sources] = part.trim().split(/\s+/);
    if (name) out[name] = sources;
  }
  return out;
}

/** True when `url` (absolute, or a path meaning same-origin) is allowed by `sources` of one directive. */
export function allowedBy(sources: string[], url: string): boolean {
  if (url.startsWith("/")) return sources.includes("'self'");
  const { protocol, host } = new URL(url);
  return sources.some((s) => {
    if (s === "'self'" || s.startsWith("'")) return false;
    const m = /^(https:\/\/)(\*\.)?([^/]+)$/.exec(s);
    if (!m || protocol !== "https:") return false;
    return m[2] ? host.endsWith(`.${m[3]}`) : host === m[3];
  });
}
