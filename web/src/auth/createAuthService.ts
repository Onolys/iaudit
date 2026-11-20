import { createFakeAuthService } from "./fakeService";
import type { AuthService } from "./types";

/** `VITE_AUTH_MODE=fake` (mock mode) or Firebase from `VITE_FIREBASE_*`. Firebase is loaded lazily. */
export async function createAuthService(env: ImportMetaEnv = import.meta.env): Promise<AuthService> {
  if (env.VITE_AUTH_MODE === "fake") return createFakeAuthService({ autoVerify: true });
  const { createFirebaseAuthService } = await import("./firebaseService");
  return createFirebaseAuthService({
    apiKey: env.VITE_FIREBASE_API_KEY,
    authDomain: env.VITE_FIREBASE_AUTH_DOMAIN,
    projectId: env.VITE_FIREBASE_PROJECT_ID,
    appId: env.VITE_FIREBASE_APP_ID,
  });
}
