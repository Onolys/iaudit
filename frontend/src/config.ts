export interface AppConfig {
  mock: boolean;
  auditUrl: string | null;
}

export interface EvalConfig {
  evalBase: string;
}

export function getConfig(): AppConfig & EvalConfig {
  const { VITE_MOCK, VITE_AUDIT_URL, VITE_EVAL_API_BASE } = import.meta.env;
  return {
    mock: VITE_MOCK === "true",
    auditUrl: VITE_AUDIT_URL ? VITE_AUDIT_URL : null,
    evalBase: VITE_EVAL_API_BASE || "/eval-api",
  };
}
