import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { renderApp } from "../test/renderApp";

// Flaky: failed once on main CI (toHaveFocus), passed on PR head. Non-blocking; see docs/reference/testing.md "Flaky tests".
describe("route table (flaky)", () => {
  it("moves focus to the h1 on navigation", { retry: 2 }, async () => {
    const { router } = renderApp("/login");
    expect(await screen.findByRole("heading", { level: 1, name: "Log in" })).toHaveFocus();
    await userEvent.click(screen.getByRole("link", { name: "Sample report" }));
    expect(router.state.location.pathname).toBe("/sample-report");
    expect(await screen.findByRole("heading", { level: 1, name: "Sample report" })).toHaveFocus();
  });
});
