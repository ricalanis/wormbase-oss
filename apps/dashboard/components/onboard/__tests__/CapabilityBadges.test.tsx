/**
 * CapabilityBadges component tests — Onboarding Sub-wave B (2026-05-30).
 *
 * Generalized from L3's StrategyStatusBanner; same accent palette,
 * same testid pattern. The component is consumed across every
 * /onboard/* tab + the universal /status + /logs views so its
 * behavior MUST stay stable.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { CapabilityBadges } from "../CapabilityBadges";

describe("CapabilityBadges", () => {
  it("renders the production accent for production status", () => {
    render(
      <CapabilityBadges
        kind="connector"
        id="stripe"
        status="production"
        capabilities={["discover", "profile", "sample"]}
        statusNote="Stripe is wired against the real platform."
      />,
    );
    expect(
      screen.getByTestId("capability-status-connector-stripe-production"),
    ).toHaveTextContent("production");
    expect(screen.getByTestId("capability-list-connector-stripe")).toHaveTextContent(
      "discover · profile · sample",
    );
    expect(screen.getByTestId("capability-note-connector-stripe")).toHaveTextContent(
      "Stripe is wired against the real platform.",
    );
  });

  it("renders the configured-stubbed accent for L3-style stubs", () => {
    render(
      <CapabilityBadges
        kind="connector"
        status="configured-stubbed"
        statusNote="Env knob set; impl is a no-op."
      />,
    );
    expect(
      screen.getByTestId("capability-status-connector-stubbed"),
    ).toHaveTextContent("configured · stubbed");
  });

  it("renders the disabled accent without capabilities or note", () => {
    render(<CapabilityBadges kind="domain" status="disabled" />);
    expect(
      screen.getByTestId("capability-status-domain-disabled"),
    ).toHaveTextContent("disabled");
    // No capabilities + no note → only the status pill renders
    expect(screen.queryByTestId("capability-list-domain")).toBeNull();
    expect(screen.queryByTestId("capability-note-domain")).toBeNull();
  });

  it("renders the unknown accent for kinds without a wired probe", () => {
    render(
      <CapabilityBadges
        kind="agent"
        id="agent-7"
        status="unknown"
        statusNote="Probe not yet implemented for agents."
      />,
    );
    expect(
      screen.getByTestId("capability-status-agent-agent-7-unknown"),
    ).toHaveTextContent("unknown");
  });

  it("preserves capability-honesty: failed renders the failed accent", () => {
    render(
      <CapabilityBadges
        kind="channel"
        id="slack-install-1"
        status="failed"
        statusNote="OAuth grant was revoked."
      />,
    );
    expect(
      screen.getByTestId("capability-status-channel-slack-install-1-failed"),
    ).toHaveTextContent("failed");
  });
});
