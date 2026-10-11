// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";

import defaultRequest from "@contracts/examples/request.json?raw";
import partialRequest from "@contracts/examples/partial.request.json?raw";
import oorRequest from "@contracts/examples/out-of-range.request.json?raw";

const fetchSpy = vi.fn(() => {
  throw new Error("network is not allowed in mock mode");
});
let consoleError: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  vi.stubEnv("VITE_MOCK", "true");
  vi.stubGlobal("fetch", fetchSpy);
  consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  fetchSpy.mockClear();
  expect(consoleError).not.toHaveBeenCalled();
  consoleError.mockRestore();
});

async function upload(text: string, name = "request.json") {
  const view = render(<App />);
  const input = view.container.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [new File([text], name)] } });
  return view;
}

const loaded = () => screen.findByText("Mock data", {}, { timeout: 3000 });
const detail = (c: HTMLElement) => c.querySelector(".right-pane .cd-root") as HTMLElement;
const claimEl = (c: HTMLElement, id: string) => c.querySelector(`.left-pane [data-claim-id="${id}"]`) as HTMLElement;

describe("mock flow", () => {
  it("default: selection, detail pane, and navigation", async () => {
    const { container } = await upload(defaultRequest);
    await loaded();
    expect(claimEl(container, "c-supported").classList.contains("selected")).toBe(true);
    expect(container.querySelector(".nav-stepper")).toBeNull();
    const d = detail(container);
    expect(d.getAttribute("data-claim-id")).toBe("c-supported");
    // verdict first, then explanation
    const badge = d.querySelector("header")!.firstElementChild!;
    expect(badge.textContent).toContain("Supported");
    expect(badge.nextElementSibling!.classList.contains("cd-explanation")).toBe(true);

    fireEvent.click(claimEl(container, "c-contradicted"));
    expect(detail(container).getAttribute("data-claim-id")).toBe("c-contradicted");

    fireEvent.click(within(container.querySelector("header")!).getByRole("button", { name: /Partially supported/ }));
    expect(screen.getByText("1 of 1")).toBeTruthy();
    expect(detail(container).getAttribute("data-claim-id")).toBe("c-partial");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("partial: warnings banner and not-processed section", async () => {
    const { container } = await upload(partialRequest, "partial.json");
    await loaded();
    expect(screen.getByRole("status", { name: "Audit warnings" }).textContent).toContain("partial");
    const cards = container.querySelectorAll(".section-card");
    expect(cards).toHaveLength(2);
    expect(within(cards[1] as HTMLElement).getByText("Not processed")).toBeTruthy();
    expect(cards[0].textContent).not.toContain("Not processed");
    expect(claimEl(container, "c-sleep-all")).toBeTruthy();
  });

  it("out-of-range: flagged claim is a chip with a warning, the rest is intact", async () => {
    const { container } = await upload(oorRequest, "oor.json");
    await loaded();
    expect(container.querySelectorAll(".section-text [data-claim-id]")).toHaveLength(2);
    const chip = claimEl(container, "c-bad");
    expect(chip.closest(".unplaced-claims")).toBeTruthy();
    fireEvent.click(chip);
    expect(detail(container).querySelector(".cd-warning")).toBeTruthy();
    expect(container.querySelector(".section-text")!.textContent).toContain("They avoid highways.");
  });

  it("invalid request file: error screen and no network call", async () => {
    await upload("{ not json", "bad.json");
    expect(await screen.findByRole("alert", {}, { timeout: 3000 })).toBeTruthy();
    expect(screen.queryByText("Mock data")).toBeNull();
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
