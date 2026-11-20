import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { createAuthService } from "./auth/createAuthService";
import "./styles/inter-latin.css";
import "./styles/tokens.css";
import "./styles/app.css";

async function enableMocking(): Promise<void> {
  if (import.meta.env.VITE_USE_MOCKS !== "true") return;
  const { startMockWorker } = await import("./mocks/browser");
  await startMockWorker();
}

void enableMocking()
  .then(() => createAuthService())
  .then((authService) => {
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App authService={authService} />
    </StrictMode>,
  );
});
