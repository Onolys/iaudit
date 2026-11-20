import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mockBackend } from "../../mocks/server";
import { here, renderApp } from "../../test/renderApp";
import { MAX_AUDIO_BYTES } from "./precheck";
import { getJob } from "./uploader";

const USER = { email: "rater@clinic.org", verified: true };
const mp3 = () => new File([new Uint8Array(100)], "visit.mp3", { type: "audio/mpeg" });

let seconds = 15 * 60;
beforeEach(() => {
  seconds = 15 * 60;
  // jsdom never loads media metadata; a stand-in that reports `seconds`.
  vi.stubGlobal(
    "Audio",
    class {
      duration = seconds;
      onloadedmetadata: (() => void) | null = null;
      onerror: (() => void) | null = null;
      preload = "";
      set src(_: string) {
        queueMicrotask(() => this.onloadedmetadata?.());
      }
      removeAttribute() {}
    },
  );
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:x", revokeObjectURL: () => {} }));
});
afterEach(() => vi.unstubAllGlobals());

async function open(path = "/sessions/new") {
  const r = renderApp(path, { user: USER });
  await screen.findByRole("heading", { level: 1, name: "New session" });
  return r;
}
const choose = (f: File) => userEvent.upload(screen.getByLabelText(/audio recording/i), f);

describe("New session form", () => {
  it("has audio, language (auto default, 3 options), optional title and no Advanced section", async () => {
    await open();
    const lang = screen.getByLabelText("Language") as HTMLSelectElement;
    expect(lang.value).toBe("auto");
    expect(Array.from(lang.options).map((o) => o.value)).toEqual(["auto", "en-US", "en-GB"]);
    expect(screen.getByLabelText(/title/i)).toBeInTheDocument();
    expect(screen.queryByText(/advanced/i)).toBeNull();
    expect(screen.getByRole("button", { name: /start/i })).toBeDisabled();
  });

  it("blocks an oversized file with the export message", async () => {
    await open();
    const big = new File([new Uint8Array(1)], "big.wav", { type: "audio/wav" });
    Object.defineProperty(big, "size", { value: MAX_AUDIO_BYTES + 1 });
    await choose(big);
    expect(await screen.findByRole("alert")).toHaveTextContent("Export it as m4a or mp3");
    expect(screen.getByRole("button", { name: /start/i })).toBeDisabled();
  });

  it("blocks a recording over 25 minutes and warns under 10 from the audio metadata", async () => {
    await open();
    seconds = 26 * 60;
    await choose(mp3());
    expect(await screen.findByRole("alert")).toHaveTextContent("longer than 25 minutes");
    expect(screen.getByRole("button", { name: /start/i })).toBeDisabled();
    seconds = 5 * 60;
    await choose(new File([new Uint8Array(100)], "short.mp3", { type: "audio/mpeg" }));
    expect(await screen.findByRole("status")).toHaveTextContent("under 10 minutes");
    expect(screen.getByRole("button", { name: /start/i })).toBeEnabled();
  });

  it("creates the session, requests the audio URL, registers the upload and navigates at once", async () => {
    const { router } = await open();
    await userEvent.type(screen.getByLabelText(/title/i), "Visit 3");
    await userEvent.selectOptions(screen.getByLabelText("Language"), "en-GB");
    await choose(mp3());
    await userEvent.click(screen.getByRole("button", { name: /start/i }));
    await waitFor(() => expect(here(router)).toMatch(/^\/sessions\/(?!new$)[^/]+$/));
    const id = here(router).split("/")[2]!;
    expect(getJob(id)).toBeDefined();
    expect(mockBackend.getSession("u_rater_clinic_org", id).status).toBe("uploading");
  });

  it("prefills the title from ?from=<id>", async () => {
    const id = mockBackend.createSession("u_rater_clinic_org", { title: "Old visit" }).session.id;
    await open(`/sessions/new?from=${id}`);
    await waitFor(() => expect(screen.getByLabelText(/title/i)).toHaveValue("Old visit"));
  });
});
