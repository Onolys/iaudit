/** Firebase Auth implementation (modular `firebase/auth` only; PRD R2, D8). */
import { initializeApp } from "firebase/app";
import {
  GoogleAuthProvider,
  createUserWithEmailAndPassword,
  getAuth,
  getRedirectResult,
  onIdTokenChanged,
  reload,
  sendEmailVerification,
  sendPasswordResetEmail,
  signInWithEmailAndPassword,
  signInWithPopup,
  signInWithRedirect,
  signOut as fbSignOut,
  type User,
} from "firebase/auth";
import { AuthError, type AuthService, type AuthUser } from "./types";

export interface FirebaseWebConfig {
  apiKey: string;
  authDomain: string;
  projectId: string;
  appId: string;
}

const toUser = (u: User | null): AuthUser | null =>
  u ? { uid: u.uid, email: u.email, emailVerified: u.emailVerified } : null;

const POPUP_FALLBACK = new Set([
  "auth/popup-blocked",
  "auth/operation-not-supported-in-this-environment",
  "auth/web-storage-unsupported",
]);

const isMobile = () => /Android|iPhone|iPad|iPod/i.test(globalThis.navigator?.userAgent ?? "");

export function createFirebaseAuthService(config: FirebaseWebConfig): AuthService {
  const app = initializeApp(config);
  const auth = getAuth(app);
  const listeners = new Set<(u: AuthUser | null) => void>();
  const emit = () => {
    const u = toUser(auth.currentUser);
    for (const l of [...listeners]) l(u ? { ...u } : null);
  };

  // Completes a redirect sign-in; the token listener below reports the user.
  void getRedirectResult(auth).catch(() => undefined);
  onIdTokenChanged(auth, emit);

  const need = (): User => {
    if (!auth.currentUser) throw new AuthError("auth/requires-recent-login");
    return auth.currentUser;
  };

  return {
    onAuthStateChanged(cb) {
      listeners.add(cb);
      // Only report once the SDK has loaded persisted state.
      void auth.authStateReady().then(() => {
        if (listeners.has(cb)) cb(toUser(auth.currentUser));
      });
      return () => void listeners.delete(cb);
    },
    async signUp(email, password) {
      const cred = await createUserWithEmailAndPassword(auth, email, password);
      await sendEmailVerification(cred.user, { url: `${window.location.origin}/verify-email` });
      emit();
    },
    async signIn(email, password) {
      await signInWithEmailAndPassword(auth, email, password);
    },
    async signInWithGoogle() {
      const provider = new GoogleAuthProvider();
      if (isMobile()) return signInWithRedirect(auth, provider);
      try {
        await signInWithPopup(auth, provider);
      } catch (err) {
        const code = (err as { code?: string }).code ?? "";
        if (POPUP_FALLBACK.has(code)) return signInWithRedirect(auth, provider);
        throw err;
      }
    },
    async sendPasswordReset(email) {
      await sendPasswordResetEmail(auth, email);
    },
    async sendVerificationEmail() {
      await sendEmailVerification(need(), { url: `${window.location.origin}/verify-email` });
    },
    async refreshUser() {
      const user = auth.currentUser;
      if (!user) return null;
      await reload(user);
      await user.getIdToken(true); // the cached token lacks email_verified until refreshed
      emit();
      return toUser(auth.currentUser);
    },
    async getToken(forceRefresh = false) {
      const user = auth.currentUser;
      return user ? user.getIdToken(forceRefresh) : null;
    },
    async signOut() {
      await fbSignOut(auth);
    },
  };
}
