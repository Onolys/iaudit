import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it } from "vitest";
import { routes } from "./routes";
import { makeQueryClient } from "../queryClient";
import { QueryClientProvider } from "@tanstack/react-query";

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

const table: Array<[string, string]> = [
  ["/signup", "Sign up"],
  ["/login", "Log in"],
  ["/forgot-password", "Reset your password"],
  ["/verify-email", "Verify your email"],
  ["/", "Sessions"],
  ["/sessions/new", "New session"],
  ["/sessions/abc123", "Session"],
  ["/sessions/abc123/reports/2", "Report"],
  ["/sample-report", "Sample report"],
  ["/settings", "Settings"],
];

describe("route table", () => {
  it.each(table)("%s renders its placeholder h1", (path, heading) => {
    renderAt(path);
    expect(screen.getByRole("heading", { level: 1, name: heading })).toBeInTheDocument();
  });

  it("has banner, nav, main and contentinfo landmarks", () => {
    renderAt("/");
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("navigation")).toBeInTheDocument();
    expect(screen.getByRole("main")).toBeInTheDocument();
    expect(screen.getByRole("contentinfo")).toBeInTheDocument();
  });

  it("shows a not-found page for unknown paths", () => {
    renderAt("/nope/nothing");
    expect(screen.getByRole("heading", { level: 1, name: "Page not found" })).toBeInTheDocument();
  });

  it("moves focus to the h1 on navigation", async () => {
    const router = renderAt("/login");
    expect(screen.getByRole("heading", { level: 1, name: "Log in" })).toHaveFocus();
    await userEvent.click(screen.getByRole("link", { name: "Settings" }));
    expect(router.state.location.pathname).toBe("/settings");
    expect(screen.getByRole("heading", { level: 1, name: "Settings" })).toHaveFocus();
  });
});
