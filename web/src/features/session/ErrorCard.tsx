import type { ReactNode } from "react";
import { messageForCode } from "../../api/errors";

/** Plain message per error code plus the reference id support can look up (PRD R4 Failure, R8). */
export function ErrorCard({
  code,
  reference,
  resetsAt,
  children,
}: {
  code: string | undefined;
  reference?: string;
  resetsAt?: string;
  children?: ReactNode;
}) {
  return (
    <div className="error-card" role="alert">
      <p className="error-card-message">{messageForCode(code, { resetsAt })}</p>
      {reference ? <p className="error-card-ref">Reference: {reference}</p> : null}
      {children ? <div className="error-card-actions">{children}</div> : null}
    </div>
  );
}
