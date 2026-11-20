/** Firebase Auth provider: `firebase/app` + `firebase/auth` only. Email/password and Google; no sign-up, no MFA. */
import { initializeApp } from "firebase/app";
import { GoogleAuthProvider, getAuth, onAuthStateChanged, signInWithEmailAndPassword, signInWithPopup, signOut } from "firebase/auth";
import type { FirebaseConfig } from "../config";
import type { AuthProvider } from "./types";

export function createFirebaseProvider(config: FirebaseConfig): AuthProvider {
  const auth = getAuth(initializeApp(config));
  return {
    onAuthChange: cb => onAuthStateChanged(auth, u => cb(u ? { email: u.email } : null)),
    getIdToken: async force => (auth.currentUser ? auth.currentUser.getIdToken(force) : null),
    signInWithEmail: async (email, password) => void (await signInWithEmailAndPassword(auth, email, password)),
    signInWithGoogle: async () => void (await signInWithPopup(auth, new GoogleAuthProvider())),
    signOut: () => signOut(auth),
  };
}
