// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Concern } from "../contract";
import { ConcernList } from "./ConcernList";

afterEach(cleanup);

const concerns: Concern[] = [
  { type: "context_stripping", group: "missing_context", explanation: "qualifier", evidence_ids: [] },
  { type: "meaning_shift", group: "changed_detail", explanation: "first changed", evidence_ids: ["e1"] },
  { type: "unsupported_inference", group: "not_in_interview", explanation: "inference", evidence_ids: [] },
  { type: "negation_reversal", group: "opposite_of_interview", explanation: "denial", evidence_ids: [] },
  { type: "calculation_error", group: "changed_detail", explanation: "second changed", evidence_ids: [] },
];

describe("ConcernList groups", () => {
  it("orders groups and keeps concern order and original interaction indices", () => {
    const onToggle = vi.fn();
    render(<ConcernList concerns={concerns} placedIds={new Set(["e1"])} activeIndex={1} onToggle={onToggle} />);
    expect(screen.getAllByRole("heading", { level: 4 }).map(h => h.textContent)).toEqual([
      "Not in interview", "Opposite of interview", "Changed detail", "Missing context",
    ]);
    const changed = screen.getByRole("heading", { name: "Changed detail" }).parentElement!;
    expect(within(changed).getAllByRole("listitem").map(li => li.textContent)).toEqual([
      "Meaning shiftfirst changed", "Calculation errorsecond changed",
    ]);
    const button = within(changed).getByRole("button");
    expect(button.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(button);
    expect(onToggle).toHaveBeenCalledWith(1);
  });
  it("omits empty group headings and keeps concerns without evidence static", () => {
    render(<ConcernList concerns={[concerns[0]]} placedIds={new Set()} activeIndex={null} onToggle={vi.fn()} />);
    expect(screen.getAllByRole("heading", { level: 4 }).map(h => h.textContent)).toEqual(["Missing context"]);
    expect(screen.queryByRole("button")).toBeNull();
  });
  it("omits the section when there are no concerns", () => {
    const { container } = render(<ConcernList concerns={[]} placedIds={new Set()} activeIndex={null} onToggle={vi.fn()} />);
    expect(container.innerHTML).toBe("");
  });
});
