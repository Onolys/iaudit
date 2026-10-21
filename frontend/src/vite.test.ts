import { createServer as createHttpServer } from "node:http";
import type { AddressInfo } from "node:net";
import { fileURLToPath } from "node:url";
import { afterEach, expect, it, vi } from "vitest";
import { createServer, resolveConfig } from "vite";

const configFile = fileURLToPath(new URL("../vite.config.ts", import.meta.url));

afterEach(() => vi.unstubAllEnvs());

it.each([undefined, "9123"])("uses the configured eval port (%s) for dev and preview", async (port) => {
  vi.stubEnv("IAUDIT_EVAL_PORT", port);
  const config = await resolveConfig({ configFile, logLevel: "silent" }, "serve");
  const expectedTarget = port === undefined ? "http://127.0.0.1:8100" : "http://127.0.0.1:9123";
  for (const proxy of [config.server.proxy, config.preview.proxy]) {
    expect(proxy?.["/eval-api"]).toMatchObject({ target: expectedTarget, changeOrigin: false });
  }
  expect(config.server.fs.allow).toContain(fileURLToPath(new URL("../../eval/api", import.meta.url)));
});

it("proxies health to a local stub without the prefix and preserves the original Host", async () => {
  const stub = createHttpServer((request, response) => {
    response.setHeader("Content-Type", "application/json");
    response.end(JSON.stringify({ path: request.url, host: request.headers.host }));
  });
  await new Promise<void>((resolve) => stub.listen(0, "127.0.0.1", resolve));
  let vite: Awaited<ReturnType<typeof createServer>> | undefined;
  try {
    vi.stubEnv("IAUDIT_EVAL_PORT", String((stub.address() as AddressInfo).port));
    vite = await createServer({ configFile, logLevel: "silent", server: { host: "127.0.0.1", port: 0 } });
    await vite.listen();
    const port = (vite.httpServer!.address() as AddressInfo).port;
    const response = await fetch(`http://127.0.0.1:${port}/eval-api/health?probe=offline`);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ path: "/health?probe=offline", host: `127.0.0.1:${port}` });
  } finally {
    await vite?.close();
    await new Promise<void>((resolve, reject) => stub.close((error) => error ? reject(error) : resolve()));
  }
});
