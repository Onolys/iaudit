import type { ReactNode, RefObject } from "react";

export interface HeaderProps {
  fileName?: string;
  requestId?: string;
  mock: boolean;
  inputRef?: RefObject<HTMLInputElement | null>;
  onFile?: (file: File) => void;
  /** Verdict count buttons, present once an audit is loaded. */
  children?: ReactNode;
}

export function Header({ fileName, requestId, mock, inputRef, onFile, children }: HeaderProps) {
  return (
    <header className="app-header">
      <div className="app-header-top">
        {onFile ? (
          <>
            <input
              ref={inputRef}
              type="file"
              hidden
              accept=".json,application/json"
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (file) onFile(file);
              }}
            />
            <button type="button" onClick={() => inputRef?.current?.click()}>
              Upload request…
            </button>
          </>
        ) : null}
        {fileName ? <span className="app-header-file">{fileName}</span> : null}
        <span className="app-header-id">{requestId ?? "No request ID"}</span>
        {mock ? <span className="chip">Mock data</span> : null}
      </div>
      {children ? <div className="app-header-counts">{children}</div> : null}
    </header>
  );
}
