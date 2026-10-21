// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it } from "vitest";
import { GoldPanel } from "./GoldPanel";
import { readFileSync } from "node:fs";
const goldStyles = readFileSync("src/eval/gold/gold.css", "utf8");

const gold = {
  summary: "inconsistent",
  sentences: [
    { sent_idx: 2, text: "Alex booked a visit.", label: "consistent", types: [], exp: "A fictional supported sentence.", start: 0, end: 19 },
    { sent_idx: 5, text: "Jordan cancelled every visit.", label: "inconsistent", types: ["Contradiction", "Nuanced Meaning Shift"], exp: "A fictional explanation: <script>ignored</script>.", start: 20, end: 49 },
  ],
};
// Vitest omits CSS side-effect imports; apply the actual stylesheet for layout limits.
let stylesheet: HTMLStyleElement;
beforeEach(() => {
  stylesheet = document.createElement("style");
  stylesheet.textContent = goldStyles;
  document.head.appendChild(stylesheet);
});
afterEach(() => { cleanup(); stylesheet.remove(); });
it("renders native sentence indices, labels, types and explanations without filling gaps", () => {
  render(<GoldPanel goldKind="tofueval_summary_sentences" gold={gold} />);
  expect(screen.getByText("Summary: inconsistent")).toBeTruthy();
  expect(screen.getByRole("heading", {name:"Sentence 2"})).toBeTruthy();
  const sentence = screen.getByRole("heading", {name:"Sentence 5"}).closest("li")!;
  for(const text of ["Jordan cancelled every visit.","inconsistent","Contradiction, Nuanced Meaning Shift","A fictional explanation: <script>ignored</script>."]) expect(within(sentence).getByText(text)).toBeTruthy();
  expect(screen.queryByRole("heading",{name:"Sentence 3"})).toBeNull();
  expect(document.querySelector("script")).toBeNull();
});
it("starts known gold expanded, allows collapse and limits its scrolling area", () => {
  const {container}=render(<GoldPanel goldKind="tofueval_summary_sentences" gold={gold} />);
  const details=container.querySelector("details")!;
  expect(details.open).toBe(true);
  fireEvent.click(within(details).getByText("Gold")); expect(details.open).toBe(false);
  fireEvent.click(within(details).getByText("Gold")); expect(details.open).toBe(true);
  const style=getComputedStyle(details);
  expect(parseFloat(style.maxHeight)).toBeCloseTo(window.innerHeight * 0.3);expect(style.overflow).toBe("auto");
});
it.each(["unknown", "toString", "__proto__"])("uses collapsed pretty JSON for unregistered kind %s", goldKind => {
  const {container}=render(<GoldPanel goldKind={goldKind} gold={{custom:["native"],missing:null}} />);
  const details=container.querySelector("details")!;
  expect(details.open).toBe(false);expect(container.querySelector("pre")!.textContent).toBe('{\n  "custom": [\n    "native"\n  ],\n  "missing": null\n}');
  fireEvent.click(within(details).getByText("Gold (JSON)"));expect(details.open).toBe(true);
});
it.each([
  null,
  { ...gold, summary:"yes" },
  { ...gold, sentences:null },
  { ...gold, sentences:[{...gold.sentences[0],label:"yes"}] },
  { ...gold, sentences:[{...gold.sentences[0],types:[1]}] },
  { ...gold, sentences:[{...gold.sentences[0],exp:null}] },
  { ...gold, sentences:[{...gold.sentences[0],sent_idx:1.5}] },
  { ...gold, sentences:[{...gold.sentences[0],end:-1}] },
  { ...gold, sentences:[{...gold.sentences[0],start:undefined}] },
])("falls back for malformed known gold without inferring annotations: %j", value => {
  const {container}=render(<GoldPanel goldKind="tofueval_summary_sentences" gold={value} />);
  expect(container.querySelector("details")!.open).toBe(false);expect(screen.getByText("Gold (JSON)")).toBeTruthy();
  expect(screen.queryByRole("heading",{name:/Sentence/})).toBeNull();
});
it("renders supplied summary for an empty sentence array without inventing a label",()=>{
  render(<GoldPanel goldKind="tofueval_summary_sentences" gold={{summary:"inconsistent",sentences:[]}}/>);
  expect(screen.getByText("Summary: inconsistent")).toBeTruthy();expect(screen.queryAllByRole("listitem")).toHaveLength(0);
});
