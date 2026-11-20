import { describe, expect, it } from "vitest";
import { loginUrl, readNext, withNext } from "./next";

describe("next param", () => {
  it("accepts same-origin paths", () => {
    expect(readNext("?next=%2Fsessions%2Fabc")).toBe("/sessions/abc");
    expect(readNext("?next=%2Fsessions%2Fnew%3Fa%3D1")).toBe("/sessions/new?a=1");
  });
  it("rejects open redirects and junk, defaulting to /", () => {
    for (const bad of ["//evil.com", "https://evil.com", "/\\evil.com", "javascript:alert(1)", "", "x"]) {
      expect(readNext(`?next=${encodeURIComponent(bad)}`)).toBe("/");
    }
    expect(readNext("")).toBe("/");
  });
  it("builds login URLs and carries next across links", () => {
    expect(loginUrl("/sessions/abc", "?x=1")).toBe("/login?next=%2Fsessions%2Fabc%3Fx%3D1");
    expect(loginUrl("/", "")).toBe("/login");
    expect(withNext("/signup", "?next=%2Fsettings")).toBe("/signup?next=%2Fsettings");
    expect(withNext("/signup", "")).toBe("/signup");
  });
});
