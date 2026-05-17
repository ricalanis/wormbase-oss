import { test, expect } from "@playwright/test";

// Phase 4 wired the ramp gauges to the live ledger client; values now come
// from the fixture seed in apps/dashboard/lib/demo-fixture.ts. Keys are the
// canonical RampAxisKey enum.
const EXPECTED = [
  { key: "ontology", label: "Ontology" },
  { key: "schema", label: "Schema" },
  { key: "business_definitions", label: "Business Definitions" },
  { key: "kpi_relational", label: "KPI Relational" },
  { key: "conversational", label: "Conversational" },
  { key: "operational", label: "Operational" },
];

test.describe("dashboard · ramp gauges", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/dashboard");
  });

  test("six named gauges render with non-zero data-value", async ({ page }) => {
    const container = page.getByTestId("ramp-gauges");
    await expect(container).toBeVisible();
    for (const axis of EXPECTED) {
      const gauge = page.getByTestId(`gauge-${axis.key}`);
      await expect(gauge).toBeVisible();
      const v = await gauge.getAttribute("data-value");
      expect(Number(v)).toBeGreaterThan(0);
    }
  });

  test("gauges expose meter role with correct aria-valuenow after mount", async ({ page }) => {
    await page.waitForTimeout(1500);
    for (const axis of EXPECTED) {
      const meter = page.getByRole("meter", { name: axis.label });
      const v = Number(await meter.getAttribute("aria-valuenow"));
      expect(v).toBeGreaterThan(0);
      expect(v).toBeLessThanOrEqual(100);
    }
  });

  test("each gauge has a Receipt below proving it's ledger-derived", async ({ page }) => {
    for (const axis of EXPECTED) {
      const gauge = page.getByTestId(`gauge-${axis.key}`);
      await expect(gauge.locator("[data-receipt]")).toBeVisible();
    }
  });
});

// ─── P2 · knowledge-ramp counter gauges ──────────────────────────────────
// Three integer-counted gauges (ontology / conversational / relational)
// rendered alongside the six-axis arc gauges above. Each tile is a
// deep-link to /trace pre-filtered to the matching entry kind.

const KNOWLEDGE_RAMP_AXES = [
  { axis: "ontology", traceFilter: "concept_" },
  { axis: "conversational", traceFilter: "chat_received" },
  { axis: "relational", traceFilter: "kpi_" },
];

test.describe("dashboard · knowledge-ramp counter gauges (P2)", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/dashboard");
  });

  test("the knowledge-ramp section is mounted with three gauges", async ({
    page,
  }) => {
    const section = page.getByTestId("knowledge-ramp-section");
    await expect(section).toBeVisible();
    for (const axis of KNOWLEDGE_RAMP_AXES) {
      const gauge = page.getByTestId(`ramp-gauge-${axis.axis}`);
      await expect(gauge).toBeVisible();
      await expect(gauge).toHaveAttribute("data-axis", axis.axis);
      await expect(gauge).toHaveAttribute("data-trace-filter", axis.traceFilter);
    }
  });

  test("each gauge tile deep-links to /trace?kind=<filter>", async ({
    page,
  }) => {
    for (const axis of KNOWLEDGE_RAMP_AXES) {
      const gauge = page.getByTestId(`ramp-gauge-${axis.axis}`);
      const href = await gauge.getAttribute("href");
      expect(href ?? "").toContain("/trace?");
      expect(href ?? "").toContain(`kind=${axis.traceFilter}`);
    }
  });

  test("clicking a gauge navigates to /trace with the kind filter applied", async ({
    page,
  }) => {
    const gauge = page.getByTestId("ramp-gauge-conversational");
    await gauge.click();
    await page.waitForURL(/\/trace\?.*kind=chat_received/);
    // The trace page renders the filter bar with our kind selected.
    const kindText = page.getByTestId("trace-filter-kind-text");
    await expect(kindText).toBeVisible();
  });
});
