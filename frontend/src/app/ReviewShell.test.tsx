// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { analyzeResponse } from "../contract";
import type { AuditRequest, AuditResponse, Claim } from "../contract";
import type { LoadResult } from "../transport";
import { VERDICT_STYLE, selectedClaimBackground } from "../tokens";
import { ReviewShell } from "./ReviewShell";

import exampleRequest from "@contracts/examples/request.json";
import exampleResponse from "@contracts/examples/response.json";

afterEach(cleanup);

const headerProps = { mock: false, inputRef: { current: null }, onFile: () => {} };

const build = (request: AuditRequest, response: AuditResponse): LoadResult => ({
  ok: true,
  request,
  response,
  analysis: analyzeResponse(request, response),
  source: "service",
});
const mount = (r: LoadResult) => render(<ReviewShell result={r} headerProps={headerProps} />);

const example = () => build(exampleRequest as AuditRequest, exampleResponse as AuditResponse);

const claim = (id: string, verdict: Claim["verdict"], index: number, start: number, end: number): Claim => ({
  id,
  verdict,
  explanation: `why ${id}`,
  concerns: [],
  evidence: [],
  span: { start: { index, char: start }, end: { index, char: end } },
});

const request: AuditRequest = {
  schema_version: "1.1.0",
  transcript: [{ id: "t0", speaker: "A", text: "hello" }],
  assessment: [
    { id: "s0", label: "Alpha", score: 2, text: "one two three four" },
    { id: "s1", text: "five six seven" },
    { id: "s2", label: "Gamma", text: "eight nine" },
  ],
};
const multi = (claims: Claim[], warnings: AuditResponse["warnings"] = []) =>
  build(request, { schema_version: "1.1.0", status: "complete", warnings, claims });

const claimEl = (c: HTMLElement, id: string) => c.querySelector(`.left-pane [data-claim-id="${id}"]`) as HTMLElement;

describe("left pane text and claims", () => {
  it("section textContent equals the supplied text, with underlined claims", () => {
    const { container } = mount(example());
    const body = container.querySelector(".section-text")!;
    expect(body.textContent).toBe((exampleRequest as AuditRequest).assessment[0].text);
    const spans = container.querySelectorAll(".left-pane [data-claim-id]");
    expect(spans).toHaveLength(5);
  });

  it("each claim carries verdict colour, style and title", () => {
    const { container } = mount(example());
    const cases: [string, keyof typeof VERDICT_STYLE][] = [
      ["c-supported", "supported"],
      ["c-insufficient", "insufficient_evidence"],
      ["c-oos", "out_of_scope"],
    ];
    for (const [id, verdict] of cases) {
      const el = claimEl(container, id);
      expect(el.getAttribute("role")).toBe("button");
      expect(el.getAttribute("tabindex")).toBe("0");
      expect(el.title).toBe(VERDICT_STYLE[verdict].label);
      expect(el.style.textDecorationStyle).toBe(VERDICT_STYLE[verdict].underline);
    }
  });

  it("selects the first claim initially, with the neutral background and no stepper", () => {
    const { container } = mount(example());
    expect(claimEl(container, "c-supported").style.backgroundColor).not.toBe("");
    expect(claimEl(container, "c-supported").classList.contains("selected")).toBe(true);
    expect(claimEl(container, "c-contradicted").classList.contains("selected")).toBe(false);
    expect(screen.queryByText(/ of \d+/)).toBeNull();
    expect(selectedClaimBackground).toBeTruthy();
  });

  it("clicking, Enter and Space select a claim", () => {
    const { container } = mount(example());
    fireEvent.click(claimEl(container, "c-oos"));
    expect(claimEl(container, "c-oos").classList.contains("selected")).toBe(true);
    fireEvent.keyDown(claimEl(container, "c-partial"), { key: "Enter" });
    expect(claimEl(container, "c-partial").classList.contains("selected")).toBe(true);
    fireEvent.keyDown(claimEl(container, "c-insufficient"), { key: " " });
    expect(claimEl(container, "c-insufficient").classList.contains("selected")).toBe(true);
  });
});

describe("right pane", () => {
  it("shows ClaimDetail of the selected claim", () => {
    const { container } = mount(example());
    expect(container.querySelector(".right-pane .cd-root")!.getAttribute("data-claim-id")).toBe("c-supported");
    fireEvent.click(claimEl(container, "c-contradicted"));
    expect(container.querySelector(".right-pane .cd-root")!.getAttribute("data-claim-id")).toBe("c-contradicted");
  });

  it("says so when the audit has no claims", () => {
    const { container } = mount(multi([]));
    expect(screen.getByText("This audit contains no claims.")).toBeTruthy();
    expect(container.querySelector(".section-text")!.textContent).toBe("one two three four");
  });
});

describe("navigation", () => {
  it("header count selects the first claim and shows the stepper", () => {
    const r = multi([
      claim("a", "supported", 0, 0, 3),
      claim("b", "contradicted", 0, 4, 7),
      claim("c", "supported", 1, 0, 4),
    ]);
    const { container } = mount(r);
    fireEvent.click(within(container.querySelector("header")!).getByRole("button", { name: /Supported/ }));
    expect(screen.getByText("1 of 2")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Next claim" }));
    expect(screen.getByText("2 of 2")).toBeTruthy();
    expect(claimEl(container, "c").classList.contains("selected")).toBe(true);
    expect((screen.getByRole("button", { name: "Next claim" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Previous claim" }));
    expect(claimEl(container, "a").classList.contains("selected")).toBe(true);
    expect((screen.getByRole("button", { name: "Previous claim" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("a click on a claim outside the list clears the stepper", () => {
    const r = multi([claim("a", "supported", 0, 0, 3), claim("b", "contradicted", 0, 4, 7)]);
    const { container } = mount(r);
    fireEvent.click(within(container.querySelector("header")!).getByRole("button", { name: /Supported/ }));
    expect(screen.getByText("1 of 1")).toBeTruthy();
    fireEvent.click(claimEl(container, "b"));
    expect(screen.queryByText("1 of 1")).toBeNull();
  });

  it("section menu uses section scope and closes on pick", () => {
    const r = multi([claim("a", "supported", 0, 0, 3), claim("c", "supported", 1, 0, 4)]);
    const { container } = mount(r);
    const cards = container.querySelectorAll(".section-card");
    fireEvent.click(within(cards[1] as HTMLElement).getByRole("button", { name: "Section menu" }));
    const menu = container.querySelector(".section-menu") as HTMLElement;
    fireEvent.click(within(menu).getByRole("button", { name: /Supported/ }));
    expect(container.querySelector(".section-menu")).toBeNull();
    expect(screen.getByText("1 of 1")).toBeTruthy();
    expect(claimEl(container, "c").classList.contains("selected")).toBe(true);
  });

  it("section menu closes on outside click", () => {
    const { container } = mount(multi([claim("a", "supported", 0, 0, 3)]));
    fireEvent.click(within(container.querySelector(".section-card") as HTMLElement).getByRole("button", { name: "Section menu" }));
    expect(container.querySelector(".section-menu")).toBeTruthy();
    fireEvent.mouseDown(document.body);
    expect(container.querySelector(".section-menu")).toBeNull();
  });
});

describe("section cards", () => {
  it("shows label with fallback and a neutral score chip only when supplied", () => {
    const { container } = mount(multi([]));
    const heads = [...container.querySelectorAll(".section-header")];
    expect(heads[0].textContent).toContain("Alpha");
    expect(heads[1].textContent).toContain("Section 2");
    expect(heads[2].textContent).toContain("Gamma");
    const chip = heads[0].querySelector(".score-chip") as HTMLElement;
    expect(chip.textContent).toBe("Score 2");
    expect(chip.title).toBe("Display only, not an audit result");
    expect(heads[1].querySelector(".score-chip")).toBeNull();
  });

  it("marks not-processed sections and disables their counts but still renders claims", () => {
    const r = multi(
      [claim("a", "supported", 1, 0, 4)],
      [{ code: "section_not_processed", message: "skipped", section_index: 1 }],
    );
    const { container } = mount(r);
    const card = container.querySelectorAll(".section-card")[1] as HTMLElement;
    expect(within(card).getByText("Not processed")).toBeTruthy();
    expect(container.querySelectorAll(".section-card")[0].textContent).not.toContain("Not processed");
    fireEvent.click(within(card).getByRole("button", { name: "Section menu" }));
    const counts = within(container.querySelector(".section-menu") as HTMLElement).getAllByRole("button");
    expect(counts.every((b) => (b as HTMLButtonElement).disabled)).toBe(true);
    expect(claimEl(container, "a")).toBeTruthy();
  });
});

describe("unplaced claims", () => {
  it("shows a bad-span claim as a selectable chip, not underlined, and passes claimSpanOk=false", () => {
    const r = multi([claim("good", "supported", 0, 0, 3), claim("bad", "contradicted", 0, 10, 999)]);
    const { container } = mount(r);
    expect(claimEl(container, "bad").tagName).toBe("BUTTON");
    expect(claimEl(container, "bad").closest(".unplaced-claims")).toBeTruthy();
    expect(container.querySelector(".section-text")!.textContent).toBe("one two three four");
    expect(container.querySelectorAll(".section-text [data-claim-id]")).toHaveLength(1);
    expect(claimEl(container, "bad").textContent).toContain("bad");
    expect(claimEl(container, "bad").textContent).toContain("position doesn't fit the supplied text");
    fireEvent.click(claimEl(container, "bad"));
    expect(claimEl(container, "bad").classList.contains("selected")).toBe(true);
    expect(container.querySelector(".right-pane .cd-root")!.getAttribute("data-claim-id")).toBe("bad");
    expect(container.querySelector(".right-pane .cd-warning")).toBeTruthy();
  });

  it("puts claims for a missing section in a trailing card", () => {
    const r = multi([claim("lost", "supported", 7, 0, 3)]);
    const { container } = mount(r);
    const cards = container.querySelectorAll(".section-card");
    expect(cards).toHaveLength(4);
    expect(cards[3].textContent).toContain("Claims outside the supplied assessment");
    expect(within(cards[3] as HTMLElement).getByText(/lost/)).toBeTruthy();
  });
});

describe("scrolling", () => {
  it("scrolls on navigation and stepping, not on direct clicks", () => {
    const spy = vi.fn();
    Element.prototype.scrollIntoView = spy;
    const r = multi([claim("a", "supported", 0, 0, 3), claim("b", "supported", 0, 4, 7), claim("c", "contradicted", 1, 0, 4)]);
    const { container } = mount(r);
    fireEvent.click(claimEl(container, "c"));
    expect(spy).not.toHaveBeenCalled();
    fireEvent.click(within(container.querySelector("header")!).getByRole("button", { name: /Supported/ }));
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy.mock.contexts[0]).toBe(claimEl(container, "a"));
    fireEvent.click(screen.getByRole("button", { name: "Next claim" }));
    expect(spy).toHaveBeenCalledTimes(2);
    expect(spy.mock.contexts[1]).toBe(claimEl(container, "b"));
    fireEvent.click(claimEl(container, "c"));
    expect(spy).toHaveBeenCalledTimes(2);
    delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView;
  });
});

describe("menu stacking", () => {
  it("raises the owning card while its menu is open", () => {
    const { container } = mount(multi([claim("a", "supported", 0, 0, 3)]));
    const card = container.querySelector(".section-card")!;
    fireEvent.click(within(card as HTMLElement).getByRole("button", { name: "Section menu" }));
    expect(card.classList.contains("menu-open")).toBe(true);
  });
});

describe("run_info", () => {
  it("renders identically with and without run_info", () => {
    const withInfo = exampleResponse as AuditResponse;
    expect(withInfo.run_info).toBeDefined();
    const { run_info: _omit, ...rest } = withInfo;
    const a = mount(build(exampleRequest as AuditRequest, withInfo));
    const htmlWith = a.container.innerHTML;
    cleanup();
    const b = mount(build(exampleRequest as AuditRequest, rest as AuditResponse));
    expect(b.container.innerHTML).toBe(htmlWith);
  });
});
