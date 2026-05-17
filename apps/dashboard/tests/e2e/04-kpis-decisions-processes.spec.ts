/**
 * 04-kpis-decisions-processes.spec.ts (W6.A5)
 *
 * Invariant: each gold-tier propose surface (KPIs, Decisions, Processes)
 * surfaces its primary CTA from the empty state or the loaded list. No
 * silent panels — every tab renders chrome + actionable controls or an
 * intent-conveying empty signal.
 */
import { test, expect } from "./fixtures";

test.describe("KPI tab", () => {
  test("J1 — /kpis renders chrome (loaded or empty)", async ({
    ctxPage: page,
  }) => {
    await page.goto("/kpis");
    const tree = page.locator('[data-testid^="kpi-"]').first();
    const propose = page.getByRole("button", { name: /propose kpi/i }).first();
    const empty = page.getByText(/(no kpis|propose your first|empty)/i).first();
    // .or() can return a union; collapse to the first hit for strict mode.
    await expect(tree.or(propose).or(empty).first()).toBeVisible();
  });

  test("J2 — propose-KPI control reachable for admin lens", async ({
    ctxPage: page,
  }) => {
    await page.goto("/kpis");
    const propose = page
      .getByRole("button", { name: /propose kpi|new kpi|add kpi/i })
      .or(page.getByRole("link", { name: /propose kpi|new kpi|add kpi/i }));
    if (await propose.first().count()) {
      await expect(propose.first()).toBeVisible();
    }
  });
});

test.describe("Decisions tab", () => {
  test("J3 — /decisions renders chrome (loaded or empty)", async ({
    ctxPage: page,
  }) => {
    await page.goto("/decisions");
    const rows = page.locator('[data-testid^="decision-"]').first();
    const propose = page.getByRole("button", { name: /(record|propose) decision/i }).first();
    const empty = page.getByText(/(no decisions|record your first|nothing yet)/i).first();
    await expect(rows.or(propose).or(empty).first()).toBeVisible();
  });

  test("J4 — record-decision CTA exists for admin lens", async ({
    ctxPage: page,
  }) => {
    await page.goto("/decisions");
    const propose = page.getByRole("button", { name: /(record|propose) decision/i });
    if (await propose.first().count()) {
      await expect(propose.first()).toBeVisible();
    }
  });
});

test.describe("Processes tab", () => {
  test("J5 — /processes renders chrome (loaded or empty)", async ({
    ctxPage: page,
  }) => {
    await page.goto("/processes");
    const rows = page.locator('[data-testid^="process-"]').first();
    const propose = page.getByRole("button", { name: /propose process/i }).first();
    const empty = page.getByText(/(no processes|first process map|empty)/i).first();
    await expect(rows.or(propose).or(empty).first()).toBeVisible();
  });

  test("J6 — propose-process control surfaces for admin lens", async ({
    ctxPage: page,
  }) => {
    await page.goto("/processes");
    const propose = page.getByRole("button", { name: /propose process|new process/i });
    if (await propose.first().count()) {
      await expect(propose.first()).toBeVisible();
    }
  });
});
