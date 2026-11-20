/** Provider-neutral auth seam (PRD R2, D8). Firebase and fake mode both implement it. */

export interface AuthUser {
  uid: string;
  email: string | null;
  emailVerified: boolean;
}

/** Carries a Firebase-style `auth/...` code so one error mapper serves both implementations. */
export class AuthError extends Error {
  readonly code: string;
  constructor(code: string) {
    super(code);
    this.name = "AuthError";
    this.code = code;
  }
}

export interface AuthService {
  /** Fires once with the initial state, then on every change. `null` = signed out. */
  onAuthStateChanged(cb: (user: AuthUser | null) => void): () => void;
  /** Creates the account and sends the verification email. */
  signUp(email: string, password: string): Promise<void>;
  signIn(email: string, password: string): Promise<void>;
  signInWithGoogle(): Promise<void>;
  sendPasswordReset(email: string): Promise<void>;
  sendVerificationEmail(): Promise<void>;
  /** Reload the user and force-refresh the ID token (the cached one lacks `email_verified`). */
  refreshUser(): Promise<AuthUser | null>;
  /** SDK-managed token; `forceRefresh` maps to `getIdToken(true)`. */
  getToken(forceRefresh?: boolean): Promise<string | null>;
  signOut(): Promise<void>;
}
