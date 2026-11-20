/** Plain-text mapping of auth error codes (PRD R2). No raw provider messages reach the UI. */

export const MIN_PASSWORD_LENGTH = 8;

export interface MappedAuthError {
  message: string;
  /** Email already in use: the form offers a link to log in. */
  offerLogin?: boolean;
}

export function mapAuthError(code: string | undefined): MappedAuthError {
  switch (code) {
    case "auth/wrong-password":
    case "auth/invalid-credential":
    case "auth/user-not-found":
      return { message: "That email and password don't match. Try again or reset your password." };
    case "auth/weak-password":
      return { message: `Use at least ${MIN_PASSWORD_LENGTH} characters for your password.` };
    case "auth/email-already-in-use":
      return { message: "An account with this email already exists.", offerLogin: true };
    case "auth/invalid-email":
      return { message: "Enter a valid email address." };
    case "auth/too-many-requests":
      return { message: "Too many attempts. Wait a few minutes and try again." };
    case "auth/network-request-failed":
      return { message: "Can't reach the server. Check your connection and try again." };
    case "auth/popup-closed-by-user":
    case "auth/cancelled-popup-request":
      return { message: "Google sign-in was cancelled." };
    case "auth/user-disabled":
      return { message: "This account has been disabled. Contact support." };
    default:
      return { message: "Something went wrong. Please try again." };
  }
}

export function errorCode(err: unknown): string | undefined {
  if (err && typeof err === "object" && "code" in err && typeof (err as { code: unknown }).code === "string") {
    return (err as { code: string }).code;
  }
  return undefined;
}
