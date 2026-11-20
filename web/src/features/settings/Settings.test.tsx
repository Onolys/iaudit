import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { here, renderApp } from "../../test/renderApp";
import { mockBackend } from "../../mocks/server";

const UID = "u_rater_clinic_org";
const USER = { email: "rater@clinic.org", verified: true };
const SECRET_RE = /onolys_[A-Za-z0-9]+_[A-Za-z0-9]+/;
const main = () => within(screen.getByRole("main"));
const dialog = () => screen.getByRole("dialog");

async function createKey(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await main().findByRole("button", { name: "Create API key" }));
  const text = await within(await screen.findByRole("dialog")).findByTestId("api-secret");
  return text.textContent ?? "";
}

let spies: ReturnType<typeof vi.spyOn>[] = [];
beforeEach(() => {
  spies = (["log", "info", "warn", "error", "debug"] as const).map((m) => vi.spyOn(console, m).mockImplementation(() => {}));
});
afterEach(() => {
  spies.forEach((s) => s.mockRestore());
  localStorage.clear();
  sessionStorage.clear();
});

const everythingLogged = () => JSON.stringify(spies.flatMap((s) => s.mock.calls));
const everythingStored = () =>
  JSON.stringify({ l: { ...localStorage }, s: { ...sessionStorage } });

describe("settings: API key", () => {
  it("shows 'no key' and offers Create when none is active", async () => {
    renderApp("/settings", { user: USER });
    expect(await main().findByText(/no api key/i)).toBeInTheDocument();
    expect(main().queryByRole("button", { name: /regenerate|revoke/i })).toBeNull();
  });

  it("shows the secret once in a modal, gated by 'I've stored it', and never again", async () => {
    const user = userEvent.setup();
    const { queryClient } = renderApp("/settings", { user: USER });
    const secret = await createKey(user);
    expect(secret).toMatch(/^onolys_[A-Za-z0-9]+_[A-Za-z0-9]+$/);

    const done = within(dialog()).getByRole("button", { name: "Done" });
    expect(done).toBeDisabled();
    await user.keyboard("{Escape}");
    expect(screen.getByRole("dialog")).toBeInTheDocument(); // Escape does not skip the gate
    await user.click(within(dialog()).getByRole("checkbox", { name: /i've stored it/i }));
    expect(done).toBeEnabled();
    await user.click(done);

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.body.textContent).not.toContain(secret);
    // metadata shows only the public key id prefix
    expect(await main().findByText(/active/i)).toBeInTheDocument();
    expect(JSON.stringify(queryClient.getQueryCache().getAll().map((q) => q.state.data))).not.toContain(secret);
    expect(JSON.stringify(queryClient.getMutationCache().getAll().map((m) => m.state.data))).not.toContain(secret);
  });

  it("is absent after reload and the server never returns it again", async () => {
    const user = userEvent.setup();
    renderApp("/settings", { user: USER });
    const secret = await createKey(user);
    cleanup(); // a reload: all component state gone
    renderApp("/settings", { user: USER });
    expect(await main().findByText(/active/i)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain(secret);
    expect(document.body.textContent).not.toMatch(SECRET_RE);
  });

  it("never writes the secret to localStorage, sessionStorage or the console", async () => {
    const user = userEvent.setup();
    renderApp("/settings", { user: USER });
    const secret = await createKey(user);
    await user.click(within(dialog()).getByRole("checkbox", { name: /i've stored it/i }));
    await user.click(within(dialog()).getByRole("button", { name: "Done" }));
    expect(everythingStored()).not.toContain(secret);
    expect(everythingLogged()).not.toContain(secret);
  });

  it("copy button copies the secret", async () => {
    const user = userEvent.setup();
    renderApp("/settings", { user: USER });
    const secret = await createKey(user);
    await user.click(within(dialog()).getByRole("button", { name: "Copy" }));
    expect(await navigator.clipboard.readText()).toBe(secret);
  });

  it("regenerate asks to confirm that the old key stops working; cancel changes nothing", async () => {
    const user = userEvent.setup();
    mockBackend.createApiKey(UID);
    const before = mockBackend.getApiKey(UID);
    renderApp("/settings", { user: USER });
    await user.click(await main().findByRole("button", { name: "Regenerate" }));
    expect(within(dialog()).getByText(/old key stops working/i)).toBeInTheDocument();
    await user.click(within(dialog()).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(mockBackend.getApiKey(UID).key_id).toBe(before.key_id);

    await user.click(main().getByRole("button", { name: "Regenerate" }));
    await user.click(within(dialog()).getByRole("button", { name: "Regenerate key" }));
    const secret = await within(await screen.findByTestId("api-secret-dialog")).findByTestId("api-secret");
    expect(secret.textContent).toMatch(SECRET_RE);
    expect(mockBackend.getApiKey(UID).key_id).not.toBe(before.key_id);
  });

  it("revoke deactivates the key after confirmation", async () => {
    const user = userEvent.setup();
    mockBackend.createApiKey(UID);
    renderApp("/settings", { user: USER });
    await user.click(await main().findByRole("button", { name: "Revoke" }));
    await user.click(within(dialog()).getByRole("button", { name: "Revoke key" }));
    expect(await main().findByText(/no api key/i)).toBeInTheDocument();
    expect(mockBackend.getApiKey(UID).active).toBe(false);
  });

  it("links to the API docs at /v1/docs with a placeholder curl example", async () => {
    renderApp("/settings", { user: USER });
    const link = await main().findByRole("link", { name: "API docs" });
    expect(link).toHaveAttribute("href", "/v1/docs");
    expect(main().getByText(/curl .*X-API-Key: onolys_<id>_<secret>/)).toBeInTheDocument();
  });

  it("shows usage and the account-removal contact placeholder", async () => {
    renderApp("/settings", { user: USER });
    expect(await main().findByText(/0 of 20 runs today/)).toBeInTheDocument();
    expect(main().getByText(/account removal/i)).toBeInTheDocument();
    expect(main().getByText(/deleting a session removes/i)).toBeInTheDocument();
  });

  it("sign out clears the query cache and returns to login", async () => {
    const user = userEvent.setup();
    const { router, queryClient } = renderApp("/settings", { user: USER });
    await main().findByText(/0 of 20 runs today/);
    expect(queryClient.getQueryCache().getAll().length).toBeGreaterThan(0);
    await user.click(main().getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(here(router)).toMatch(/^\/login/));
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0);
  });
});
