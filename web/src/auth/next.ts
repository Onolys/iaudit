/** `?next=` handling: same-origin paths only (no open redirects). */

export function readNext(search: string): string {
  const raw = new URLSearchParams(search).get("next");
  if (!raw || !raw.startsWith("/") || raw.startsWith("//") || raw.includes("\\")) return "/";
  return raw;
}

function hasNext(search: string): boolean {
  return readNext(search) !== "/";
}

/** Append the validated `next` from `search` to `path` (omitted when it is just `/`). */
export function withNext(path: string, search: string): string {
  const next = readNext(search);
  return hasNext(search) ? `${path}?next=${encodeURIComponent(next)}` : path;
}

export function loginUrl(pathname: string, search: string): string {
  const target = pathname + search;
  return target === "/" ? "/login" : `/login?next=${encodeURIComponent(target)}`;
}

export function verifyUrl(pathname: string, search: string): string {
  const target = pathname + search;
  return target === "/" ? "/verify-email" : `/verify-email?next=${encodeURIComponent(target)}`;
}
