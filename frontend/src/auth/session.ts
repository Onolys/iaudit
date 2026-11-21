import { createAuthFetch } from "../transport/authFetch";
import type { AuthProvider, AuthUser } from "./types";

export type AuthStatus = "loading" | "signed-out" | "signed-in" | "forbidden";
export interface AuthSnapshot {
  status: AuthStatus;
  user: AuthUser | null;
}

export interface AuthSession {
  getSnapshot(): AuthSnapshot;
  subscribe(cb: () => void): () => void;
  signInWithEmail(email: string, password: string): Promise<void>;
  signInWithGoogle(): Promise<void>;
  signOut(): Promise<void>;
  /** Wrap a fetch so requests carry the bearer token and 401/403 drive the gate. */
  createFetch(base?: typeof fetch): typeof fetch;
}

export function createAuthSession(provider: AuthProvider): AuthSession {
  let snap: AuthSnapshot = { status: "loading", user: null };
  const listeners = new Set<() => void>();
  const set = (next: AuthSnapshot) => {
    snap = next;
    listeners.forEach(l => l());
  };
  provider.onAuthChange(user => {
    if (!user) set({ status: "signed-out", user: null });
    else set({ status: snap.status === "forbidden" ? "forbidden" : "signed-in", user });
  });
  return {
    getSnapshot: () => snap,
    subscribe(cb) {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    signInWithEmail: (email, password) => provider.signInWithEmail(email, password),
    signInWithGoogle: () => provider.signInWithGoogle(),
    async signOut() {
      await provider.signOut();
      set({ status: "signed-out", user: null });
    },
    createFetch: (base = (input, init) => fetch(input, init)) =>
      createAuthFetch({
        fetch: base,
        getToken: force => provider.getIdToken(force),
        onUnauthorized: () => {
          set({ status: "signed-out", user: null });
          void provider.signOut().catch(() => undefined);
        },
        onForbidden: () => set({ status: "forbidden", user: snap.user }),
      }),
  };
}
