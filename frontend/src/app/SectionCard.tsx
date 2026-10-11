import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { VerdictCounts as Counts, Verdict } from "../contract";
import { VerdictCounts } from "./VerdictCounts";

const ZERO: Counts = {
  supported: 0,
  partially_supported: 0,
  contradicted: 0,
  insufficient_evidence: 0,
  out_of_scope: 0,
};

interface SectionCardProps {
  label: string;
  score?: number | string;
  notProcessed?: boolean;
  /** Omit for the trailing "outside" card, which has no menu. */
  counts?: Counts;
  activeVerdict?: Verdict | null;
  onPick?: (verdict: Verdict) => void;
  children: ReactNode;
}

export function SectionCard({ label, score, notProcessed, counts, activeVerdict = null, onPick, children }: SectionCardProps) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  return (
    <section className={["section-card", notProcessed && "not-processed", open && "menu-open"].filter(Boolean).join(" ")}>
      <div className="section-header">
        <h3>{label}</h3>
        {score !== undefined ? (
          <span className="score-chip" title="Display only, not an audit result">
            Score {score}
          </span>
        ) : null}
        {notProcessed ? <span className="chip">Not processed</span> : null}
        {counts && onPick ? (
          <div className="section-menu-anchor" ref={menuRef}>
            <button type="button" aria-label="Section menu" aria-expanded={open} onClick={() => setOpen(!open)}>
              ⋯
            </button>
            {open ? (
              <div className="section-menu">
                <VerdictCounts
                  counts={counts ?? ZERO}
                  active={activeVerdict}
                  disabled={notProcessed}
                  onPick={(v) => {
                    setOpen(false);
                    onPick(v);
                  }}
                />
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
      {children}
    </section>
  );
}
