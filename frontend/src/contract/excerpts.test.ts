import { describe, expect, it } from "vitest";
import { buildChunks } from "./excerpts";

const ex = (id: string, firstTurn: number, lastTurn: number) => ({ id, firstTurn, lastTurn });
const turnsOf = (chunks: ReturnType<typeof buildChunks>) =>
  chunks.flatMap((c) => c.rows.map((r) => r.turn));

describe("buildChunks", () => {
  it("separate excerpts give separate chunks with hidden counts", () => {
    const c = buildChunks({ transcriptLength: 30, excerpts: [ex("a", 2, 2), ex("b", 20, 21)], expansion: {} });
    expect(c.map((x) => [x.startTurn, x.endTurn])).toEqual([[2, 2], [20, 21]]);
    expect(c[0]).toMatchObject({ hiddenAbove: 2, hiddenBelow: 17, topExcerptId: "a", bottomExcerptId: "a" });
    expect(c[1]).toMatchObject({ hiddenAbove: 17, hiddenBelow: 8, topExcerptId: "b", bottomExcerptId: "b" });
    expect(c[0].rows).toEqual([{ turn: 2, highlights: [{ excerptId: "a", from: 2, to: 2 }] }]);
  });
  it("touching ranges merge", () => {
    const c = buildChunks({ transcriptLength: 10, excerpts: [ex("a", 1, 2), ex("b", 3, 4)], expansion: {} });
    expect(c).toHaveLength(1);
    expect(turnsOf(c)).toEqual([1, 2, 3, 4]);
    expect(c[0]).toMatchObject({ topExcerptId: "a", bottomExcerptId: "b" });
  });
  it("overlapping ranges merge, shared turn carries both highlights", () => {
    const c = buildChunks({ transcriptLength: 10, excerpts: [ex("a", 1, 3), ex("b", 3, 5)], expansion: {} });
    expect(c).toHaveLength(1);
    expect(turnsOf(c)).toEqual([1, 2, 3, 4, 5]);
    expect(c[0].rows.find((r) => r.turn === 3)!.highlights.map((h) => h.excerptId)).toEqual(["a", "b"]);
    expect(c[0].rows.find((r) => r.turn === 2)!.highlights.map((h) => h.excerptId)).toEqual(["a"]);
  });
  it("expansion adds 3 turns per click and clamps at both ends", () => {
    const one = buildChunks({ transcriptLength: 20, excerpts: [ex("a", 10, 10)], expansion: { a: { up: 1, down: 1 } } });
    expect([one[0].startTurn, one[0].endTurn]).toEqual([7, 13]);
    expect(one[0].rows.filter((r) => r.highlights.length === 0)).toHaveLength(6);
    const clamped = buildChunks({ transcriptLength: 20, excerpts: [ex("a", 1, 1)], expansion: { a: { up: 5, down: 99 } } });
    expect([clamped[0].startTurn, clamped[0].endTurn]).toEqual([0, 19]);
    expect(clamped[0]).toMatchObject({ hiddenAbove: 0, hiddenBelow: 0 });
  });
  it("expansion can make chunks touch and merge", () => {
    const c = buildChunks({
      transcriptLength: 30,
      excerpts: [ex("a", 2, 2), ex("b", 10, 10)],
      expansion: { a: { up: 0, down: 2 }, b: { up: 1, down: 0 } },
    });
    expect(c).toHaveLength(1);
    expect(new Set(turnsOf(c)).size).toBe(turnsOf(c).length);
  });
  it("never repeats a turn", () => {
    const c = buildChunks({
      transcriptLength: 12,
      excerpts: [ex("a", 2, 4), ex("b", 4, 6), ex("c", 9, 9)],
      expansion: { b: { up: 1, down: 1 } },
    });
    const t = turnsOf(c);
    expect(new Set(t).size).toBe(t.length);
  });
  it("returns nothing for no excerpts", () => {
    expect(buildChunks({ transcriptLength: 5, excerpts: [], expansion: {} })).toEqual([]);
  });
});
