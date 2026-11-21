import type { AppConfig, AuthConfig } from "../config";

/** The gate renders only for a deployed build (VITE_AUTH_REQUIRED=true); local dev and VITE_MOCK skip it. */
export function shouldGate(config: AppConfig & AuthConfig): boolean {
  return config.authRequired && !config.mock;
}
