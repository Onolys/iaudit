import { useEffect, useRef, type ReactNode } from "react";

/** Minimal modal: focus moves in and is trapped; Escape calls `onEscape` when given (the secret dialog omits it). */
export function Modal({
  titleId,
  onEscape,
  testId,
  children,
}: {
  titleId: string;
  onEscape?: () => void;
  testId?: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.querySelector<HTMLElement>("button, input")?.focus();
  }, []);

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      onEscape?.();
    } else if (e.key === "Tab") {
      const items = ref.current?.querySelectorAll<HTMLElement>("button:not([disabled]), input:not([disabled])");
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
    <div className="dialog-backdrop" data-testid={testId}>
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions */}
      <div ref={ref} className="dialog" role="dialog" aria-modal="true" aria-labelledby={titleId} onKeyDown={onKeyDown}>
        {children}
      </div>
    </div>
  );
}
