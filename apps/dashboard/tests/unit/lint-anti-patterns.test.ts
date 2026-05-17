import { describe, it, expect } from "vitest";
import { execSync } from "node:child_process";
import path from "node:path";

const SCRIPT = path.resolve(__dirname, "..", "..", "scripts", "lint-anti-patterns.ts");

describe("anti-pattern lint script", () => {
  it("runs to completion against the current codebase (zero violations)", () => {
    let stdout = "";
    let exitCode = 0;
    try {
      stdout = execSync(`pnpm dlx tsx ${SCRIPT}`, {
        cwd: path.resolve(__dirname, "..", ".."),
        encoding: "utf8",
        stdio: "pipe",
      });
    } catch (err: unknown) {
      const e = err as { status?: number; stdout?: string; stderr?: string };
      exitCode = e.status ?? 1;
      stdout = (e.stdout ?? "") + (e.stderr ?? "");
    }
    expect(exitCode).toBe(0);
    expect(stdout).toMatch(/clean — no forbidden patterns found/);
  }, 30_000);
});
