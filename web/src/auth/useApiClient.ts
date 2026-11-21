import { useMemo } from "react";
import { createApiClient, DEFAULT_BASE_URL } from "../api/client";
import { useAuth } from "./AuthProvider";

/** API client wired to the auth service: per-request token, one forced refresh on 401, then sign-out (D8). */
export function useApiClient() {
  const { service, signOut } = useAuth();
  return useMemo(
    () =>
      createApiClient({
        baseUrl: new URL(import.meta.env.VITE_API_BASE_URL ?? DEFAULT_BASE_URL, window.location.origin).href.replace(/\/$/, ""),
        getToken: (force) => service.getToken(force),
        onSessionExpired: () => void signOut(),
      }),
    [service, signOut],
  );
}
