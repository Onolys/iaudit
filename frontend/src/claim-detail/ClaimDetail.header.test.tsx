// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { CONCERN_TYPES } from "../contract";
import { VERDICT_STYLE } from "../tokens";
import { ClaimDetail } from "./ClaimDetail";
import { CONCERN_LABELS, concernLabel } from "./concernLabels";
import { exampleProps } from "./testData";

afterEach(cleanup);

describe("header", () => {
  it("renders badge, explanation, suggestion, concerns in order for c-contradicted", () => {
    const props = exampleProps("c-contradicted");
    const { container } = render(<ClaimDetail {...props} />);
    const html = container.innerHTML;
    const at = (s: string) => html.indexOf(s);
    const order = [
      at("Contradicted"),
      at("The respondent denied losing keys."),
      at("Suggestion — not applied"),
      at("Potential concerns"),
    ];
    expect(order.every((n) => n >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
  });

  it("badge shows icon and label", () => {
    render(<ClaimDetail {...exampleProps("c-contradicted")} />);
    expect(screen.getByText(VERDICT_STYLE.contradicted.icon)).toBeTruthy();
    expect(screen.getByText(VERDICT_STYLE.contradicted.label)).toBeTruthy();
  });

  it("shows the insufficient-evidence line only for that verdict", () => {
    const { unmount } = render(<ClaimDetail {...exampleProps("c-insufficient")} />);
    expect(screen.getByText(/This is not the same as contradicted\./)).toBeTruthy();
    unmount();
    render(<ClaimDetail {...exampleProps("c-contradicted")} />);
    expect(screen.queryByText(/not the same as contradicted/)).toBeNull();
  });

  it("shows the warning strip when a position is out of range", () => {
    const props = exampleProps("c-contradicted");
    render(<ClaimDetail {...props} check={{ ...props.check, spanOutOfRange: true }} />);
    expect(screen.getByRole("alert").textContent).toMatch(/does not fit the supplied input/);
  });
});

describe("suggestion", () => {
  it("is present with the heading and no button", () => {
    render(<ClaimDetail {...exampleProps("c-contradicted")} />);
    const box = screen.getByLabelText("Suggestion");
    expect(box.textContent).toContain("Suggestion — not applied");
    expect(box.textContent).toContain("The patient denied losing keys.");
    expect(box.querySelectorAll("button")).toHaveLength(0);
  });

  it("is absent when null", () => {
    render(<ClaimDetail {...exampleProps("c-supported")} />);
    expect(screen.queryByText("Suggestion — not applied")).toBeNull();
  });
});

describe("concerns", () => {
  it("labels all 12 mission checks and falls back to the raw value", () => {
    expect(Object.keys(CONCERN_LABELS)).toEqual([...CONCERN_TYPES]);
    expect(new Set(Object.values(CONCERN_LABELS)).size).toBe(12);
    expect(concernLabel("something_new")).toBe("something_new");
  });

  it("renders a toggle button for a concern that cites a placed excerpt", () => {
    render(<ClaimDetail {...exampleProps("c-contradicted")} />);
    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(2);
    expect(buttons[0].textContent).toContain("Negation reversal");
    expect(buttons[0].getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(buttons[0]);
    expect(buttons[0].getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(buttons[1]);
    expect(buttons[0].getAttribute("aria-pressed")).toBe("false");
    expect(buttons[1].getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(buttons[1]);
    expect(buttons[1].getAttribute("aria-pressed")).toBe("false");
  });

  it("renders a concern with no evidence as plain text", () => {
    render(<ClaimDetail {...exampleProps("c-insufficient")} />);
    expect(screen.getByText("Claim support")).toBeTruthy();
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });

  it("renders a concern citing only dangling or unplaceable ids as plain text", () => {
    const props = exampleProps("c-contradicted");
    const claim = {
      ...props.claim,
      concerns: [{ type: "negation_reversal" as const, explanation: "x", evidence_ids: ["nope", "e-denial"] }],
    };
    render(<ClaimDetail {...props} claim={claim} check={{ ...props.check, evidence: { "e-denial": false } }} />);
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });

  it("is omitted when there are no concerns", () => {
    render(<ClaimDetail {...exampleProps("c-supported")} />);
    expect(screen.queryByText("Potential concerns")).toBeNull();
  });
});

describe("text safety", () => {
  it("never uses dangerouslySetInnerHTML in claim-detail/", () => {
    const needle = ["dangerously", "SetInnerHTML"].join("");
    for (const f of readdirSync(__dirname)) {
      if (f.endsWith(".test.tsx") || f.endsWith(".test.ts")) continue;
      expect(readFileSync(join(__dirname, f), "utf8").includes(needle), f).toBe(false);
    }
  });
});
