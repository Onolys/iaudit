import { Navigate, Outlet, useLocation } from "react-router";
import { useAuth } from "./AuthProvider";
import { loginUrl, readNext, verifyUrl } from "./next";

function Loading() {
  return (
    <p role="status" aria-live="polite">
      Loading…
    </p>
  );
}

/** Signed-in and email-verified only (R1 guards). */
export function RequireVerified() {
  const { status, user } = useAuth();
  const { pathname, search } = useLocation();
  if (status === "loading") return <Loading />;
  if (!user) return <Navigate to={loginUrl(pathname, search)} replace />;
  if (!user.emailVerified) return <Navigate to={verifyUrl(pathname, search)} replace />;
  return <Outlet />;
}

/** Login / sign-up / forgot-password: signed-in users are sent on. */
export function PublicOnly() {
  const { status, user } = useAuth();
  const { search } = useLocation();
  if (status === "loading") return <Loading />;
  if (user?.emailVerified) return <Navigate to={readNext(search)} replace />;
  if (user) return <Navigate to={verifyTo(search)} replace />;
  return <Outlet />;
}

function verifyTo(search: string): string {
  const next = readNext(search);
  return next === "/" ? "/verify-email" : `/verify-email?next=${encodeURIComponent(next)}`;
}

/** `/verify-email`: signed-in and unverified only. */
export function RequireUnverified() {
  const { status, user } = useAuth();
  const { search } = useLocation();
  if (status === "loading") return <Loading />;
  if (!user) {
    const next = readNext(search);
    return <Navigate to={next === "/" ? "/login" : `/login?next=${encodeURIComponent(next)}`} replace />;
  }
  if (user.emailVerified) return <Navigate to={readNext(search)} replace />;
  return <Outlet />;
}
