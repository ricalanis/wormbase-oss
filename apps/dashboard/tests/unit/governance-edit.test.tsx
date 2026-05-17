/**
 * Governance edit tests — exercise the inline owner-change UI on
 * DomainCardGrid and inline classification-change UI on PolicyTable.
 *
 * These tests pin the optimistic-UI contract:
 *   1. Click → state flips immediately (audience sees change).
 *   2. POST is dispatched with the right body to the right route.
 *   3. On API failure, the optimistic value reverts.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

import { DomainCardGrid } from "../../components/domains/DomainCardGrid";
import { PolicyTable } from "../../components/policies/PolicyTable";
import type {
  DomainRow,
  PersonRow,
  PolicyRow,
} from "../../lib/ledger-client.types";

const domains: DomainRow[] = [
  {
    domainId: "d_finance",
    name: "Finance",
    owner: "ricardo-bot",
    classificationDefault: "restricted",
    resourceCount: 0,
    receipt: {
      hash: "fff0",
      source: "domains-projection",
      owner: "ricardo-bot",
      classification: "restricted",
    },
  },
];

const people: PersonRow[] = [
  {
    personId: "p_alice",
    displayName: "alice-bot",
    email: null,
    position: "pm",
    status: "active",
    tenancyRole: null,
    identities: [],
    domainGrantCount: 0,
    resourceGrantCount: 0,
    roles: ["pm"],
    ownedDomains: [],
    ownedResources: [],
    receipt: {
      hash: "alice000",
      source: "people-projection",
      owner: "alice-bot",
      classification: "internal",
    },
  },
  {
    personId: "p_carla",
    displayName: "carla-bot",
    email: null,
    position: "de",
    status: "active",
    tenancyRole: null,
    identities: [],
    domainGrantCount: 0,
    resourceGrantCount: 0,
    roles: ["de"],
    ownedDomains: [],
    ownedResources: [],
    receipt: {
      hash: "carla000",
      source: "people-projection",
      owner: "carla-bot",
      classification: "internal",
    },
  },
];

const policies: PolicyRow[] = [
  {
    policyId: "pii_redaction",
    name: "PII redaction",
    plainLanguage: "redact PII",
    gateImpl: "gates/pii.py",
    scope: "global",
    firesLast7d: 4,
    receipt: {
      hash: "pii00000",
      source: "policy-pack-v1",
      owner: "system",
      classification: "internal",
    },
  },
];

beforeEach(() => {
  vi.unstubAllGlobals();
});

function stubFetch(impl: (url: string, init?: RequestInit) => Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn(impl) as unknown as typeof fetch);
}

describe("DomainCardGrid", () => {
  it("optimistically swaps the owner and POSTs to /api/governance/domain", async () => {
    const calls: { url: string; body: unknown }[] = [];
    stubFetch(async (url, init) => {
      if (init?.method === "POST") {
        calls.push({ url, body: JSON.parse(String(init.body)) });
        return new Response(JSON.stringify({ ok: true }), { status: 200 });
      }
      // GET poll — return same domains
      return new Response(JSON.stringify({ domains }), { status: 200 });
    });

    render(
      <DomainCardGrid
        initialDomains={domains}
        initialPeople={people}
        initialResources={[]}
        currentPersonId={null}
      />,
    );

    // Open the dropdown
    const button = screen.getByTestId("domain-owner-button-d_finance");
    expect(button.textContent).toContain("ricardo-bot");
    fireEvent.click(button);

    // Pick alice-bot
    const pick = screen.getByTestId("domain-owner-pick-d_finance-p_alice");
    await act(async () => {
      fireEvent.click(pick);
    });

    // Optimistic swap
    await waitFor(() => {
      expect(
        screen.getByTestId("domain-owner-button-d_finance").textContent,
      ).toContain("alice-bot");
    });

    // POST dispatched with the right body
    const post = calls.find((c) => c.url === "/api/governance/domain");
    expect(post).toBeTruthy();
    expect(post!.body).toEqual({
      domain_id: "d_finance",
      owner_person_id: "alice-bot",
    });
  });

  it("reverts the optimistic owner on API error", async () => {
    stubFetch(async (_url, init) => {
      if (init?.method === "POST") {
        return new Response("nope", { status: 500 });
      }
      return new Response(JSON.stringify({ domains }), { status: 200 });
    });

    render(
      <DomainCardGrid
        initialDomains={domains}
        initialPeople={people}
        initialResources={[]}
        currentPersonId={null}
      />,
    );
    const button = screen.getByTestId("domain-owner-button-d_finance");
    fireEvent.click(button);
    const pick = screen.getByTestId("domain-owner-pick-d_finance-p_carla");
    await act(async () => {
      fireEvent.click(pick);
    });

    // Eventually reverts back to ricardo-bot.
    await waitFor(() => {
      expect(
        screen.getByTestId("domain-owner-button-d_finance").textContent,
      ).toContain("ricardo-bot");
    });
  });
});

describe("PolicyTable", () => {
  it("inline-edits classification with an optimistic UI + POST", async () => {
    const calls: { url: string; body: unknown }[] = [];
    stubFetch(async (url, init) => {
      if (init?.method === "POST") {
        calls.push({ url, body: JSON.parse(String(init.body)) });
        return new Response(JSON.stringify({ ok: true }), { status: 200 });
      }
      return new Response(JSON.stringify({ policies }), { status: 200 });
    });

    render(<PolicyTable initialPolicies={policies} initialDomains={domains} />);

    const select = screen.getByTestId(
      "policy-classification-pii_redaction",
    ) as HTMLSelectElement;
    expect(select.value).toBe("internal");

    await act(async () => {
      fireEvent.change(select, { target: { value: "pii" } });
    });

    await waitFor(() => {
      const post = calls.find((c) => c.url === "/api/governance/policy");
      expect(post).toBeTruthy();
      expect(post!.body).toEqual({
        policy_id: "pii_redaction",
        classification: "pii",
      });
    });
  });
});
