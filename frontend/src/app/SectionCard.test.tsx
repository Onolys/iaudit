// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { SectionCard } from "./SectionCard";

afterEach(cleanup);

const counts = { supported: 1, partially_supported: 0, contradicted: 0, insufficient_evidence: 0, out_of_scope: 0 };

describe("SectionCard menu", () => {
  it("closes on Escape", () => {
    render(
      <SectionCard label="A" counts={counts} onPick={() => {}}>
        text
      </SectionCard>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Section menu" }));
    expect(screen.getByRole("button", { name: "Section menu" }).getAttribute("aria-expanded")).toBe("true");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.getByRole("button", { name: "Section menu" }).getAttribute("aria-expanded")).toBe("false");
  });
});
