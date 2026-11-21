/** Fake auth for mock mode (`VITE_AUTH_MODE=fake`): matches SP04 `AUTH_MODE=fake` (`Bearer test:<uid>`). */
import type { TokenProvider } from "../api/client";

export const FAKE_UID = "u_mock";

export function fakeToken(uid: string): string {
  return `test:${uid}`;
}

export function fakeTokenProvider(uid: string = FAKE_UID): TokenProvider {
  return async () => fakeToken(uid);
}
