import { useCallback, useEffect, useState } from "react";

/** `#i=<id>` -> id (ids only, never text); anything else -> null. */
export function parseInstanceHash(hash: string): string | null {
  const m = /^#i=(.+)$/.exec(hash);
  if (!m) return null;
  try {
    return decodeURIComponent(m[1]);
  } catch {
    return null;
  }
}

/** Selected instance id lives in the URL hash so links and the back button work. */
export function useSelectedInstance(): [string | null, (id: string | null) => void] {
  const [id, setId] = useState(() => parseInstanceHash(window.location.hash));
  useEffect(() => {
    const on = () => setId(parseInstanceHash(window.location.hash));
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const select = useCallback((next: string | null) => {
    window.location.hash = next ? `i=${encodeURIComponent(next)}` : "";
    setId(next);
  }, []);
  return [id, select];
}
