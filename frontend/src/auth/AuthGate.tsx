import { useState, useSyncExternalStore } from "react";
import type { FormEvent, ReactNode } from "react";
import type { AuthSession } from "./session";

function Login({ session }: { session: AuthSession }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(false);
    try {
      await fn();
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    void run(() => session.signInWithEmail(email, password));
  };
  return (
    <div className="app-message">
      <form onSubmit={submit}>
        <h2>Sign in</h2>
        <label>Email<input type="email" autoComplete="username" value={email} onChange={e => setEmail(e.target.value)} /></label>
        <label>Password<input type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} /></label>
        <button type="submit" disabled={busy}>Sign in</button>
        <button type="button" disabled={busy} onClick={() => void run(() => session.signInWithGoogle())}>Sign in with Google</button>
        {error ? <p role="alert">Sign-in failed. Check your details and try again.</p> : null}
      </form>
    </div>
  );
}

/** Renders children only for a signed-in admin. Mounted only when the gate is on (see gate.ts). */
export function AuthGate({ session, children }: { session: AuthSession; children: ReactNode }) {
  const { status } = useSyncExternalStore(session.subscribe, session.getSnapshot);
  if (status === "loading") return null;
  if (status === "signed-out") return <Login session={session} />;
  if (status === "forbidden") {
    return (
      <div className="app-message" role="alert">
        <h2>Not allowed</h2>
        <p>This account is not on the admin list.</p>
        <button type="button" onClick={() => void session.signOut()}>Sign out</button>
      </div>
    );
  }
  return (
    <>
      <div className="app-auth-bar"><button type="button" onClick={() => void session.signOut()}>Sign out</button></div>
      {children}
    </>
  );
}
