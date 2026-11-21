import { ESLint } from "eslint";
import { describe, expect, it } from "vitest";

async function lint(code: string) {
  const eslint = new ESLint({ cwd: process.cwd() });
  const [res] = await eslint.lintText(code, { filePath: "src/probe.tsx" });
  return res.messages;
}

describe("lint rules", () => {
  it("fails dangerouslySetInnerHTML", async () => {
    const msgs = await lint(
      'export const A = ({ h }: { h: string }) => <div dangerouslySetInnerHTML={{ __html: h }} />;\n',
    );
    expect(msgs.some((m) => m.ruleId === "no-restricted-syntax" && m.severity === 2)).toBe(true);
  });

  it("fails an a11y violation (img without alt)", async () => {
    const msgs = await lint('export const A = () => <img src="/x.png" />;\n');
    expect(msgs.some((m) => m.ruleId === "jsx-a11y/alt-text")).toBe(true);
  });

  it("passes clean code", async () => {
    const msgs = await lint('export const A = () => <p>hello</p>;\n');
    expect(msgs).toEqual([]);
  });
});
