export interface AppConfig {
  mock: boolean;
  auditUrl: string | null;
}

export interface EvalConfig {
  evalBase: string;
  /** false only when VITE_EVAL_ENABLED is exactly "false" (deployed build, see .env.production). */
  evalEnabled: boolean;
}

export function getConfig(): AppConfig & EvalConfig {
  const { VITE_MOCK, VITE_AUDIT_URL, VITE_EVAL_API_BASE, VITE_EVAL_ENABLED } = import.meta.env;
  return {
    mock: VITE_MOCK === "true",
    auditUrl: VITE_AUDIT_URL ? VITE_AUDIT_URL : null,
    evalBase: VITE_EVAL_API_BASE || "/eval-api",
    evalEnabled: VITE_EVAL_ENABLED !== "false",
  };
}
