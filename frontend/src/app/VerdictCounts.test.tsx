// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { VERDICT_STYLE } from "../tokens";
import { VerdictCounts } from "./VerdictCounts";

afterEach(cleanup);

const counts = { supported: 2, partially_supported: 0, contradicted: 1, insufficient_evidence: 0, out_of_scope: 3 };

describe("VerdictCounts", () => {
  it("renders five buttons in verdict order with icon, label and number", () => {
    render(<VerdictCounts counts={counts} active={null} onPick={() => {}} />);
    const buttons = screen.getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual(
      Object.values(VERDICT_STYLE).map((v, i) => `${v.icon}${v.label}${Object.values(counts)[i]}`),
    );
  });

  it("disables zero counts and ignores clicks on them", () => {
    const onPick = vi.fn();
    render(<VerdictCounts counts={counts} active={null} onPick={onPick} />);
    const zero = screen.getByRole("button", { name: /Partially supported/ }) as HTMLButtonElement;
    expect(zero.disabled).toBe(true);
    fireEvent.click(zero);
    expect(onPick).not.toHaveBeenCalled();
  });

  it("picks the verdict on click", () => {
    const onPick = vi.fn();
    render(<VerdictCounts counts={counts} active={null} onPick={onPick} />);
    fireEvent.click(screen.getByRole("button", { name: /Contradicted/ }));
    expect(onPick).toHaveBeenCalledWith("contradicted");
  });

  it("marks only the active verdict as pressed", () => {
    render(<VerdictCounts counts={counts} active="supported" onPick={() => {}} />);
    const pressed = screen.getAllByRole("button").filter((b) => b.getAttribute("aria-pressed") === "true");
    expect(pressed).toHaveLength(1);
    expect(pressed[0].textContent).toContain("Supported");
  });

  it("disables everything when disabled", () => {
    render(<VerdictCounts counts={counts} active={null} onPick={() => {}} disabled />);
    expect(screen.getAllByRole("button").every((b) => (b as HTMLButtonElement).disabled)).toBe(true);
  });
});
