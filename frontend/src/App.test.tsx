// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import App from "./App";
import type { AuditDeps } from "./transport/runAudit";

import requestRaw from "@contracts/examples/request.json?raw";
import responseRaw from "@contracts/examples/response.json?raw";

afterEach(cleanup);

const okDeps = (response = responseRaw, mock = false): AuditDeps => ({
  fetch: (async () => new Response(response, { status: 200 })) as typeof fetch,
  config: { mock, auditUrl: "https://audit.example/api" },
  registry: [],
});

const input = (c: HTMLElement) => c.querySelector('input[type="file"]') as HTMLInputElement;
const upload = async (c: HTMLElement, text = requestRaw, name = "req.json") => {
  await act(async () => {
    fireEvent.change(input(c), { target: { files: [new File([text], name)] } });
  });
};

describe("App screen", () => {
  it("shows the idle prompt and a hidden file input accepting JSON", () => {
    const { container } = render(<App deps={okDeps()} />);
    expect(screen.getByText("Upload a request JSON file to begin.")).toBeTruthy();
    expect(input(container).accept).toBe(".json,application/json");
    expect(input(container).hidden).toBe(true);
    expect(screen.getByText("No request ID")).toBeTruthy();
  });

  it("shows header file name, request_id and five counts after load", async () => {
    const { container } = render(<App deps={okDeps()} />);
    await upload(container);
    await waitFor(() => expect(screen.getByText("example-001")).toBeTruthy());
    expect(screen.getByText("req.json")).toBeTruthy();
    const counts = container.querySelectorAll("header .verdict-count");
    expect(counts).toHaveLength(5);
    for (const c of counts) expect(c.querySelector("strong")!.textContent).toBe("1");
    expect(screen.queryByText("Mock data")).toBeNull();
  });

  it("shows the Mock data chip for mock results", async () => {
    const mockDeps: AuditDeps = {
      ...okDeps(),
      config: { mock: true, auditUrl: null },
      registry: [{ name: "default", loadRequest: async () => requestRaw, loadResponse: async () => responseRaw }],
      mockDelayMs: 0,
    };
    const { container } = render(<App deps={mockDeps} />);
    await upload(container);
    await waitFor(() => expect(screen.getByText("Mock data")).toBeTruthy());
  });

  it("shows the error screen and no stale audit", async () => {
    const { container } = render(<App deps={okDeps()} />);
    await upload(container);
    await waitFor(() => screen.getByText("example-001"));
    await upload(container, "not json", "bad.json");
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(container.querySelectorAll(".verdict-count")).toHaveLength(0);
    expect(screen.queryByText("example-001")).toBeNull();
  });

  it("resets the input value so the same file fires again, and resets the review", async () => {
    const { container } = render(<App deps={okDeps()} />);
    await upload(container);
    await waitFor(() => screen.getByText("example-001"));
    fireEvent.click(container.querySelector(".verdict-count")!);
    expect(container.querySelector('.verdict-count[aria-pressed="true"]')).toBeTruthy();
    await upload(container);
    await waitFor(() => expect(container.querySelector('.verdict-count[aria-pressed="true"]')).toBeNull());
    expect(input(container).value).toBe("");
  });

  it("clicking a header count marks it pressed", async () => {
    const { container } = render(<App deps={okDeps()} />);
    await upload(container);
    await waitFor(() => screen.getByText("example-001"));
    fireEvent.click(screen.getByRole("button", { name: /Contradicted/ }));
    expect(screen.getByRole("button", { name: /Contradicted/ }).getAttribute("aria-pressed")).toBe("true");
  });
});
