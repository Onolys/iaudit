import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { createFirestoreStatusListener } from "./api/firestoreListener";
import { setStatusListener } from "./api/statusListener";
import { createAuthService } from "./auth/createAuthService";
import "./styles/inter-latin.css";
import "./styles/tokens.css";
import "./styles/app.css";

async function enableMocking(): Promise<void> {
  if (import.meta.env.VITE_USE_MOCKS !== "true") return;
  const { startMockWorker } = await import("./mocks/browser");
  await startMockWorker();
}

function registerStatusListener(): void {
  if (import.meta.env.VITE_USE_MOCKS === "true") return; // the mock worker registers the in-memory emitter
  setStatusListener(
    createFirestoreStatusListener({
      database: import.meta.env.VITE_FIRESTORE_DATABASE,
      emulator: import.meta.env.VITE_FIRESTORE_EMULATOR,
    }),
  );
}

void enableMocking()
  .then(registerStatusListener)
  .then(() => createAuthService())
  .then((authService) => {
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App authService={authService} />
    </StrictMode>,
  );
});
