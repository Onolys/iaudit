export interface AppConfig {
  mock: boolean;
  auditUrl: string | null;
}

export interface EvalConfig {
  evalBase: string;
  /** false only when VITE_EVAL_ENABLED is exactly "false" (deployed build, see .env.production). */
  evalEnabled: boolean;
}

export interface FirebaseConfig {
  apiKey: string;
  authDomain: string;
  projectId: string;
  appId: string;
}

export interface AuthConfig {
  /** true only when VITE_AUTH_REQUIRED is exactly "true" (deployed admin build). */
  authRequired: boolean;
  firebase: FirebaseConfig;
}

export function getConfig(): AppConfig & EvalConfig & AuthConfig {
  const { VITE_MOCK, VITE_AUDIT_URL, VITE_EVAL_API_BASE, VITE_EVAL_ENABLED, VITE_AUTH_REQUIRED } = import.meta.env;
  const { VITE_FIREBASE_API_KEY, VITE_FIREBASE_AUTH_DOMAIN, VITE_FIREBASE_PROJECT_ID, VITE_FIREBASE_APP_ID } = import.meta.env;
  return {
    authRequired: VITE_AUTH_REQUIRED === "true",
    firebase: {
      apiKey: VITE_FIREBASE_API_KEY ?? "",
      authDomain: VITE_FIREBASE_AUTH_DOMAIN || "admin.onolys.com",
      projectId: VITE_FIREBASE_PROJECT_ID ?? "",
      appId: VITE_FIREBASE_APP_ID ?? "",
    },
    mock: VITE_MOCK === "true",
    auditUrl: VITE_AUDIT_URL ? VITE_AUDIT_URL : null,
    evalBase: VITE_EVAL_API_BASE || "/eval-api",
    evalEnabled: VITE_EVAL_ENABLED !== "false",
  };
}
