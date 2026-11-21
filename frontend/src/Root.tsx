import App from "./App";
import { AuthGate } from "./auth";
import type { AuthSession } from "./auth";
import { getConfig } from "./config";
import { defaultRegistry } from "./transport/mock/registry";

/** `session` is null when the gate is off (local dev, VITE_MOCK): the app mounts with no auth involvement. */
export function Root({ session }: { session: AuthSession | null }) {
  if (!session) return <App />;
  return (
    <AuthGate session={session}>
      <App deps={{ fetch: session.createFetch(), config: getConfig(), registry: defaultRegistry }} />
    </AuthGate>
  );
}
