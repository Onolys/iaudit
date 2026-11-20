import { describe, expect, it } from "vitest";
import { checkFile, MAX_AUDIO_BYTES } from "./precheck";

const f = (name: string, size = 1000, type = "audio/mpeg") => ({ name, size, type });

describe("checkFile (advisory pre-checks)", () => {
  it("accepts a normal mp3 with a 15 minute duration", () => {
    expect(checkFile(f("a.mp3"), 15 * 60)).toEqual({ blocked: null, warning: null });
  });

  it("blocks over 300 MB with the export message", () => {
    const r = checkFile(f("a.wav", MAX_AUDIO_BYTES + 1, "audio/wav"), 900);
    expect(r.blocked).toBe("This file is over 300 MB. Export it as m4a or mp3 and upload that instead.");
  });

  it("allows exactly 300 MB", () => {
    expect(checkFile(f("a.wav", MAX_AUDIO_BYTES, "audio/wav"), 900).blocked).toBeNull();
  });

  it.each(["a.mp3", "a.WAV", "a.m4a", "a.webm", "a.ogg"])("accepts extension %s", (name) => {
    expect(checkFile(f(name, 10, ""), 900).blocked).toBeNull();
  });

  it("blocks an unsupported extension with an unknown type", () => {
    expect(checkFile(f("notes.pdf", 10, "application/pdf"), 900).blocked).toMatch(/mp3, wav, m4a, webm or ogg/);
    expect(checkFile(f("noext", 10, ""), 900).blocked).toMatch(/mp3, wav, m4a, webm or ogg/);
  });

  it("accepts a known audio MIME alias when the extension is odd", () => {
    expect(checkFile(f("recording", 10, "audio/x-m4a"), 900).blocked).toBeNull();
  });

  it("blocks over 25 minutes", () => {
    expect(checkFile(f("a.mp3"), 25 * 60 + 1).blocked).toBe(
      "This recording is longer than 25 minutes. Upload a shorter one.",
    );
  });

  it("allows exactly 25 minutes and exactly 10 minutes without a warning", () => {
    expect(checkFile(f("a.mp3"), 25 * 60)).toEqual({ blocked: null, warning: null });
    expect(checkFile(f("a.mp3"), 10 * 60)).toEqual({ blocked: null, warning: null });
  });

  it("warns (does not block) under 10 minutes", () => {
    const r = checkFile(f("a.mp3"), 10 * 60 - 1);
    expect(r.blocked).toBeNull();
    expect(r.warning).toMatch(/under 10 minutes/);
  });

  it("does not block or warn when the duration cannot be read", () => {
    expect(checkFile(f("a.mp3"), null)).toEqual({ blocked: null, warning: null });
  });

  it("size block wins over a duration block", () => {
    expect(checkFile(f("a.mp3", MAX_AUDIO_BYTES + 1), 60 * 60).blocked).toMatch(/over 300 MB/);
  });
});
