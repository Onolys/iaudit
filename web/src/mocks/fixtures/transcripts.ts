/** Synthetic, non-clinical transcripts (everyday topic). No real sessions. */
import type { components } from "../../api/schema";

export type Turn = components["schemas"]["TranscriptTurn"];

type Spec = [speaker: "spk_0" | "spk_1" | "spk_2", text: string];

function build(specs: Spec[]): Turn[] {
  return specs.map(([speaker, text], i) => ({
    id: `t${i + 1}`,
    speaker,
    role: null,
    start_ms: i * 9000,
    end_ms: i * 9000 + 8000,
    text,
  }));
}

/** spk_0 asks and reflects (the clinician in the fixtures); spk_1 is the client. */
export const sampleTranscript: Turn[] = build([
  ["spk_0", "Thanks for coming in. What would you like to be different about your evenings?"],
  ["spk_1", "I sit on the sofa after work and I'm tired of it. I'd like to start walking more."],
  ["spk_0", "You'd like to walk more in the evenings."],
  ["spk_1", "Yes, but it gets dark early and I'm usually exhausted."],
  ["spk_0", "It's tiring after work, and part of you still wants to get out there."],
  ["spk_1", "I think a short walk around the block would feel good. Maybe three evenings a week."],
  ["spk_0", "What would make three evenings feel doable?"],
  ["spk_1", "Setting out my shoes by the door, and asking my neighbour to join me."],
  ["spk_0", "That's a thoughtful plan, and it's yours to adjust."],
  ["spk_1", "I'll try it this week and see."],
  ["spk_0", "How confident do you feel, from one to ten?"],
  ["spk_1", "About a seven."],
]);

/**
 * Same ids/structure, with astral emoji, a ZWJ family sequence, combining
 * accents and CJK, so code-point offsets differ from UTF-16 offsets (PRD D11).
 */
export const edgeTranscript: Turn[] = build([
  ["spk_0", "Thanks for coming in \u{1F60A} What would you like to be different about your evenings?"],
  ["spk_1", "I sit on the sofa \u{1F629} after work and I'd like to start walking more, maybe to the café with my neighbour \u{1F469}‍\u{1F469}‍\u{1F467}."],
  ["spk_0", "You'd like to walk more \u{1F6B6} in the evenings."],
  ["spk_1", "Yes, but it gets dark early \u{1F319} and I'm usually exhausted — 疲れた."],
  ["spk_0", "It's tiring after work \u{1D4B3}, and part of you still wants to get out there."],
  ["spk_1", "I think a short walk around the block \u{1F333} would feel good. Maybe three evenings a week."],
  ["spk_0", "What would make three evenings \u{1F4C5} feel doable?"],
  ["spk_1", "Setting out my shoes by the door, and asking my neighbour to join me."],
  ["spk_0", "That's a thoughtful plan \u{1F44F} and it's yours to adjust."],
  ["spk_1", "I'll try it this week and see."],
  ["spk_0", "How confident do you feel, from one to ten?"],
  ["spk_1", "About a seven."],
]);

/** Three speakers: spk_2 joins late. The gate lists all three. */
export const threeSpeakerTranscript: Turn[] = (() => {
  const t = sampleTranscript.map((x) => ({ ...x }));
  const extra = build([
    ["spk_2", "Sorry to interrupt. Is this the right room for the group?"],
    ["spk_2", "I'll wait outside until you finish."],
    ["spk_2", "Thanks, I can hear you from the corridor."],
  ]);
  extra.forEach((turn, i) => {
    const n = t.length + i + 1;
    t.push({ ...turn, id: `t${n}`, start_ms: (n - 1) * 9000, end_ms: (n - 1) * 9000 + 8000 });
  });
  return t;
})();

/** Three lines per speaker for the speaker gate (first three of each, in order). */
export function sampleLines(turns: Turn[]): { speaker: string; sample_lines: string[] }[] {
  const order: string[] = [];
  for (const t of turns) if (!order.includes(t.speaker)) order.push(t.speaker);
  return order.map((speaker) => ({
    speaker,
    sample_lines: turns.filter((t) => t.speaker === speaker).slice(0, 3).map((t) => t.text),
  }));
}
