/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_AUDIT_URL?: string;
  readonly VITE_MOCK?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
