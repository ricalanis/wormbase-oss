import { test, expect } from "@playwright/test";

test.describe("landing page", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
  });

  test("renders the WormBase headline", async ({ page }) => {
    const heading = page.getByRole("heading", { level: 1 });
    await expect(heading).toContainText("WormBase");
    await expect(heading).toContainText(
      /Institutional AI for your company.{1,4}s data and processes/
    );
  });

  test("renders the tagline", async ({ page }) => {
    await expect(
      page.getByText(
        /install on monday\. by friday it has mapped your data, learned your processes/i
      )
    ).toBeVisible();
  });

  test("renders the WormMark monogram component (Phase 1B brand asset)", async ({ page }) => {
    const mark = page.getByTestId("hero-wormmark").locator("svg");
    await expect(mark).toBeVisible();
    // React serializes boolean attributes; confirm presence + value="true"
    await expect(mark).toHaveAttribute("data-wormmark", "true");
    await expect(mark).toHaveAttribute("viewBox", "0 0 300 300");
    // Arched WORMBASE wordmark inside the seal
    await expect(mark.locator("textPath")).toHaveText("WORMBASE");
  });

  test("primary CTA is present and clickable", async ({ page }) => {
    const cta = page.getByTestId("create-workspace");
    await expect(cta).toBeVisible();
    await expect(cta).toHaveText(/create demo workspace/i);
    await cta.click();
    await expect(page).toHaveURL(/\/onboarding$/);
  });

  test("does NOT contain forbidden SaaS-ish decorations", async ({ page }) => {
    // Anti-patterns per PRD §4.4: no testimonial cards, no feature grid,
    // no emoji reactions as interface.
    await expect(page.getByText(/testimonial/i)).toHaveCount(0);
    await expect(page.getByText(/features/i)).toHaveCount(0);
  });

  // Phase 4A — new sections beneath the hero. The hero contract above is
  // unchanged; these assertions pin the new architecture / arc / pricing /
  // signup sections that 4B / 4C / 4D will deepen.

  test("renders the wire-replay viewer above the fold (Phase 4B)", async ({ page }) => {
    // Phase 4B replaced the static placeholder with a real SSR replay
    // viewer: thread scaffold, hash-receipt footer (with terminal hash
    // + tenant slug), and a Replay-again button that re-fires the SSR
    // replay against the same fixed `until_ts` window.
    await expect(page.getByTestId("hero-demo")).toBeVisible();
    await expect(page.getByTestId("hero-demo-receipt")).toBeVisible();
    await expect(page.getByTestId("hero-demo-replay-again")).toBeVisible();
    // No placeholder marker — 4B owns the surface now.
    await expect(page.getByTestId("hero-demo-placeholder")).toHaveCount(0);
  });

  test("renders the clickable 6-agent architecture diagram", async ({ page }) => {
    await expect(page.getByTestId("architecture-section")).toBeVisible();
    for (const id of ["lake", "identity", "chat", "process", "research", "governance"]) {
      await expect(page.getByTestId(`agent-node-${id}`)).toBeVisible();
    }
  });

  test("clicking an agent node opens a modal with reactivities", async ({ page }) => {
    await page.getByTestId("agent-node-lake").click();
    const modal = page.getByTestId("agent-modal");
    await expect(modal).toBeVisible();
    await expect(modal.getByTestId("agent-modal-reactivities")).toBeVisible();
    await page.getByTestId("agent-modal-close").click();
    await expect(modal).not.toBeVisible();
  });

  test("renders the 5-beat 'how it works' arc", async ({ page }) => {
    for (const slug of ["connect", "grow", "build", "produce", "self-improve"]) {
      await expect(page.getByTestId(`how-it-works-beat-${slug}`)).toBeVisible();
    }
  });

  test("renders three real pricing tiers (Free / Pro / Enterprise) with working CTAs", async ({ page }) => {
    for (const id of ["free", "pro", "enterprise"]) {
      await expect(page.getByTestId(`pricing-tier-${id}`)).toBeVisible();
      const cta = page.getByTestId(`pricing-cta-${id}`);
      await expect(cta).toBeVisible();
      const href = await cta.getAttribute("href");
      expect(href).toBeTruthy();
    }
    // Free CTA → /onboarding (single signup wire, not bifurcated by pricing).
    await expect(page.getByTestId("pricing-cta-free")).toHaveAttribute(
      "href",
      "/onboarding",
    );
    // Enterprise CTA → mailto: contact-sales.
    const entHref = await page
      .getByTestId("pricing-cta-enterprise")
      .getAttribute("href");
    expect(entHref?.toLowerCase().startsWith("mailto:")).toBe(true);
  });

  test("standalone /pricing route renders the same tiers", async ({ page }) => {
    await page.goto("/pricing");
    for (const id of ["free", "pro", "enterprise"]) {
      await expect(page.getByTestId(`pricing-tier-${id}`)).toBeVisible();
    }
    // Masthead links back home so direct visitors can navigate.
    await expect(page.getByTestId("pricing-page-home")).toHaveAttribute(
      "href",
      "/",
    );
  });

  test("signup section: primary disabled, secondary points at /onboarding", async ({ page }) => {
    await expect(page.getByTestId("signup-primary")).toBeDisabled();
    await expect(page.getByTestId("signup-secondary")).toHaveAttribute(
      "href",
      "/onboarding",
    );
  });
});
