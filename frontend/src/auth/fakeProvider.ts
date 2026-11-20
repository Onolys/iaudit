import { vi } from "vitest";
import type { AuthProvider, AuthUser } from "./types";

/** Test double for AuthProvider: no network, scripted tokens. */
export function createFakeProvider(initial: AuthUser | null = null) {
  let user = initial;
  const listeners = new Set<(u: AuthUser | null) => void>();
  let n = 0;
  const emit = () => listeners.forEach(l => l(user));
  const provider = {
    onAuthChange(cb: (u: AuthUser | null) => void) {
      listeners.add(cb);
      queueMicrotask(() => cb(user));
      return () => listeners.delete(cb);
    },
    getIdToken: vi.fn(async (force?: boolean) => (user ? (force ? `fresh-${++n}` : "tok-0") : null)),
    signInWithEmail: vi.fn(async (email: string, _password: string) => { user = { email }; emit(); }),
    signInWithGoogle: vi.fn(async () => { user = { email: "g@example.com" }; emit(); }),
    signOut: vi.fn(async () => { user = null; emit(); }),
  } satisfies AuthProvider;
  return provider;
}
