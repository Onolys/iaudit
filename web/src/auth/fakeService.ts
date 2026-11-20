/**
 * In-memory AuthService for mock mode and tests (`VITE_AUTH_MODE=fake`).
 * Tokens match SP04 `AUTH_MODE=fake` (`Bearer test:<uid>`). No persistence.
 */
import { fakeToken } from "./fake";
import { AuthError, type AuthService, type AuthUser } from "./types";

interface Account {
  uid: string;
  email: string;
  password: string | null;
  verified: boolean;
}

export interface FakeAuthOptions {
  /** Mock dev mode: refreshUser() marks the account verified (no inbox to click in). */
  autoVerify?: boolean;
}

export interface FakeAuthService extends AuthService {
  calls: {
    signUps: number;
    signIns: number;
    googleSignIns: number;
    verificationEmails: number;
    forcedRefreshes: number;
    resets: string[];
  };
  /** Pretend the user clicked the email link (visible after the next refreshUser). */
  markVerified(email: string): void;
  /** Test shortcut: be signed in as this account right now. */
  signedInAs(email: string, opts: { verified: boolean }): void;
}

const uidFor = (email: string) => `u_${email.toLowerCase().replace(/[^a-z0-9]/g, "_")}`;
const norm = (email: string) => email.trim().toLowerCase();

export function createFakeAuthService(options: FakeAuthOptions = {}): FakeAuthService {
  const accounts = new Map<string, Account>();
  const listeners = new Set<(u: AuthUser | null) => void>();
  let currentEmail: string | null = null;
  // Verification state the app has seen (the "cached token"); the account holds the truth.
  let seenVerified = false;

  const view = (): AuthUser | null => {
    if (!currentEmail) return null;
    const a = accounts.get(currentEmail)!;
    return { uid: a.uid, email: a.email, emailVerified: seenVerified };
  };
  const emit = () => {
    const u = view();
    for (const l of [...listeners]) l(u ? { ...u } : null);
  };
  const enter = (email: string) => {
    currentEmail = email;
    seenVerified = accounts.get(email)!.verified;
    emit();
  };

  const calls: FakeAuthService["calls"] = {
    signUps: 0,
    signIns: 0,
    googleSignIns: 0,
    verificationEmails: 0,
    forcedRefreshes: 0,
    resets: [],
  };

  return {
    calls,
    onAuthStateChanged(cb) {
      listeners.add(cb);
      void Promise.resolve().then(() => {
        if (listeners.has(cb)) {
          const u = view();
          cb(u ? { ...u } : null);
        }
      });
      return () => void listeners.delete(cb);
    },
    async signUp(email, password) {
      calls.signUps++;
      const key = norm(email);
      if (accounts.has(key)) throw new AuthError("auth/email-already-in-use");
      if (password.length < 6) throw new AuthError("auth/weak-password");
      accounts.set(key, { uid: uidFor(key), email: key, password, verified: false });
      calls.verificationEmails++;
      enter(key);
    },
    async signIn(email, password) {
      calls.signIns++;
      const a = accounts.get(norm(email));
      if (!a || a.password !== password) throw new AuthError("auth/invalid-credential");
      enter(a.email);
    },
    async signInWithGoogle() {
      calls.googleSignIns++;
      const key = "google.user@example.com";
      if (!accounts.has(key)) accounts.set(key, { uid: uidFor(key), email: key, password: null, verified: true });
      enter(key);
    },
    async sendPasswordReset(email) {
      calls.resets.push(email);
      if (!accounts.has(norm(email))) throw new AuthError("auth/user-not-found");
    },
    async sendVerificationEmail() {
      if (!currentEmail) throw new AuthError("auth/requires-recent-login");
      calls.verificationEmails++;
    },
    async refreshUser() {
      if (!currentEmail) return null;
      calls.forcedRefreshes++;
      const a = accounts.get(currentEmail)!;
      if (options.autoVerify) a.verified = true;
      seenVerified = a.verified;
      emit();
      return view();
    },
    async getToken(forceRefresh) {
      if (!currentEmail) return null;
      if (forceRefresh) calls.forcedRefreshes++;
      return fakeToken(accounts.get(currentEmail)!.uid);
    },
    async signOut() {
      currentEmail = null;
      seenVerified = false;
      emit();
    },
    markVerified(email) {
      const a = accounts.get(norm(email));
      if (a) a.verified = true;
    },
    signedInAs(email, { verified }) {
      const key = norm(email);
      accounts.set(key, { uid: uidFor(key), email: key, password: "password1", verified });
      enter(key);
    },
  };
}
