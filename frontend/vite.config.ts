import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const contracts = fileURLToPath(new URL("../docs/contracts", import.meta.url));
const root = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@contracts": contracts } },
  server: { fs: { allow: [root, contracts] } },
  test: { environment: "node" },
});
