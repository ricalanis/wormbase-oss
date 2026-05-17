// Headless Playwright screenshotter for the WormBase dashboard.
//
// Usage:
//   node scripts/dashboard-screenshots.mjs <outdir>
//
// Iterates the public dashboard routes, takes a full-page screenshot of
// each, and writes them as <outdir>/<slug>.png. Used by the autonomous
// rehearsal loop to capture before/during/after states around a demo run.

// Run from inside apps/dashboard (pnpm-managed deps live there).
// Dashboard depends on @playwright/test, which re-exports `chromium`.
import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";

const ROUTES = [
  ["/", "root"],
  ["/dashboard", "dashboard"],
  ["/trace", "trace"],
  ["/sources", "sources"],
  ["/activity", "activity"],
  ["/kpis", "kpis"],
  ["/domains", "domains"],
  ["/people", "people"],
  ["/policies", "policies"],
  ["/decisions", "decisions"],
  ["/processes", "processes"],
  ["/system-map", "system-map"],
  ["/research", "research"],
  ["/onboarding", "onboarding"],
];

const BASE = process.env.DASHBOARD_BASE || "http://localhost:3000";
const OUTDIR = resolve(process.argv[2] || "screenshots");

await mkdir(OUTDIR, { recursive: true });

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 2,
});
const page = await context.newPage();

for (const [path, slug] of ROUTES) {
  const url = BASE + path;
  try {
    await page.goto(url, { waitUntil: "networkidle", timeout: 30_000 });
    // Give Next.js a beat to hydrate above-the-fold content.
    await page.waitForTimeout(500);
    const out = resolve(OUTDIR, `${slug}.png`);
    await page.screenshot({ path: out, fullPage: true });
    console.log(`✓ ${slug}\t${out}`);
  } catch (err) {
    console.log(`✗ ${slug}\t${err.message || err}`);
  }
}

await browser.close();
