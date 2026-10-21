// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { AuditRequest, Claim } from "../contract";
import { ClaimDetail } from "./ClaimDetail";
import { exampleProps, inlineProps } from "./testData";

afterEach(cleanup);

const turns = (c: HTMLElement) => [...c.querySelectorAll<HTMLElement>(".cd-row")].map((r) => Number(r.dataset.turn));
const span = (si: number, sc: number, ei: number, ec: number) => ({
  start: { index: si, char: sc },
  end: { index: ei, char: ec },
});
const N = 20;
const req: AuditRequest = {
  schema_version: "1.2.0",
  transcript: Array.from({ length: N }, (_, i) => ({ id: `t${i}`, speaker: "S", text: `turn ${i}` })),
  assessment: [{ id: "s", text: "Some assessment text." }],
};
const ev = (id: string, turn: number) => ({ id, role: "supporting" as const, span: span(turn, 0, turn, 6) });
const claimOf = (evidence: Claim["evidence"]): Claim => ({
  id: "c-x",
  span: span(0, 0, 0, 5),
  verdict: "contradicted",
  explanation: "e",
  concerns: [],
  evidence,
});
const btn = (re: RegExp) => screen.queryAllByRole("button", { name: re });

describe("expansion", () => {
  it("never promises more turns than are hidden", () => {
    const { container } = render(<ClaimDetail {...inlineProps(req, claimOf([ev("e1", 1), ev("e2", 18)]))} />);
    expect(turns(container)).toEqual([1, 18]);
    expect(btn(/Show 1 more turn above \(1 hidden\)/)).toHaveLength(1);
    expect(btn(/Show 1 more turn below \(1 hidden\)/)).toHaveLength(1);
  });

  it("shows hidden counts and adds exactly 3 turns per click", () => {
    const { container } = render(<ClaimDetail {...inlineProps(req, claimOf([ev("e1", 10)]))} />);
    expect(turns(container)).toEqual([10]);
    fireEvent.click(screen.getByRole("button", { name: "Show 3 more turns above (10 hidden)" }));
    expect(turns(container)).toEqual([7, 8, 9, 10]);
    expect(container.querySelectorAll(".cd-row.context")).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: "Show 3 more turns below (9 hidden)" }));
    expect(turns(container)).toEqual([7, 8, 9, 10, 11, 12, 13]);
  });

  it("adds fewer than 3 at turn 0 and removes the control at the bound", () => {
    const { container } = render(<ClaimDetail {...inlineProps(req, claimOf([ev("e1", 2)]))} />);
    fireEvent.click(screen.getByRole("button", { name: /above \(2 hidden\)/ }));
    expect(turns(container)).toEqual([0, 1, 2]);
    expect(btn(/above/)).toHaveLength(0);
  });

  it("removes the below control at the last turn", () => {
    const { container } = render(<ClaimDetail {...inlineProps(req, claimOf([ev("e1", N - 2)]))} />);
    fireEvent.click(screen.getByRole("button", { name: /below \(1 hidden\)/ }));
    expect(turns(container)).toEqual([N - 2, N - 1]);
    expect(btn(/below/)).toHaveLength(0);
  });

  it("offers one gap control with both directions between separate groups", () => {
    render(<ClaimDetail {...inlineProps(req, claimOf([ev("e1", 3), ev("e2", 15)]))} />);
    // top edge: above(3); gap: below(11) + above(11); bottom edge: below(4)
    expect(btn(/above/).map((b) => b.textContent)).toEqual([
      "Show 3 more turns above (3 hidden)",
      "Show 3 more turns above (11 hidden)",
    ]);
    expect(btn(/below/).map((b) => b.textContent)).toEqual([
      "Show 3 more turns below (11 hidden)",
      "Show 3 more turns below (4 hidden)",
    ]);
  });

  it("merges neighbouring groups without repeating a turn", () => {
    const { container } = render(<ClaimDetail {...inlineProps(req, claimOf([ev("e1", 5), ev("e2", 9)]))} />);
    fireEvent.click(btn(/below \(3 hidden\)/)[0]); // e1 down: 5..8, touches 9
    const t = turns(container);
    expect(t).toEqual([5, 6, 7, 8, 9]);
    expect(new Set(t).size).toBe(t.length);
    // the gap control is gone; e1's top edge and e2's bottom edge remain
    expect(btn(/below/)).toHaveLength(1);
    expect(btn(/above/)).toHaveLength(1);
  });

  it("c-partial 'above' reveals turns 1 and 0 style context rows without duplicating", () => {
    const { container } = render(<ClaimDetail {...exampleProps("c-partial")} />);
    fireEvent.click(screen.getByRole("button", { name: /above \(2 hidden\)/ }));
    expect(turns(container)).toEqual([0, 1, 2, 3]);
  });

  it("changing claim resets the active concern and expansion", () => {
    const a = exampleProps("c-contradicted");
    const { container, rerender } = render(<ClaimDetail {...a} />);
    fireEvent.click(screen.getAllByRole("button", { name: /Negation reversal/ })[0]);
    fireEvent.click(screen.getByRole("button", { name: /above/ }));
    expect(turns(container)).toEqual([0, 1]);
    const b = exampleProps("c-partial");
    rerender(<ClaimDetail {...b} />);
    rerender(<ClaimDetail {...a} />);
    expect(turns(container)).toEqual([1]);
    expect(container.querySelectorAll(".emphasised, .dimmed")).toHaveLength(0);
    expect(screen.getAllByRole("button", { name: /Negation reversal/ })[0].getAttribute("aria-pressed")).toBe("false");
  });
});

describe("special states", () => {
  it("c-insufficient: no-excerpt message, evidence line, plain-text concern", () => {
    const { container } = render(<ClaimDetail {...exampleProps("c-insufficient")} />);
    expect(screen.getByText("No excerpt in the supplied interview.")).toBeTruthy();
    expect(container.querySelectorAll(".cd-row")).toHaveLength(0);
  });

  it("c-oos: shows the reason and neither concerns nor excerpts", () => {
    const { container } = render(<ClaimDetail {...exampleProps("c-oos")} />);
    expect(screen.getByText("Diagnostic criterion, not a factual claim about the interview.")).toBeTruthy();
    expect(screen.queryByText("Potential concerns")).toBeNull();
    expect(container.querySelector(".cd-excerpts")).toBeNull();
  });

  it("other verdict with only unplaceable evidence: 'No excerpts to show.' plus notice", () => {
    const bad = { id: "e9", role: "contradicting" as const, span: span(99, 0, 99, 3) };
    render(<ClaimDetail {...inlineProps(req, claimOf([bad]))} />);
    expect(screen.getByText("No excerpts to show.")).toBeTruthy();
    expect(screen.getByText(/Excerpt position out of range — Contradicting/)).toBeTruthy();
  });

  it("other verdict with no evidence at all: 'No excerpts to show.'", () => {
    render(<ClaimDetail {...inlineProps(req, claimOf([]))} />);
    expect(screen.getByText("No excerpts to show.")).toBeTruthy();
  });
});
