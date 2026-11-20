import { QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { AuthProvider } from "../auth/AuthProvider";
import { createFakeAuthService, type FakeAuthService } from "../auth/fakeService";
import { makeQueryClient } from "../queryClient";
import { routes } from "../routes/routes";

export interface RenderOptions {
  service?: FakeAuthService;
  /** Pre-signed-in user. Omit for signed out. */
  user?: { email: string; verified: boolean };
}

export function renderApp(path: string, opts: RenderOptions = {}) {
  const service = opts.service ?? createFakeAuthService();
  if (opts.user) service.signedInAs(opts.user.email, { verified: opts.user.verified });
  const queryClient = makeQueryClient();
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider service={service}>
        <RouterProvider router={router} />
      </AuthProvider>
    </QueryClientProvider>,
  );
  return { router, service, queryClient };
}

export function here(router: { state: { location: { pathname: string; search: string } } }) {
  return router.state.location.pathname + router.state.location.search;
}
