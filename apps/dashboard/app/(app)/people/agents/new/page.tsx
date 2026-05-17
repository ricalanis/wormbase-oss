import Link from "next/link";

import { AgentRegistrationForm } from "../../../../../components/agents/AgentRegistrationForm";
import { EmptyState } from "../../../../../components/chrome/EmptyState";
import { PageBoundary } from "../../../../../components/chrome/PageBoundary";
import { getCurrentCompanyId } from "../../../../../lib/tenant-cookies";
import { getCurrentPerson } from "../../../../../lib/server/identity";
import { getDomains, getRolesForPerson } from "../../../../../lib/ledger-client";
import { registerAgent } from "./actions";

export const metadata = { title: "WormBase · People · Register agent" };

export const dynamic = "force-dynamic";

/**
 * /people/agents/new — Semantic Layer Wave 3.2 Hole #1.
 *
 * Admin-only form for registering a new external Agent (Claude / OpenAI /
 * Kimi / internal_worm / other) plus an initial set of grants. Submission
 * routes through the `registerAgent` server action, which forwards to
 * worm-core's HTTP write API. The dashboard NEVER direct-writes the
 * ledger — every registration lands as an `agent_registered` PEVR cycle
 * (plus companion `agent_grant` entries for each requested grant).
 *
 * Defense in depth: the page short-circuits to a "admin required" panel
 * for non-admins; the server action re-checks the role before forwarding
 * to worm-core. A non-admin can neither see the form nor bypass the page
 * by posting directly to the action.
 */
export default async function NewAgentPage(): Promise<JSX.Element> {
  const companyId = await getCurrentCompanyId();
  const person = await getCurrentPerson(companyId);

  // Resolve effective tenancy role (admin / installer; fall back to a
  // grants probe in case the roster projection lags). Mirrors the
  // pattern used by `promoteSemanticGap`.
  const isAdmin = await resolveIsAdmin(companyId, person);

  return (
    <PageBoundary
      surface="people agents register"
      traceQuery="?surface=people.agents.new"
    >
      <header style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Pl. IV · Governance lens · register agent
        </span>
        <h1
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 34,
            fontWeight: 500,
            letterSpacing: "-0.01em",
          }}
        >
          Register a new agent
        </h1>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
            maxWidth: 720,
          }}
        >
          Issues an external Agent (Claude, OpenAI, Kimi, …) or an internal
          worm-issued Agent with an initial set of grants. The registration
          lands as an `agent_registered` PEVR cycle through worm-core;
          revocation is one ledger write, not a side-channel.
        </p>
      </header>

      {!isAdmin ? (
        <EmptyState
          testId="people-agents-new-not-admin"
          eyebrow="admin required"
          title="Admin role required to register agents."
          description={
            "Only Persons with an unrevoked tenancy.admin (or " +
            "tenancy.installer) grant can register agents. Ask an existing " +
            "admin to add you, or proceed via the admin CLI."
          }
          cta={{ label: "Back to agents", href: "/people/agents" }}
          secondaryCta={{ label: "See activity", href: "/activity" }}
        />
      ) : (
        <NewAgentFormContainer companyId={companyId} />
      )}
    </PageBoundary>
  );
}

async function NewAgentFormContainer({
  companyId,
}: {
  companyId: string;
}): Promise<JSX.Element> {
  const domains = await getDomains(companyId);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <AgentRegistrationForm
        domains={domains}
        registerAction={registerAgent}
      />
      <p
        style={{
          margin: 0,
          fontFamily: "var(--wb-font-serif)",
          fontSize: 12,
          fontStyle: "italic",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        Need to revoke an existing agent? See the per-agent detail at{" "}
        <Link href="/people/agents" style={{ color: "inherit" }}>
          /people/agents
        </Link>
        .
      </p>
    </div>
  );
}

async function resolveIsAdmin(
  companyId: string,
  person: Awaited<ReturnType<typeof getCurrentPerson>>,
): Promise<boolean> {
  if (!person) return false;
  if (person.tenancyRole === "admin" || person.tenancyRole === "installer") {
    return true;
  }
  // Roster projection may lag; probe the grants table directly.
  let grants: Awaited<ReturnType<typeof getRolesForPerson>> = [];
  try {
    grants = await getRolesForPerson(companyId, person.personId);
  } catch {
    grants = [];
  }
  const live = grants
    .filter((g) => g.facet === "tenancy" && g.revokedAt === null)
    .map((g) => g.role);
  return live.includes("admin") || live.includes("installer");
}
