import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";
import { setStatusListener } from "../api/statusListener";
import { mockBackend, mockEmitter, server } from "../mocks/server";

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
  setStatusListener(mockEmitter); // the in-memory status doc stands in for Firestore
});
afterEach(() => {
  cleanup();
  server.resetHandlers();
  mockBackend.reset();
});
afterAll(() => server.close());
