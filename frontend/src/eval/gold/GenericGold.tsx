/** Opaque API gold stays inspectable when its kind or shape is unsupported. */
export function GenericGold({ gold }: { gold: unknown }) {
  return <details className="eval-gold">
    <summary>Gold (JSON)</summary>
    <div className="eval-gold-content" role="region" aria-label="Gold JSON">
      <pre>{JSON.stringify(gold, null, 2) ?? "undefined"}</pre>
    </div>
  </details>;
}
