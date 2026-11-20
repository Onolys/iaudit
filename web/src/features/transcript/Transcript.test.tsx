import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Transcript } from "./Transcript";

const turns = [
  { id: "t1", speaker: "spk_0", role: "clinician" as const, start_ms: 65_000, end_ms: 70_000, text: "Hi \u{1F60A} <img src=x onerror=alert(1)> there" },
  { id: "t2", speaker: "spk_1", role: "client" as const, start_ms: 70_000, end_ms: 72_000, text: "café time" },
  { id: "t3", speaker: "spk_2", role: null, start_ms: null, end_ms: null, text: "unspeakered" },
];

describe("Transcript", () => {
  it("renders role labels, m:ss timestamps and text only (no HTML parsing)", () => {
    const { container } = render(<Transcript turns={turns} highlights={[]} selectedId={null} />);
    const items = screen.getAllByRole("listitem");
    expect(within(items[0]).getByText("Clinician")).toBeInTheDocument();
    expect(within(items[0]).getByText("1:05")).toBeInTheDocument();
    expect(within(items[1]).getByText("Client")).toBeInTheDocument();
    expect(within(items[2]).getByText("spk_2")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("<img src=x onerror=alert(1)>");
  });

  it("highlights by code points around emoji and accents", () => {
    const { container } = render(
      <Transcript
        turns={turns}
        highlights={[
          { id: "i1", turn_id: "t1", start: 5, end: 8, quote: "<im" },
          { id: "i2", turn_id: "t2", start: 0, end: 4, quote: "cafe" },
        ]}
        selectedId={null}
      />,
    );
    const marks = [...container.querySelectorAll("mark")].map((m) => m.textContent);
    expect(marks).toEqual(["<im", "cafe"]);
  });

  it("pulses and marks the selected instance", () => {
    const { container } = render(
      <Transcript turns={turns} highlights={[{ id: "i2", turn_id: "t2", start: 0, end: 5, quote: "café" }]} selectedId="i2" />,
    );
    const mark = container.querySelector("mark");
    expect(mark).toHaveClass("pulse");
    expect(mark).toHaveAttribute("data-ids", "i2");
  });

  it("degrades a mismatched quote to an unhighlighted list, and does not throw", () => {
    const { container } = render(
      <Transcript turns={turns} highlights={[{ id: "bad", turn_id: "t2", start: 0, end: 4, quote: "nope" }, { id: "gone", turn_id: "zzz", start: 0, end: 1, quote: "q" }]} selectedId="bad" />,
    );
    expect(container.querySelector("mark")).toBeNull();
    const list = screen.getByRole("list", { name: "Quotes not highlighted" });
    expect(within(list).getByText("nope")).toBeInTheDocument();
    expect(within(list).getByText("q")).toBeInTheDocument();
  });
});
