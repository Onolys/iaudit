export interface AppConfig {
  mock: boolean;
  auditUrl: string | null;
}

export function getConfig(): AppConfig {
  const { VITE_MOCK, VITE_AUDIT_URL } = import.meta.env;
  return {
    mock: VITE_MOCK === "true",
    auditUrl: VITE_AUDIT_URL ? VITE_AUDIT_URL : null,
  };
}
