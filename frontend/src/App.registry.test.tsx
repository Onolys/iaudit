// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";

vi.mock("./products", () => ({ PRODUCTS: [{ id: "eaudit", label: "Evidence review" }] }));

afterEach(cleanup);

it("uses the product registry label for the selected product tab", () => {
  render(<App />);
  expect(screen.getByRole("button", { name: "Evidence review", pressed: true })).toBeTruthy();
  expect(screen.getByText("Upload a request JSON file to begin.")).toBeTruthy();
});
