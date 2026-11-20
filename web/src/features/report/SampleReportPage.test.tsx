import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { server } from "../../mocks/server";
import { renderApp } from "../../test/renderApp";

afterEach(() => {
  server.events.removeAllListeners();
  window.location.hash = "";
});

describe("/sample-report", () => {
  it("renders the bundled report and transcript with zero network requests, signed out", async () => {
    const requests: string[] = [];
    server.events.on("request:start", ({ request }) => void requests.push(`${request.method} ${request.url}`));
    renderApp("/sample-report");
    const main = within(screen.getByRole("main"));
    expect(await main.findByRole("heading", { name: "Sample report" })).toBeInTheDocument();
    expect(main.getByText(/^Sample$/)).toBeInTheDocument();
    expect(main.getByRole("region", { name: "Scorecard" })).toBeInTheDocument();
    expect(main.getByRole("region", { name: "Transcript" })).toHaveTextContent("I'd like to start walking more");
    await new Promise((r) => setTimeout(r, 50));
    expect(requests).toEqual([]);
  });

  it("has no Run again, rating or delete controls", async () => {
    renderApp("/sample-report");
    const main = within(screen.getByRole("main"));
    await main.findByRole("region", { name: "Scorecard" });
    expect(main.queryByRole("button", { name: /run again/i })).toBeNull();
    expect(main.queryByRole("button", { name: /rating/i })).toBeNull();
    expect(main.queryByRole("button", { name: /delete/i })).toBeNull();
  });
});
