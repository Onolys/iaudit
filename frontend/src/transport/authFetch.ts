export interface AuthFetchDeps {
  fetch: typeof fetch;
  /** The one injected token provider. `forceRefresh` asks for a new ID token. */
  getToken: (forceRefresh?: boolean) => Promise<string | null>;
  /** Still 401 after one forced refresh: go to login. */
  onUnauthorized: () => void;
  /** 403: signed in but not on the admin list. */
  onForbidden: () => void;
}

/** fetch wrapper: `Authorization: Bearer <ID token>`; 401 -> one forced refresh + retry, then login; 403 -> forbidden. */
export function createAuthFetch({ fetch: doFetch, getToken, onUnauthorized, onForbidden }: AuthFetchDeps): typeof fetch {
  const send = async (input: RequestInfo | URL, init: RequestInit | undefined, force: boolean) => {
    const headers = new Headers(init?.headers);
    const token = await getToken(force);
    if (token) headers.set("Authorization", `Bearer ${token}`);
    else headers.delete("Authorization");
    return doFetch(input, { ...init, headers });
  };
  return async (input, init) => {
    let res = await send(input, init, false);
    if (res.status === 401) {
      res = await send(input, init, true);
      if (res.status === 401) onUnauthorized();
    }
    if (res.status === 403) onForbidden();
    return res;
  };
}
