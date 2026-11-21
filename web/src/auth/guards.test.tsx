import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { useQuery } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { server } from "../mocks/server";
import { here, renderApp } from "../test/renderApp";
import { createMemoryRouter, RouterProvider } from "react-router";
import { routes } from "../routes/routes";
import { createFakeAuthService } from "./fakeService";
import { AuthProvider } from "./AuthProvider";
import { useApiClient } from "./useApiClient";
import { QueryClientProvider } from "@tanstack/react-query";
import { makeQueryClient } from "../queryClient";

const h1 = (name: string) => screen.findByRole("heading", { level: 1, name });

describe("guards", () => {
  it.each(["/sessions/new", "/sessions/abc", "/sessions/abc/reports/1", "/settings"])(
    "unauthenticated %s -> /login?next=",
    async (path) => {
      const { router } = renderApp(path);
      await h1("Log in");
      expect(here(router)).toBe(`/login?next=${encodeURIComponent(path)}`);
    },
  );

  it("unauthenticated users can read /sample-report", async () => {
    renderApp("/sample-report");
    await h1("Sample report");
  });

  it("an unverified user cannot reach / and is sent to /verify-email", async () => {
    const { router } = renderApp("/", { user: { email: "a@clinic.org", verified: false } });
    await h1("Verify your email");
    expect(here(router)).toBe("/verify-email");
    expect(screen.queryByRole("heading", { level: 1, name: "Sessions" })).not.toBeInTheDocument();
  });

  it("an unverified user is sent from a deep link to /verify-email keeping next", async () => {
    const { router } = renderApp("/sessions/abc", { user: { email: "a@clinic.org", verified: false } });
    await h1("Verify your email");
    expect(here(router)).toBe("/verify-email?next=%2Fsessions%2Fabc");
  });

  it("a verified user reaches /", async () => {
    renderApp("/", { user: { email: "a@clinic.org", verified: true } });
    await h1("Sessions");
  });

  it("a verified user on /login or /verify-email is sent on", async () => {
    renderApp("/login", { user: { email: "a@clinic.org", verified: true } });
    await h1("Sessions");
  });

  it("a signed-out user on /verify-email goes to /login", async () => {
    renderApp("/verify-email");
    await h1("Log in");
  });

  it("an unverified user can still open the sign-up/login pages' redirect to verify", async () => {
    const { router } = renderApp("/login", { user: { email: "a@clinic.org", verified: false } });
    await h1("Verify your email");
    expect(here(router)).toBe("/verify-email");
  });
});

function Probe() {
  const client = useApiClient();
  const q = useQuery({
    queryKey: ["probe"],
    queryFn: async () => (await client.GET("/usage")).response.status,
    retry: false,
  });
  return <p>{q.isSuccess ? `status ${q.data}` : "pending"}</p>;
}

const USAGE = `${window.location.origin}/v1/usage`;

function renderWithProbe(service: ReturnType<typeof createFakeAuthService>, path: string) {
  const queryClient = makeQueryClient();
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider service={service}>
        <Probe />
        <RouterProvider router={router} />
      </AuthProvider>
    </QueryClientProvider>,
  );
  return { router, queryClient };
}

describe("token retry and sign-out", () => {
  it("one 401 then success: exactly one forced refresh, still signed in", async () => {
    const service = createFakeAuthService();
    service.signedInAs("a@clinic.org", { verified: true });
    let n = 0;
    server.use(
      http.get(USAGE, () =>
        ++n === 1 ? new HttpResponse(null, { status: 401 }) : HttpResponse.json({ runs_today: 0, daily_cap: 20, resets_at: "x" }),
      ),
    );
    const { router } = renderWithProbe(service, "/settings");
    expect(await screen.findByText("status 200")).toBeInTheDocument();
    expect(service.calls.forcedRefreshes).toBe(1);
    await h1("Settings");
    expect(here(router)).toBe("/settings");
  });

  it("a second 401 signs out, clears the query cache and the guard sends to /login", async () => {
    server.use(http.get(USAGE, () => new HttpResponse(null, { status: 401 })));
    const service = createFakeAuthService();
    service.signedInAs("a@clinic.org", { verified: true });
    const signOut = vi.spyOn(service, "signOut");
    const { router, queryClient } = renderWithProbe(service, "/settings");
    queryClient.setQueryData(["secret"], { phi: "x" });
    await h1("Log in");
    expect(service.calls.forcedRefreshes).toBe(1);
    expect(signOut).toHaveBeenCalledTimes(1);
    expect(here(router)).toBe("/login?next=%2Fsettings");
    expect(queryClient.getQueryData(["secret"])).toBeUndefined();
    expect(await service.getToken()).toBeNull();
  });
});
