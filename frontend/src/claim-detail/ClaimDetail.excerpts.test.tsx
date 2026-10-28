// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { AuditRequest, Claim } from "../contract";
import { ClaimDetail } from "./ClaimDetail";
import { partsForTurn } from "./excerptModel";
import { exampleProps, inlineProps } from "./testData";

afterEach(cleanup);

const rows = (c: HTMLElement) => [...c.querySelectorAll<HTMLElement>(".cd-row")];
const turns = (c: HTMLElement) => rows(c).map((r) => Number(r.dataset.turn));

const span = (si: number, sc: number, ei: number, ec: number) => ({
  start: { index: si, char: sc },
  end: { index: ei, char: ec },
});
const claimOf = (evidence: Claim["evidence"], over: Partial<Claim> = {}): Claim => ({
  id: "c-x",
  span: span(0, 0, 0, 5),
  verdict: "contradicted",
  explanation: "e",
  concerns: [],
  evidence,
  ...over,
});
const LONG = "0123456789".repeat(6); // 60 code points
const req: AuditRequest = {
  schema_version: "0.0.1",
  transcript: [
    { id: "a", speaker: "A", role: "interviewer", text: "first", timestamp: "00:00:01" },
    { id: "b", speaker: "B", text: LONG },
    { id: "c", speaker: "C", role: "respondent", text: "" },
    { id: "d", speaker: "D", text: "last turn" },
  ],
  assessment: [{ id: "s", text: "Some assessment text." }],
};

describe("partsForTurn", () => {
  it("splits at boundaries and marks overlap and dim", () => {
    expect(partsForTurn(10, [{ from: 0, to: 6 }, { from: 4, to: 8 }])).toEqual([
      { from: 0, to: 4, kind: "highlight" },
      { from: 4, to: 6, kind: "overlap" },
      { from: 6, to: 8, kind: "highlight" },
      { from: 8, to: 10, kind: "dim" },
    ]);
    expect(partsForTurn(5, [])).toEqual([{ from: 0, to: 5, kind: "plain" }]);
  });
});

describe("excerpts", () => {
  it("c-contradicted shows its one Contradicting excerpt (turn 1) with note", () => {
    const { container } = render(<ClaimDetail {...exampleProps("c-contradicted")} />);
    expect(turns(container)).toEqual([1]);
    expect(screen.getByText("Contradicting")).toBeTruthy();
    expect(container.querySelector(".cd-highlight")!.textContent).toBe("No. I don't lose my keys.");
    expect(screen.getByText(/Audit note \(paraphrase, not a quote\): The respondent's answer/)).toBeTruthy();
  });

  it("orders excerpts by transcript position even when evidence is reversed", () => {
    const props = exampleProps("c-supported");
    const claim = { ...props.claim, evidence: [...props.claim.evidence].reverse() };
    const { container } = render(<ClaimDetail {...props} claim={claim} />);
    expect(turns(container)).toEqual([4, 5]);
  });

  it("c-partial renders turns 2-3 as one excerpt with one chip", () => {
    const { container } = render(<ClaimDetail {...exampleProps("c-partial")} />);
    expect(turns(container)).toEqual([2, 3]);
    expect(screen.getAllByText("Qualifying")).toHaveLength(1);
    expect(container.querySelectorAll(".cd-dim")).toHaveLength(0);
  });

  it("highlights the exact span and dims the rest of the turn", () => {
    const ev = { id: "e1", role: "supporting" as const, span: span(1, 0, 2, 0) };
    const hl = { ...ev, span: span(1, 5, 1, 45) };
    const { container } = render(<ClaimDetail {...inlineProps(req, claimOf([hl]))} />);
    expect(container.querySelector(".cd-highlight")!.textContent).toBe(LONG.slice(5, 45));
    const dims = [...container.querySelectorAll(".cd-dim")].map((d) => d.textContent);
    expect(dims).toEqual([LONG.slice(0, 5), LONG.slice(45)]);
  });

  it("shows timestamp verbatim, else #index, and speaker with optional role", () => {
    const e = { id: "e1", role: "supporting" as const, span: span(0, 0, 1, 3) };
    const { container } = render(<ClaimDetail {...inlineProps(req, claimOf([e]))} />);
    const [r0, r1] = rows(container);
    expect(r0.textContent).toContain("A · interviewer");
    expect(r0.textContent).toContain("00:00:01");
    expect(r1.textContent).toContain("#1");
    expect(r1.textContent).not.toContain(" · ");
  });

  it("shows (empty turn) for an empty turn inside an excerpt", () => {
    const e = { id: "e1", role: "qualifying" as const, span: span(1, 50, 3, 4) };
    render(<ClaimDetail {...inlineProps(req, claimOf([e]))} />);
    expect(screen.getByText("(empty turn)")).toBeTruthy();
  });

  it("two excerpts sharing a turn: one row, neutral overlap, both chips, first role border", () => {
    const e1 = { id: "e1", role: "supporting" as const, span: span(1, 0, 1, 30) };
    const e2 = { id: "e2", role: "contradicting" as const, span: span(1, 20, 1, 50) };
    const { container } = render(<ClaimDetail {...inlineProps(req, claimOf([e2, e1]))} />);
    expect(turns(container)).toEqual([1]);
    expect(container.querySelector(".cd-overlap")!.textContent).toBe(LONG.slice(20, 30));
    expect(screen.getByText("Supporting")).toBeTruthy();
    expect(screen.getByText("Contradicting")).toBeTruthy();
    expect(rows(container)[0].style.borderLeftColor).toBeTruthy();
  });

  it("clicking a concern emphasises cited excerpts, dims others, and a second click clears", () => {
    const e1 = { id: "e1", role: "supporting" as const, span: span(0, 0, 0, 5) };
    const e2 = { id: "e2", role: "contradicting" as const, span: span(3, 0, 3, 9) };
    const claim = claimOf([e1, e2], {
      concerns: [{ type: "negation_reversal", explanation: "why", evidence_ids: ["e2"] }],
    });
    const { container } = render(<ClaimDetail {...inlineProps(req, claim)} />);
    const btn = screen.getByRole("button", { name: /Negation reversal/ });
    fireEvent.click(btn);
    const [r0, r3] = rows(container);
    expect(r3.classList.contains("emphasised")).toBe(true);
    expect(r0.classList.contains("dimmed")).toBe(true);
    fireEvent.click(btn);
    expect(container.querySelectorAll(".emphasised, .dimmed")).toHaveLength(0);
  });

  it("out-of-range evidence becomes a one-line notice and does not throw", () => {
    const ok = { id: "e1", role: "supporting" as const, span: span(0, 0, 0, 5) };
    const bad = { id: "e2", role: "qualifying" as const, span: span(9, 0, 9, 4), note: "n" };
    const props = inlineProps(req, claimOf([ok, bad]));
    expect(props.check.spanOutOfRange).toBe(true);
    const { container } = render(<ClaimDetail {...props} />);
    expect(turns(container)).toEqual([0]);
    expect(screen.getByText(/Excerpt position out of range — Qualifying — n/)).toBeTruthy();
    expect(screen.getByRole("alert")).toBeTruthy();
  });

  it("ignores later evidence that reuses an id (different turns) without throwing", () => {
    const a = { id: "dup", role: "supporting" as const, span: span(0, 0, 0, 5) };
    const b = { id: "dup", role: "contradicting" as const, span: span(3, 0, 3, 9) };
    const { container } = render(<ClaimDetail {...inlineProps(req, claimOf([b, a]))} />);
    expect(turns(container)).toEqual([0]);
    expect(screen.getAllByText("Supporting")).toHaveLength(1);
    expect(screen.queryByText("Contradicting")).toBeNull();
  });

  it("ignores a duplicate id within the same turn", () => {
    const a = { id: "dup", role: "supporting" as const, span: span(1, 0, 1, 10) };
    const b = { id: "dup", role: "qualifying" as const, span: span(1, 0, 1, 10) };
    const { container } = render(<ClaimDetail {...inlineProps(req, claimOf([a, b]))} />);
    expect(container.querySelectorAll(".cd-overlap")).toHaveLength(0);
    expect(screen.getAllByText("Supporting")).toHaveLength(1);
  });
});
