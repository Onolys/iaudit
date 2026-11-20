/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_AUDIT_URL?: string;
  readonly VITE_MOCK?: string;
  readonly VITE_EVAL_API_BASE?: string;
  readonly VITE_EVAL_ENABLED?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
