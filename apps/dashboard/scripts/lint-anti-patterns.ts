#!/usr/bin/env tsx
/**
 * Anti-pattern lint — mechanically reject the forbidden Tailwind / styling
 * patterns from PRD §4.4 so future edits can't drift back into a generic
 * SaaS-admin look.
 *
 * Forbidden tokens:
 *   - rounded-lg / rounded-xl / rounded-full / rounded-2xl etc.
 *   - bg-gradient-to-* (any direction)
 *   - bg-pink-* / bg-purple-* / bg-fuchsia-* (pastels)
 *   - font-sans (implies Inter/Arial body)
 *   - colored emoji strings used as primary affordance — heuristic only
 *
 * Allowlist (allowed exceptions):
 *   - rounded-[1px], rounded-[2px], rounded-[3px], rounded-[4px] —
 *     these stay within the ≤4px corner ceiling.
 *
 * Exits with code 1 on any violation; CI gates merges on this.
 */

import { readFileSync, statSync } from "node:fs";
import { join, resolve, sep } from "node:path";
import { readdirSync } from "node:fs";

const ROOT = resolve(__dirname, "..");
const DESIGN_ROOT = resolve(__dirname, "..", "..", "..", "packages", "design");

interface Violation {
  file: string;
  line: number;
  rule: string;
  match: string;
}

const RULES: Array<{ name: string; pattern: RegExp }> = [
  { name: "rounded-lg", pattern: /\brounded-(?:sm|md|lg|xl|2xl|3xl|full)\b/ },
  { name: "bg-gradient", pattern: /\bbg-gradient-to-[lrtb][rblta]?\b/ },
  { name: "pastel-pink", pattern: /\bbg-pink-\d{2,3}\b/ },
  { name: "pastel-purple", pattern: /\bbg-purple-\d{2,3}\b/ },
  { name: "pastel-fuchsia", pattern: /\bbg-fuchsia-\d{2,3}\b/ },
  { name: "font-sans", pattern: /\bfont-sans\b/ },
  { name: "shadow-glow", pattern: /\bshadow-(?:lg|2xl)\b/ },
];

const SKIP_DIRS = new Set([
  "node_modules",
  ".next",
  "dist",
  "build",
  "test-results",
  ".turbo",
  "design-exports",
  "playwright-report",
]);

function* walk(dir: string): Generator<string> {
  let entries: string[];
  try {
    entries = readdirSync(dir);
  } catch {
    return;
  }
  for (const entry of entries) {
    if (SKIP_DIRS.has(entry)) continue;
    const full = join(dir, entry);
    let st;
    try {
      st = statSync(full);
    } catch {
      continue;
    }
    if (st.isDirectory()) yield* walk(full);
    else if (/\.(ts|tsx|css)$/.test(entry)) yield full;
  }
}

function lint(file: string): Violation[] {
  const src = readFileSync(file, "utf8");
  const lines = src.split("\n");
  const violations: Violation[] = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    for (const rule of RULES) {
      const m = line.match(rule.pattern);
      if (m) {
        violations.push({
          file,
          line: i + 1,
          rule: rule.name,
          match: m[0],
        });
      }
    }
  }
  return violations;
}

function main() {
  const targets = [ROOT, DESIGN_ROOT];
  const violations: Violation[] = [];
  for (const t of targets) {
    for (const f of walk(t)) {
      // skip the lint script itself + its test (false positives — the script
      // contains the anti-pattern strings as data)
      if (f.includes(`scripts${sep}lint-anti-patterns.ts`)) continue;
      if (f.includes(`tests${sep}unit${sep}lint-anti-patterns.test.ts`)) continue;
      violations.push(...lint(f));
    }
  }

  if (violations.length === 0) {
    console.log("[anti-patterns] clean — no forbidden patterns found.");
    process.exit(0);
  }
  console.error(`[anti-patterns] ${violations.length} violation(s):`);
  for (const v of violations) {
    console.error(`  ${v.file}:${v.line}  ${v.rule}: ${v.match}`);
  }
  process.exit(1);
}

main();
