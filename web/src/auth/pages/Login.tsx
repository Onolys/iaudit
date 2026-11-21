import { useState, type FormEvent } from "react";
import { Link, useLocation } from "react-router";
import { useAuth } from "../AuthProvider";
import { withNext } from "../next";
import { ErrorSummary } from "./parts";
import { useFormError } from "./useFormError";

export function Login() {
  const { service } = useAuth();
  const { search } = useLocation();
  const [busy, setBusy] = useState(false);
  const form = useFormError();

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const data = new FormData(e.currentTarget);
    form.clear();
    setBusy(true);
    try {
      await service.signIn(String(data.get("email") ?? "").trim(), String(data.get("password") ?? ""));
    } catch (err) {
      form.fail(err);
    } finally {
      setBusy(false);
    }
  }

  async function google() {
    form.clear();
    try {
      await service.signInWithGoogle();
    } catch (err) {
      form.fail(err);
    }
  }

  return (
    <>
      <h1>Log in</h1>
      <form className="auth-form" onSubmit={(e) => void onSubmit(e)} noValidate>
        {form.error && <ErrorSummary error={form.error} search={search} />}
        <label>
          Email
          <input name="email" type="email" autoComplete="email" required />
        </label>
        <label>
          Password
          <input name="password" type="password" autoComplete="current-password" required />
        </label>
        <button type="submit" className="primary" disabled={busy}>
          Log in
        </button>
        <button type="button" className="secondary" onClick={() => void google()}>
          Continue with Google
        </button>
        <p>
          <Link to={withNext("/forgot-password", search)}>Forgot your password?</Link>
        </p>
        <p>
          New here? <Link to={withNext("/signup", search)}>Create an account</Link>
        </p>
      </form>
    </>
  );
}
