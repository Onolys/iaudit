import { useState, type FormEvent } from "react";
import { Link, useLocation } from "react-router";
import { useAuth } from "../AuthProvider";
import { errorCode } from "../errors";
import { withNext } from "../next";
import { ErrorSummary } from "./parts";
import { useFormError } from "./useFormError";

/** Same confirmation for every email: no account enumeration (R2). */
export const RESET_CONFIRMATION = "If an account exists for that email, we've sent a link to reset your password.";

// Only failures that say nothing about the account are shown; everything else gets the confirmation.
const SHOWN = new Set(["auth/network-request-failed", "auth/too-many-requests"]);

export function ForgotPassword() {
  const { service } = useAuth();
  const { search } = useLocation();
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const form = useFormError();

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const email = String(new FormData(e.currentTarget).get("email") ?? "").trim();
    form.clear();
    if (!email) {
      form.failWith("Enter your email address.");
      return;
    }
    setBusy(true);
    try {
      await service.sendPasswordReset(email);
      setSent(true);
    } catch (err) {
      if (SHOWN.has(errorCode(err) ?? "")) form.fail(err);
      else setSent(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1>Reset your password</h1>
      <form className="auth-form" onSubmit={(e) => void onSubmit(e)} noValidate>
        {form.error && <ErrorSummary error={form.error} search={search} />}
        {sent && <p role="status">{RESET_CONFIRMATION}</p>}
        <label>
          Email
          <input name="email" type="email" autoComplete="email" required />
        </label>
        <button type="submit" className="primary" disabled={busy}>
          Send reset link
        </button>
        <p>
          <Link to={withNext("/login", search)}>Back to log in</Link>
        </p>
      </form>
    </>
  );
}
