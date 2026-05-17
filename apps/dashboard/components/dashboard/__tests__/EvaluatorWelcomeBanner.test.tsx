/**
 * Phase 4 Task 4C — evaluator welcome banner.
 *
 * The /api/auth/email/confirm route 303-redirects magic-link visitors
 * to /dashboard?welcome=email. The dashboard renders this banner when
 * that query is present so first-time evaluators see an honest
 * "you're in a seeded demo tenant, here's what you can do" panel
 * before the rest of the dashboard surfaces appear.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { EvaluatorWelcomeBanner } from "../EvaluatorWelcomeBanner";

describe("EvaluatorWelcomeBanner", () => {
  it("renders nothing when source is undefined or unknown", () => {
    const { container } = render(<EvaluatorWelcomeBanner source={undefined} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders the email-evaluator copy when source='email'", () => {
    render(<EvaluatorWelcomeBanner source="email" tenantDisplayName="WormBase SaaS Demo" />);
    const banner = screen.getByTestId("evaluator-welcome-banner");
    expect(banner).toBeInTheDocument();
    expect(banner.textContent).toContain("WormBase SaaS Demo");
    expect(banner.textContent?.toLowerCase()).toContain("magic link");
  });

  it("falls back gracefully when no tenant display name is provided", () => {
    render(<EvaluatorWelcomeBanner source="email" />);
    expect(screen.getByTestId("evaluator-welcome-banner")).toBeInTheDocument();
  });

  it("ignores unrecognized source codes (forward-compat)", () => {
    const { container } = render(
      <EvaluatorWelcomeBanner source="unknown-source" />,
    );
    expect(container.firstChild).toBeNull();
  });
});
