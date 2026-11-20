/** Node MSW server for Vitest. */
import { setupServer } from "msw/node";
import { mockBackend } from "./backend";
import { handlers } from "./handlers";

export { mockBackend };
export const server = setupServer(...handlers);
