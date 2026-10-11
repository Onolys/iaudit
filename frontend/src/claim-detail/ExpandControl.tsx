interface Props {
  /** Present when turns can still be revealed above this control's position. */
  up?: { hidden: number; onClick: () => void };
  down?: { hidden: number; onClick: () => void };
}

const label = (dir: "above" | "below", hidden: number) =>
  `Show 3 more turns ${dir} (${hidden} hidden)`;

export function ExpandControl({ up, down }: Props) {
  const up_ = up && up.hidden > 0 ? up : undefined;
  const down_ = down && down.hidden > 0 ? down : undefined;
  if (!up_ && !down_) return null;
  return (
    <div className="cd-expand">
      {down_ && (
        <button type="button" onClick={down_.onClick}>
          {label("below", down_.hidden)}
        </button>
      )}
      {up_ && (
        <button type="button" onClick={up_.onClick}>
          {label("above", up_.hidden)}
        </button>
      )}
    </div>
  );
}
