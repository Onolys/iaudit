// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import App from "./App";
import { ROLE_STYLE, VERDICT_STYLE } from "./tokens";

afterEach(cleanup);

describe("legend", () => {
  it("lists all 5 verdicts with icon and label", () => {
    render(<App />);
    const entries = Object.values(VERDICT_STYLE);
    expect(entries).toHaveLength(5);
    for (const { icon, label } of entries) {
      expect(screen.getByText(label)).toBeTruthy();
      expect(screen.getAllByText(icon).length).toBeGreaterThan(0);
    }
  });

  it("lists the 3 evidence roles", () => {
    render(<App />);
    for (const { label } of Object.values(ROLE_STYLE)) {
      expect(screen.getByText(label)).toBeTruthy();
    }
  });
});
