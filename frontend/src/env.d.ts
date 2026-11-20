/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_AUDIT_URL?: string;
  readonly VITE_MOCK?: string;
  readonly VITE_EVAL_API_BASE?: string;
  readonly VITE_EVAL_ENABLED?: string;
  readonly VITE_AUTH_REQUIRED?: string;
  readonly VITE_FIREBASE_API_KEY?: string;
  readonly VITE_FIREBASE_AUTH_DOMAIN?: string;
  readonly VITE_FIREBASE_PROJECT_ID?: string;
  readonly VITE_FIREBASE_APP_ID?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
