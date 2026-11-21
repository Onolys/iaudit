import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { makeQueryClient } from "../queryClient";
import { AuthProvider, useAuth } from "./AuthProvider";
import { createFakeAuthService } from "./fakeService";

function Who() {
  const { status, user, signOut } = useAuth();
  return (
    <>
      <p>{status === "loading" ? "loading" : (user?.email ?? "signed out")}</p>
      <button onClick={() => void signOut()}>out</button>
    </>
  );
}

describe("AuthProvider", () => {
  it("reports loading, then the user; sign-out clears the query cache", async () => {
    const service = createFakeAuthService();
    service.signedInAs("a@clinic.org", { verified: true });
    const qc = makeQueryClient();
    qc.setQueryData(["secret"], 1);
    render(
      <QueryClientProvider client={qc}>
        <AuthProvider service={service}>
          <Who />
        </AuthProvider>
      </QueryClientProvider>,
    );
    expect(await screen.findByText("a@clinic.org")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "out" }));
    expect(await screen.findByText("signed out")).toBeInTheDocument();
    expect(qc.getQueryData(["secret"])).toBeUndefined();
  });
});
