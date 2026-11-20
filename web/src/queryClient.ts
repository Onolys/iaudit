import { QueryClient } from "@tanstack/react-query";

/** In-memory only, short-lived cache: no PHI persisted (PRD R8, D3). */
export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { gcTime: 2 * 60 * 1000, staleTime: 0, retry: 1, refetchOnWindowFocus: false },
    },
  });
}
