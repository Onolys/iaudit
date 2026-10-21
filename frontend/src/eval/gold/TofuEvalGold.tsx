import { GenericGold } from "./GenericGold";

type NativeLabel = "consistent" | "inconsistent";
interface GoldSentence {
  sent_idx: number;
  text: string;
  label: NativeLabel;
  types: string[];
  exp: string;
  start: number;
  end: number;
}
interface TofuGold { summary: NativeLabel; sentences: GoldSentence[] }
const record = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const label = (value: unknown): value is NativeLabel => value === "consistent" || value === "inconsistent";
const index = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
function isTofuGold(gold: unknown): gold is TofuGold {
  return record(gold) && label(gold.summary) && Array.isArray(gold.sentences) && gold.sentences.every(sentence =>
    record(sentence) && index(sentence.sent_idx) && typeof sentence.text === "string" && label(sentence.label)
    && Array.isArray(sentence.types) && sentence.types.every(type => typeof type === "string")
    && typeof sentence.exp === "string" && index(sentence.start) && index(sentence.end) && sentence.end >= sentence.start);
}

/** C2 labels and annotation strings are displayed as supplied, without recomputation. */
export function TofuEvalGold({ gold }: { gold: unknown }) {
  if (!isTofuGold(gold)) return <GenericGold gold={gold} />;
  return <details className="eval-gold" open>
    <summary>Gold</summary>
    <div className="eval-gold-content" role="region" aria-label="Gold annotations">
      <p>Summary: {gold.summary}</p>
      <ol className="eval-gold-sentences">
        {gold.sentences.map((sentence, position) => <li key={position}>
          <h3>Sentence {sentence.sent_idx}</h3>
          <p className="eval-gold-text">{sentence.text}</p>
          <dl>
            <dt>Label</dt><dd>{sentence.label}</dd>
            {sentence.types.length > 0 && <><dt>Error types</dt><dd>{sentence.types.join(", ")}</dd></>}
            {sentence.exp !== "" && <><dt>Explanation</dt><dd className="eval-gold-text">{sentence.exp}</dd></>}
          </dl>
        </li>)}
      </ol>
    </div>
  </details>;
}
