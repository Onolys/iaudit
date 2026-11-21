import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { AuthService, AuthUser } from "./types";

export interface AuthContextValue {
  service: AuthService;
  /** `loading` until the SDK reports its initial state. */
  status: "loading" | "ready";
  user: AuthUser | null;
  /** Signs out and drops every cached query (no PHI left in memory). */
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ service, children }: { service: AuthService; children: ReactNode }) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<{ status: "loading" | "ready"; user: AuthUser | null }>({
    status: "loading",
    user: null,
  });

  const signedIn = useRef(false);
  useEffect(
    () =>
      service.onAuthStateChanged((user) => {
        signedIn.current = user !== null;
        setState({ status: "ready", user });
      }),
    [service],
  );

  // One sign-out at a time: queries still mounted after clear() may 401 again before the guard navigates.
  const inflight = useRef<Promise<void> | null>(null);
  const signOut = useCallback(() => {
    if (!signedIn.current) return Promise.resolve();
    inflight.current ??= (async () => {
      try {
        await service.signOut();
      } finally {
        queryClient.clear();
        inflight.current = null;
      }
    })();
    return inflight.current;
  }, [service, queryClient]);

  const value = useMemo(() => ({ service, ...state, signOut }), [service, state, signOut]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>.");
  return ctx;
}
