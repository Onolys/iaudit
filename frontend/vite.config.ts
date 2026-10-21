import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";

const contracts = fileURLToPath(new URL("../docs/contracts", import.meta.url));
const evalApi = fileURLToPath(new URL("../eval/api", import.meta.url));
const root = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig(({ mode }) => {
  const { IAUDIT_EVAL_PORT } = loadEnv(mode, root, "IAUDIT_EVAL_PORT");
  const proxy = {
    "/eval-api": {
      target: `http://127.0.0.1:${IAUDIT_EVAL_PORT ?? 8100}`,
      changeOrigin: false,
      rewrite: (path: string) => path.replace(/^\/eval-api/, ""),
    },
  };
  return {
    plugins: [react()],
    resolve: { alias: { "@contracts": contracts, "@eval-api": evalApi } },
    server: { fs: { allow: [root, contracts, evalApi] }, proxy },
    preview: { proxy },
    test: { environment: "node" },
  };
});
