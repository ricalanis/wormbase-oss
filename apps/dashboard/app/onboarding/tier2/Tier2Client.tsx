"use client";

import Link from "next/link";
import { Button } from "@wormbase/design";
import { WizardProgress } from "../../../components/onboarding/WizardProgress";
import { BusinessDefsPanel } from "../../../components/onboarding/BusinessDefsPanel";
import { TalkativenessPanel } from "../../../components/onboarding/TalkativenessPanel";
import { GovernancePanel } from "../../../components/onboarding/GovernancePanel";
import type {
  BusinessDefProposal,
  ChannelRow,
  DomainRow,
  PersonRow,
} from "../../../lib/ledger-client.types";
import {
  assignDomainOwnerAction,
  confirmBusinessDefAction,
  rejectBusinessDefAction,
} from "./actions";

export function Tier2Client({
  defs,
  channels,
  domains,
  people,
}: {
  defs: BusinessDefProposal[];
  channels: ChannelRow[];
  domains: DomainRow[];
  people: PersonRow[];
}) {
  return (
    <div
      style={{
        maxWidth: 980,
        margin: "0 auto",
        padding: "32px 24px",
        display: "flex",
        flexDirection: "column",
        gap: 28,
      }}
    >
      <header style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 11,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Onboarding · Tier 2 · Context
        </span>
        <h1
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 30,
            fontWeight: 600,
            letterSpacing: "-0.01em",
          }}
        >
          The worm proposes; you confirm
        </h1>
      </header>

      <WizardProgress currentTier={2} completed={[1]} />

      <section
        data-testid="defs-section"
        style={{ display: "flex", flexDirection: "column", gap: 12 }}
      >
        <h2
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontSize: 20,
            fontWeight: 600,
            margin: 0,
            borderBottom: "3px double var(--wb-color-aged-ink)",
            paddingBottom: 6,
          }}
        >
          Business definitions
        </h2>
        {/*
          F2 wire (Sub-wave A, 2026-05-30):
          confirm + reject now flow through `tier2/actions.ts` server
          actions, which forward to the existing `confirmBusinessDef` /
          `rejectBusinessDef` writers in `lib/ledger-client.ts`. The
          writers emit synthetic receipts today (no new worm-core
          endpoint); Sub-wave C may promote them to a real
          `emit_concept_confirmed` PEVR cycle once the
          `concept_confirmed` write_actions endpoint lands. Until then
          the user-visible behaviour (an accept that returns a receipt
          + flips the row to data-status=accepted) is honest.
        */}
        <BusinessDefsPanel
          proposals={defs}
          onConfirm={async (term) => {
            await confirmBusinessDefAction(term);
          }}
          onReject={async (term) => {
            await rejectBusinessDefAction(term);
          }}
        />
      </section>

      <section
        data-testid="talkativeness-section"
        style={{ display: "flex", flexDirection: "column", gap: 12 }}
      >
        <h2
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontSize: 20,
            fontWeight: 600,
            margin: 0,
            borderBottom: "3px double var(--wb-color-aged-ink)",
            paddingBottom: 6,
          }}
        >
          Channel talkativeness
        </h2>
        {/*
          Intentionally NOT wired in this Sub-wave (F2 scope cut).
          Channel talkativeness edits flow through `/settings/channels`,
          which already POSTs to `/api/governance/channel` and writes
          the canonical ledger entry. Re-wiring the Tier 2 affordance
          to a Tier-2-scoped action would require a duplicate endpoint
          or a contextual write — neither is in this sub-wave's scope.
          Sub-wave C (or B, depending on the `/onboard/chat` design) is
          the right place to revisit if/when Tier 2 needs an in-wizard
          dial.
        */}
        <TalkativenessPanel channels={channels} />
      </section>

      <section
        data-testid="governance-section"
        style={{ display: "flex", flexDirection: "column", gap: 12 }}
      >
        <h2
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontSize: 20,
            fontWeight: 600,
            margin: 0,
            borderBottom: "3px double var(--wb-color-aged-ink)",
            paddingBottom: 6,
          }}
        >
          Governance · domains & owners
        </h2>
        {/*
          F2 wire (Sub-wave A, 2026-05-30):
          domain owner assignment forwards to `assignDomainOwnerAction`,
          which calls the existing `assignDomainOwner` writer in
          `lib/ledger-client.ts`. That writer emits a real
          `emit_domain_owner_assigned` PEVR cycle when Postgres is
          reachable, and falls back to a synthetic receipt otherwise.
          The `/domains` read projection picks up the new owner on its
          next 10s poll.
        */}
        <GovernancePanel
          domains={domains}
          people={people}
          onAssignOwner={async (domainId, personId) => {
            await assignDomainOwnerAction(domainId, personId);
          }}
        />
      </section>

      <footer
        style={{
          display: "flex",
          justifyContent: "space-between",
          borderTop: "1px solid var(--wb-color-aged-ink)",
          paddingTop: 16,
        }}
      >
        <Link href="/onboarding" style={{ textDecoration: "none" }}>
          <Button variant="ghost">Back</Button>
        </Link>
        <Link href="/onboarding/tier3" style={{ textDecoration: "none" }}>
          <Button data-testid="next">Next</Button>
        </Link>
      </footer>
    </div>
  );
}
