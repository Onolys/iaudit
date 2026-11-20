import { rmSync } from "node:fs";
import { join } from "node:path";
import react from "@vitejs/plugin-react";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";

/** `public/mockServiceWorker.js` is for `dev:mock` only; every build except `--mode mock` drops it from `dist/` (PRD R8). */
function dropMockWorker(mode: string): Plugin {
  return {
    name: "drop-mock-service-worker",
    apply: "build",
    closeBundle() {
      if (mode === "mock") return;
      rmSync(join(this.environment.config.build.outDir, "mockServiceWorker.js"), { force: true });
    },
  };
}

export default defineConfig(({ mode }) => ({
  plugins: [react(), dropMockWorker(mode)],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    globals: false,
  },
}));
