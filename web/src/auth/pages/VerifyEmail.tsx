import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "../AuthProvider";
import { ErrorSummary } from "./parts";
import { useFormError } from "./useFormError";

export const RESEND_COOLDOWN_SECONDS = 60;

export function VerifyEmail() {
  const { service, user, signOut } = useAuth();
  const [cooldown, setCooldown] = useState(0);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const form = useFormError();
  const checking = useRef(false);

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  // Reload + forced token refresh; on success the guard redirects (user.emailVerified flips).
  const check = useCallback(
    async (announce: boolean) => {
      if (checking.current) return;
      checking.current = true;
      try {
        const fresh = await service.refreshUser();
        if (fresh && !fresh.emailVerified && announce) {
          setNote("We haven't seen your verification yet. Open the link in the email, then try again.");
        }
      } catch {
        if (announce) setNote("Couldn't check just now. Please try again.");
      } finally {
        checking.current = false;
      }
    },
    [service],
  );

  useEffect(() => {
    const onFocus = () => void check(false);
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [check]);

  async function resend() {
    form.clear();
    setBusy(true);
    try {
      await service.sendVerificationEmail();
      setNote("Verification email sent.");
      setCooldown(RESEND_COOLDOWN_SECONDS);
    } catch (err) {
      form.fail(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1>Verify your email</h1>
      <div className="auth-form">
        {form.error && <ErrorSummary error={form.error} search="" />}
        <p>
          Check your inbox — and your spam folder. We sent a verification link to <strong>{user?.email}</strong>.
        </p>
        {note && <p role="status">{note}</p>}
        <button type="button" className="primary" onClick={() => void check(true)}>
          I've verified
        </button>
        <button type="button" className="secondary" disabled={busy || cooldown > 0} onClick={() => void resend()}>
          {cooldown > 0 ? `Resend in ${cooldown}s` : "Resend email"}
        </button>
        <p>
          Wrong address?{" "}
          <button type="button" className="secondary" onClick={() => void signOut()}>
            Sign out
          </button>
        </p>
      </div>
    </>
  );
}
