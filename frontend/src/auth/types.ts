export interface AuthUser {
  email: string | null;
}

/** The single injected auth provider (Firebase in production, a fake in tests). Email/password and Google only. */
export interface AuthProvider {
  onAuthChange(cb: (user: AuthUser | null) => void): () => void;
  getIdToken(forceRefresh?: boolean): Promise<string | null>;
  signInWithEmail(email: string, password: string): Promise<void>;
  signInWithGoogle(): Promise<void>;
  signOut(): Promise<void>;
}
