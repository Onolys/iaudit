export interface ExcerptInput {
  id: string;
  firstTurn: number;
  lastTurn: number;
}

export interface Expansion {
  up: number;
  down: number;
}

export interface ChunkRow {
  turn: number;
  /** from/to = the excerpt's turn range; [] = context row. */
  highlights: { excerptId: string; from: number; to: number }[];
}

export interface Chunk {
  startTurn: number;
  endTurn: number;
  rows: ChunkRow[];
  topExcerptId: string;
  bottomExcerptId: string;
  hiddenAbove: number;
  hiddenBelow: number;
}

export interface ChunkInput {
  transcriptLength: number;
  excerpts: ExcerptInput[];
  expansion: Record<string, Expansion>;
  step?: number;
}

interface Visible {
  ex: ExcerptInput;
  start: number;
  end: number;
}

export function buildChunks({ transcriptLength, excerpts, expansion, step = 3 }: ChunkInput): Chunk[] {
  const last = transcriptLength - 1;
  const visible: Visible[] = excerpts
    .map((ex) => {
      const { up = 0, down = 0 } = expansion[ex.id] ?? {};
      return {
        ex,
        start: Math.max(0, ex.firstTurn - step * up),
        end: Math.min(last, ex.lastTurn + step * down),
      };
    })
    .sort((a, b) => a.start - b.start || a.end - b.end);

  const groups: Visible[][] = [];
  let groupEnd = -Infinity;
  for (const v of visible) {
    if (groups.length > 0 && v.start <= groupEnd + 1) {
      groups[groups.length - 1].push(v);
      groupEnd = Math.max(groupEnd, v.end);
    } else {
      groups.push([v]);
      groupEnd = v.end;
    }
  }

  const bounds = groups.map((g) => ({
    start: g[0].start,
    end: Math.max(...g.map((v) => v.end)),
  }));

  return groups.map((g, i) => {
    const { start, end } = bounds[i];
    const rows: ChunkRow[] = [];
    for (let turn = start; turn <= end; turn++) {
      rows.push({
        turn,
        highlights: g
          .filter((v) => turn >= v.ex.firstTurn && turn <= v.ex.lastTurn)
          .map((v) => ({ excerptId: v.ex.id, from: v.ex.firstTurn, to: v.ex.lastTurn })),
      });
    }
    const bottom = g.reduce((best, v) => (v.end > best.end ? v : best), g[0]);
    return {
      startTurn: start,
      endTurn: end,
      rows,
      topExcerptId: g[0].ex.id,
      bottomExcerptId: bottom.ex.id,
      hiddenAbove: start - (i === 0 ? 0 : bounds[i - 1].end + 1),
      hiddenBelow: (i === groups.length - 1 ? last + 1 : bounds[i + 1].start) - (end + 1),
    };
  });
}
