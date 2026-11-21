/** Browser MSW worker for `npm run dev:mock` (VITE_USE_MOCKS=true). */
import { setupWorker } from "msw/browser";
import { setStatusListener } from "../api/statusListener";
import { mockBackend, mockEmitter } from "./backend";
import { handlers } from "./handlers";

const worker = setupWorker(...handlers);

/** Start the worker, register the in-memory status listener, and advance the fake worker. */
export async function startMockWorker(stepMs = 1500): Promise<void> {
  await worker.start({ onUnhandledFrame: "bypass", quiet: true });
  setStatusListener(mockEmitter);
  setInterval(() => mockBackend.advanceAll(), stepMs);
}
