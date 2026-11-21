# Email action links (web)

Every Firebase email action link (verification, password reset, change of email, recover email) points to our own page, `/auth/action` (`web/src/auth/pages/AuthAction.tsx`), not Google's hosted handler (`https://onolys.firebaseapp.com/__/auth/action`).

**Why.** The project's Identity Platform config carries a Google `AQ.` key as `client.apiKey`. Google puts that key in the email link, and the hosted handler calls `identitytoolkit/v3/relyingparty/setAccountInfo?key=AQ...`, which answers `401 CREDENTIALS_MISSING`. The hosted page shows that as "Try verifying your email again ... expired or already used", although the code is fine. Our handler uses the app's own Firebase auth instance (web `AIzaSy...` key) and ignores the link's `apiKey` parameter.

**Behaviour.**
- The route is public and outside every auth guard (works signed out, unverified or verified).
- `mode=verifyEmail`: the code is applied only when the user clicks "Verify my email" (mail scanners prefetch links and would consume the one-time code). Then the user is reloaded and the ID token refreshed so guards see `emailVerified`.
- `mode=resetPassword`: the code is checked on load (not consumed), then a new password (min 8 characters) is set.
- `mode=verifyAndChangeEmail` (from `verifyBeforeUpdateEmail`): the code is checked on load (shows the new address, not consumed); applied only on click of "Confirm new email". The change revokes the session, so the user is told to log in again with the new email (if the session survived, "Continue" is offered).
- `mode=recoverEmail` (sent to the old address after a change): the code is checked on load (shows the address to restore); applied only on click of "Restore this email". The success page suggests resetting the password (button sends a reset email to the restored address) since the account may be compromised.
- Other or missing `mode` / `oobCode`: "This link isn't valid". This includes `mode=revertSecondFactorAddition` (MFA is disabled in this project), which adds a note that two-step verification isn't used.
- Invalid or expired codes show "Link expired" (change/recover) or the existing per-mode messages; other errors show a plain-text mapped message.
- `continueUrl` is followed only if it is same-origin, or an https URL on a known app host (`app.onolys.com`, `onolys-app.web.app`, `onolys-app-staging.web.app`); otherwise `/`. Staging shares the Firebase project, so its links go through the configured action URL and return to staging via `continueUrl`.

**Config.** The email action URL (`notification.sendEmail.callbackUri`) is `https://app.onolys.com/auth/action`, set by `infra/scripts/identity-config.py` (`--callback-uri` to override; run by `terraform_data.identity_policy`). Console equivalent: Authentication > Templates > Customize action URL, for each email type (the callbackUri is project-wide, so all action types land on this page).
