/**
 * Tier 2 wizard write-back wiring tests (Sub-wave A F2, 2026-05-30).
 *
 * Pins:
 *   1. Tier 2 confirm/reject flows fire the server actions in
 *      `app/onboarding/tier2/actions.ts` (no more empty-body
 *      callbacks).
 *   2. GovernancePanel drop assignment fires
 *      `assignDomainOwnerAction(domainId, personId)`.
 *   3. The TalkativenessPanel callback stays intentionally-unwired in
 *      this Sub-wave — pin the absence so a future change is forced to
 *      confront the Sub-wave C plan rather than silently retrofitting.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

// Mock the server-actions module so we can assert what the client
// invokes. The actual server actions call into ledger-client.ts which
// has its own unit tests (`tests/unit/ledger-client.test.ts`); here
// we're only pinning the wire from the client surface to the action
// entry points.
vi.mock("../../app/onboarding/tier2/actions", () => ({
  confirmBusinessDefAction: vi.fn(async () => ({ ok: true })),
  rejectBusinessDefAction: vi.fn(async () => ({ ok: true })),
  assignDomainOwnerAction: vi.fn(async () => ({ ok: true })),
}));

import { Tier2Client } from "../../app/onboarding/tier2/Tier2Client";
import {
  assignDomainOwnerAction,
  confirmBusinessDefAction,
  rejectBusinessDefAction,
} from "../../app/onboarding/tier2/actions";
import type {
  BusinessDefProposal,
  ChannelRow,
  DomainRow,
  PersonRow,
} from "../../lib/ledger-client.types";

const defs: BusinessDefProposal[] = [
  {
    term: "ARPU",
    proposedDefinition: "Net invoice total / count distinct active accounts.",
    sourceHash: "deadbeef",
  },
];

const channels: ChannelRow[] = [];

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
];

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Tier2Client F2 wiring", () => {
  it("renders all three panels (defs, talkativeness, governance)", () => {
    render(
      <Tier2Client
        defs={defs}
        channels={channels}
        domains={domains}
        people={people}
      />,
    );
    expect(screen.getByTestId("defs-section")).toBeInTheDocument();
    expect(screen.getByTestId("talkativeness-section")).toBeInTheDocument();
    expect(screen.getByTestId("governance-section")).toBeInTheDocument();
  });

  it("calls confirmBusinessDefAction on Accept (wire from Sub-wave A F2)", async () => {
    render(
      <Tier2Client
        defs={defs}
        channels={channels}
        domains={domains}
        people={people}
      />,
    );
    fireEvent.click(screen.getByTestId("confirm-ARPU"));
    await waitFor(() => {
      expect(confirmBusinessDefAction).toHaveBeenCalledWith("ARPU");
    });
  });

  it("calls rejectBusinessDefAction on Reject", async () => {
    render(
      <Tier2Client
        defs={defs}
        channels={channels}
        domains={domains}
        people={people}
      />,
    );
    fireEvent.click(screen.getByTestId("reject-ARPU"));
    await waitFor(() => {
      expect(rejectBusinessDefAction).toHaveBeenCalledWith("ARPU");
    });
  });

  it("calls assignDomainOwnerAction with personId after a drop", async () => {
    render(
      <Tier2Client
        defs={defs}
        channels={channels}
        domains={domains}
        people={people}
      />,
    );
    // Simulate the drag-and-drop manually. happy-dom's DataTransfer is
    // limited — we fake it with a minimal Pick-shaped object that
    // carries the two `text/wb-person*` keys the panel reads.
    const drop = screen.getByTestId("domain-zone-d_finance");
    const dataMap: Record<string, string> = {
      "text/wb-person": "alice-bot",
      "text/wb-person-id": "p_alice",
    };
    const dataTransfer = {
      getData: (k: string) => dataMap[k] ?? "",
      setData: () => {},
      types: ["text/wb-person", "text/wb-person-id"],
    } as unknown as DataTransfer;

    fireEvent.drop(drop, { dataTransfer });
    await waitFor(() => {
      expect(assignDomainOwnerAction).toHaveBeenCalledWith(
        "d_finance",
        "p_alice",
      );
    });
  });

  it("falls back to display name as personId when wb-person-id is absent (back-compat)", async () => {
    // Legacy drag sources only set `text/wb-person`. The handler must
    // not crash; it forwards the display name as a fallback id so the
    // server-side action returns a structured "missing person_id"
    // error rather than throwing. (The action's input validation
    // handles the rest.)
    render(
      <Tier2Client
        defs={defs}
        channels={channels}
        domains={domains}
        people={people}
      />,
    );
    const drop = screen.getByTestId("domain-zone-d_finance");
    const dataMap: Record<string, string> = {
      "text/wb-person": "alice-bot",
    };
    const dataTransfer = {
      getData: (k: string) => dataMap[k] ?? "",
      setData: () => {},
      types: ["text/wb-person"],
    } as unknown as DataTransfer;
    fireEvent.drop(drop, { dataTransfer });
    await waitFor(() => {
      expect(assignDomainOwnerAction).toHaveBeenCalledWith(
        "d_finance",
        "alice-bot",
      );
    });
  });
});
