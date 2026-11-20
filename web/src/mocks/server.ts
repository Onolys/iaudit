/** Node MSW server for Vitest. */
import { setupServer } from "msw/node";
import { mockBackend, mockEmitter } from "./backend";
import { handlers } from "./handlers";

export { mockBackend, mockEmitter };
export const server = setupServer(...handlers);
