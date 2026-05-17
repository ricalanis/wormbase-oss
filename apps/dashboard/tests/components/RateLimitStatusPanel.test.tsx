/**
 * W3-B (2026-05-07) — RateLimitStatusPanel component tests.
 *
 * Pins:
 *   - renders nothing for non-WhatsApp platforms (Slack/Discord/Teams)
 *   - reads `policy:whatsapp_rate_limit` events via getPolicyAppliedEvents
 *   - empty state when no events recorded ("the bot has stayed under
 *     the rate limit")
 *   - fill bar shows "5 / 5 (idle)" by default; "0 / 5 (throttle in
 *     progress)" when a recent event lands
 *   - configured rate disclosure (5 / min default + env knob copy)
 *   - one row per recent backoff event, with rule/timestamp/scope
 */
import { afterEach, beforeEach, describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import type { PolicyAppliedEvent } from "../../lib/ledger-client.types";

const mockGetPolicyAppliedEvents = vi.fn();

vi.mock("../../lib/ledger-client", () => ({
  getPolicyAppliedEvents: (...args: unknown[]) =>
    mockGetPolicyAppliedEvents(...args),
}));

import { RateLimitStatusPanel } from "../../components/channels/RateLimitStatusPanel";

const COMPANY = "a8989ece-b38a-5811-9625-327a79a65f90";
const CHANNEL = "5511999998888@s.whatsapp.net";

function event(over: Partial<PolicyAppliedEvent> = {}): PolicyAppliedEvent {
  return {
    hash: "abc123def456",
    ts: "2026-05-07T18:00:00Z",
    policyName: "policy:whatsapp_rate_limit",
    rule: "rate_limit_persistent_throttle",
    rationale:
      "WhatsApp send: persistent 429 throttle after 3 backoff retries",
    appliesTo: {
      scope: "adapter",
      platform: "whatsapp",
      bot_phone: "+5511999998888",
      tenant_id: "baseworm",
    },
    botPhone: "+5511999998888",
    outcome: "applied",
    receipt: {
      hash: "abc123def456",
      source: "policy-applied-projection",
      owner: "system",
      classification: "internal",
    },
    ...over,
  };
}

describe("RateLimitStatusPanel", () => {
  beforeEach(() => {
    mockGetPolicyAppliedEvents.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders nothing for non-WhatsApp platforms", async () => {
    mockGetPolicyAppliedEvents.mockResolvedValueOnce([]);
    const ui = await RateLimitStatusPanel({
      companyId: COMPANY,
      channelId: "C12345",
      platform: "slack",
    });
    const { container } = render(<>{ui}</>);
    expect(container.firstChild).toBeNull();
    // The accessor should not even be called when platform isn't whatsapp.
    expect(mockGetPolicyAppliedEvents).not.toHaveBeenCalled();
  });

  it("renders the empty state when no throttling events have been recorded", async () => {
    mockGetPolicyAppliedEvents.mockResolvedValueOnce([]);
    const ui = await RateLimitStatusPanel({
      companyId: COMPANY,
      channelId: CHANNEL,
      platform: "whatsapp",
    });
    render(<>{ui}</>);
    const empty = screen.getByTestId("rate-limit-events-empty");
    expect(empty).toBeInTheDocument();
    expect(empty.textContent).toMatch(/No throttling events recorded/);
    expect(empty.textContent).toMatch(/stayed under the rate limit/);
    // Idle state: 5 / 5 tokens, green fill.
    const label = screen.getByTestId("rate-limit-fill-label");
    expect(label.textContent).toMatch(/5 \/ 5 tokens available/);
    const stateLabel = screen.getByTestId("rate-limit-fill-state");
    expect(stateLabel.textContent?.toLowerCase()).toMatch(
      /idle, not throttling/,
    );
    expect(
      screen
        .getByTestId("rate-limit-status-section")
        .getAttribute("data-throttle-active"),
    ).toBe("false");
  });

  it("surfaces the configured-rate copy + env knob", async () => {
    mockGetPolicyAppliedEvents.mockResolvedValueOnce([]);
    const ui = await RateLimitStatusPanel({
      companyId: COMPANY,
      channelId: CHANNEL,
      platform: "whatsapp",
    });
    render(<>{ui}</>);
    const section = screen.getByTestId("rate-limit-status-section");
    expect(section.textContent).toMatch(/5 \/ min/);
    expect(section.textContent).toMatch(/WORMBASE_WHATSAPP_RATE_PER_MIN_/);
  });

  it("renders one row per recent backoff event with rule + scope + rationale", async () => {
    const ts = new Date(Date.now() - 60_000).toISOString();
    mockGetPolicyAppliedEvents.mockResolvedValueOnce([
      event({ hash: "h1", ts, rule: "rate_limit_persistent_throttle" }),
      event({
        hash: "h2",
        ts: new Date(Date.now() - 30 * 60_000).toISOString(),
        rule: "rate_limit_persistent_throttle",
      }),
    ]);
    const ui = await RateLimitStatusPanel({
      companyId: COMPANY,
      channelId: CHANNEL,
      platform: "whatsapp",
    });
    render(<>{ui}</>);
    const list = screen.getByTestId("rate-limit-events-list");
    expect(list).toBeInTheDocument();
    expect(screen.getByTestId("rate-limit-event-row-h1")).toBeInTheDocument();
    expect(screen.getByTestId("rate-limit-event-row-h2")).toBeInTheDocument();
    // Both rows carry the rule + scope.
    expect(
      screen.getByTestId("rate-limit-event-row-h1").textContent,
    ).toMatch(/rate_limit_persistent_throttle/);
    expect(
      screen.getByTestId("rate-limit-event-row-h1").textContent,
    ).toMatch(/\+5511999998888/);
    expect(
      screen.getByTestId("rate-limit-event-row-h1").textContent,
    ).toMatch(/persistent 429 throttle/);
  });

  it("flags throttle-in-progress when most-recent event is within 5 minutes", async () => {
    const ts = new Date(Date.now() - 60_000).toISOString();
    mockGetPolicyAppliedEvents.mockResolvedValueOnce([event({ ts })]);
    const ui = await RateLimitStatusPanel({
      companyId: COMPANY,
      channelId: CHANNEL,
      platform: "whatsapp",
    });
    render(<>{ui}</>);
    const section = screen.getByTestId("rate-limit-status-section");
    expect(section.getAttribute("data-throttle-active")).toBe("true");
    expect(screen.getByTestId("rate-limit-fill-label").textContent).toMatch(
      /0 \/ 5 tokens available/,
    );
    expect(
      screen.getByTestId("rate-limit-fill-state").textContent?.toLowerCase(),
    ).toMatch(/throttle in progress/);
  });

  it("shows idle state when most-recent event is older than 5 minutes", async () => {
    const ts = new Date(Date.now() - 30 * 60_000).toISOString();
    mockGetPolicyAppliedEvents.mockResolvedValueOnce([event({ ts })]);
    const ui = await RateLimitStatusPanel({
      companyId: COMPANY,
      channelId: CHANNEL,
      platform: "whatsapp",
    });
    render(<>{ui}</>);
    const section = screen.getByTestId("rate-limit-status-section");
    expect(section.getAttribute("data-throttle-active")).toBe("false");
    expect(
      screen.getByTestId("rate-limit-fill-state").textContent?.toLowerCase(),
    ).toMatch(/idle, not throttling/);
  });

  it("queries the accessor with the WhatsApp policy name and a bounded limit", async () => {
    mockGetPolicyAppliedEvents.mockResolvedValueOnce([]);
    await RateLimitStatusPanel({
      companyId: COMPANY,
      channelId: CHANNEL,
      platform: "whatsapp",
    });
    expect(mockGetPolicyAppliedEvents).toHaveBeenCalledTimes(1);
    const [companyId, policyName, opts] =
      mockGetPolicyAppliedEvents.mock.calls[0];
    expect(companyId).toBe(COMPANY);
    expect(policyName).toBe("policy:whatsapp_rate_limit");
    // Cap is small (~10) so the panel never fans out unbounded.
    expect(opts).toEqual({ limit: 10 });
  });
});
