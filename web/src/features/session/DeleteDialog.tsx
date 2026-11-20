import { useEffect, useRef, type ReactNode } from "react";

/** Confirm dialog for permanent deletion (PRD R4 Delete). Escape or Cancel closes it. */
export function DeleteDialog({
  busy,
  onConfirm,
  onCancel,
  children,
}: {
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  /** Error card slot, shown inside the dialog. */
  children?: ReactNode;
}) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    cancelRef.current?.focus();
  }, []);

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      onCancel();
    } else if (e.key === "Tab") {
      // keep focus inside the dialog
      const items = dialogRef.current?.querySelectorAll<HTMLElement>("button:not([disabled])");
      if (!items || items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  };

  return (
    <div className="dialog-backdrop">
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions */}
      <div
        ref={dialogRef}
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="delete-title"
        aria-describedby="delete-body"
        onKeyDown={onKeyDown}
      >
        <h2 id="delete-title">Delete this session?</h2>
        <p id="delete-body">
          This permanently removes the audio, transcript, rating and all report versions. This can't be undone.
        </p>
        {children}
        <div className="dialog-actions">
          <button ref={cancelRef} type="button" className="btn btn-secondary" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button type="button" className="btn btn-danger" onClick={onConfirm} disabled={busy}>
            Delete permanently
          </button>
        </div>
      </div>
    </div>
  );
}
