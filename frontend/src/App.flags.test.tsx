// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";
import type { EvalApi } from "./eval/evalApi";

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

const spyApi = () => {
  const calls: string[] = [];
  const handler = { get: (_: object, name: string) => (...args: unknown[]) => { calls.push(name); void args; return Promise.resolve([]); } };
  return { api: new Proxy({}, handler) as unknown as EvalApi, calls };
};

it("shows eaudit view by default and switches to the paudit view", () => {
  render(<App />);
  expect(screen.getByText("Upload a request JSON file to begin.")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "paudit" }));
  expect(screen.getByRole("button", { name: "paudit", pressed: true })).toBeTruthy();
  expect(screen.getByTestId("paudit-view")).toBeTruthy();
  expect(screen.queryByText("Upload a request JSON file to begin.")).toBeNull();
});

it("shows the Eval tab by default (local dev)", () => {
  render(<App />);
  expect(screen.getByRole("button", { name: "Eval" })).toBeTruthy();
});

it("hides the Eval tab and makes zero eval requests when VITE_EVAL_ENABLED=false", async () => {
  vi.stubEnv("VITE_EVAL_ENABLED", "false");
  const fetchSpy = vi.spyOn(globalThis, "fetch");
  const { api, calls } = spyApi();
  render(<App evalApi={api} />);
  expect(screen.queryByRole("button", { name: "Eval" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "paudit" }));
  fireEvent.click(screen.getByRole("button", { name: "eaudit" }));
  await Promise.resolve();
  expect(calls).toEqual([]);
  expect(fetchSpy.mock.calls.filter(([u]) => String(u).includes("eval-api"))).toEqual([]);
  fetchSpy.mockRestore();
});
