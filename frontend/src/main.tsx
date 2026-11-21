import { createRoot } from "react-dom/client";
import { shouldGate, createAuthSession } from "./auth";
import { getConfig } from "./config";
import { Root } from "./Root";

async function start() {
  const config = getConfig();
  let session = null;
  if (shouldGate(config)) {
    const { createFirebaseProvider } = await import("./auth/firebase");
    session = createAuthSession(createFirebaseProvider(config.firebase));
  }
  createRoot(document.getElementById("root")!).render(<Root session={session} />);
}
void start();
