"use client";

/**
 * ArchitectureDiagram — the post-portfolio worm decomposition (CLAUDE.md §1.5)
 * rendered as a clickable 6-agent pitch surface.
 *
 * Six named-actor worms ship as their own packages and compose under
 * `apps/worm-core` (the runtime hub). Each agent's modal lists what it does
 * and which Reactivities it ships, so visitors see the institutional-AI
 * architecture as concrete code, not slideware.
 *
 * Wave H · Phase 4A — visual treatment is Field Notebook (warm paper, rule
 * lines, serif headlines, monospace metadata). Each agent node is a button
 * so keyboard users can open the modal via Enter/Space.
 *
 * Reactivity surface for each agent comes from the post-portfolio waves
 * (A=Identity, B=Chat, C₁=Research, C₂=Process, D=Governance, P1=Lake).
 */
import { useId, useState, type CSSProperties, type ReactNode } from "react";

export type AgentId =
  | "lake"
  | "identity"
  | "chat"
  | "process"
  | "research"
  | "governance";

export interface AgentSpec {
  id: AgentId;
  /** Display name (serif headline). */
  title: string;
  /** Package name from CLAUDE.md §1.5. */
  pkg: string;
  /** Wave letter (Phase 1 / A / B / C₁ / C₂ / D). */
  wave: string;
  /** One-sentence pitch (under the node). */
  blurb: string;
  /** Modal body — what the agent does. */
  body: string;
  /** Reactivities the agent ships, named per CLAUDE.md doctrine. */
  reactivities: string[];
}

export const AGENTS: AgentSpec[] = [
  {
    id: "lake",
    title: "Lake Maintainer",
    pkg: "packages/lake-maintainer",
    wave: "Phase 1",
    blurb:
      "Grows the medallion lake — bronze, silver, gold — across all six source-building flows.",
    body:
      "Owns the medallion cascade. Profiles dropped files, walks discovered catalogs, and watches connected sources. Every layer writes a hash-stable ledger receipt; replay the ledger to timestamp T to land on the same bytes.",
    reactivities: [
      "source.proposed → profile + classify",
      "source.connected → bronze cascade",
      "bronze.landed → silver typing + governance hints",
      "silver.landed → gold aggregates + KPI proposals",
    ],
  },
  {
    id: "identity",
    title: "Identity Tracker",
    pkg: "packages/wormbase-identity-tracker",
    wave: "Wave A",
    blurb:
      "Discovers your team from chatter — one Person, many platform identities, role-graded.",
    body:
      "Watches every wire event and proposes Persons + identity links + role grants. Three role facets compose: tenancy, domain, resource. Every grant is a ledger entry with audit trail.",
    reactivities: [
      "wire.unknown_user → emit_person_proposed",
      "wire.platform_member_listed → emit_identity_link_proposed",
      "chatter.signal → emit_resource_role_proposed",
      "admin.confirms → emit_identity_linked / emit_role_assigned",
    ],
  },
  {
    id: "chat",
    title: "Chat Presence",
    pkg: "packages/wormbase-chat-presence",
    wave: "Wave B",
    blurb:
      "Listens, gates, and speaks across every channel — Slack, Discord, Teams, anywhere OpenClaw reaches.",
    body:
      "Bridges OpenClaw wire events to ledger entries. Listen-for-ingest is always on; speak is always gated. The relevance gate is constructor-injected from governance so every interjection is auditable.",
    reactivities: [
      "wire.message → emit_chat_received",
      "wire.mention → relevance_gate → emit_chat_response_proposed",
      "wire.thread.recurs → emit_recurring_question",
      "scheduled.digest → emit_digest_published",
    ],
  },
  {
    id: "process",
    title: "Process Extractor",
    pkg: "packages/wormbase-process-extractor",
    wave: "Wave C₂",
    blurb:
      "Mines decisions, process maps, and system maps from the conversation lake.",
    body:
      "Reads silver-conversation rows and lifts them into gold-conversation artifacts: decision logs, process diagrams, system maps. The org's tacit knowledge becomes a queryable substrate.",
    reactivities: [
      "silver.thread.closed → emit_decision_recorded",
      "silver.thread.workflow → emit_process_map_proposed",
      "silver.handoff → emit_system_map_node",
      "decision.contradicts_prior → emit_decision_revised",
    ],
  },
  {
    id: "research",
    title: "Research Loop",
    pkg: "packages/wormbase-research-loop",
    wave: "Wave C₁",
    blurb:
      "Karpathy-style autoresearch, parameterized per Person × position. One analyst seat, sharper every night.",
    body:
      "Per-person autoresearch loop. Reads recent activity, tracks headline metrics defined by the user's position, proposes experiments, runs them, and keeps wins. PEVR primitive: propose → execute → verify → resolve.",
    reactivities: [
      "headline_metric.observed → emit_experiment_proposed",
      "experiment.proposed → emit_experiment_run",
      "experiment.run → emit_experiment_resolved (keep / discard)",
      "weekly.cadence → emit_research_digest",
    ],
  },
  {
    id: "governance",
    title: "Governance",
    pkg: "packages/governance",
    wave: "Wave D",
    blurb:
      "Composes gates at every write site — relevance, PII, classification, policy.",
    body:
      "Gates are not Reactivities — they compose into other worms at construction time. Relevance gate flows into chat presence; PII + warmup gates attach at write_actions sites. Every fire is a ledger receipt.",
    reactivities: [
      "any.write → relevance_gate (chat)",
      "any.write → pii_gate (write_actions)",
      "any.write → warmup_gate (write_actions)",
      "policy.violation → emit_gate_fired",
    ],
  },
];

export function ArchitectureDiagram() {
  const [activeId, setActiveId] = useState<AgentId | null>(null);
  const titleId = useId();
  const active = activeId ? AGENTS.find((a) => a.id === activeId) ?? null : null;

  return (
    <section
      data-testid="architecture-section"
      aria-labelledby={titleId}
      style={sectionStyle}
    >
      <div style={sectionInnerStyle}>
        <p className="wb-mono" style={eyebrowStyle}>
          plate iii · the architecture
        </p>
        <h2
          id={titleId}
          data-testid="architecture-headline"
          style={headlineStyle}
        >
          Six worms, one ledger.
          <span style={headlineDashStyle}> — </span>
          <span style={headlineSubStyle}>
            Click any agent to read its responsibilities.
          </span>
        </h2>
        <p style={subheadStyle}>
          WormBase decomposes the data-function into six named agents that
          compose under one runtime hub. Every action — every classification,
          every experiment, every spoken reply — passes through the gate and
          lands on the ledger. The diagram is the codebase.
        </p>

        <div style={diagramStyle}>
          <Hub />
          <ul style={ringStyle} role="list">
            {AGENTS.map((agent) => (
              <li key={agent.id} style={ringItemStyle}>
                <AgentNode
                  agent={agent}
                  onActivate={() => setActiveId(agent.id)}
                  isActive={active?.id === agent.id}
                />
              </li>
            ))}
          </ul>
        </div>
      </div>

      {active ? (
        <AgentModal agent={active} onClose={() => setActiveId(null)} />
      ) : null}
    </section>
  );
}

function Hub() {
  return (
    <div data-testid="architecture-hub" style={hubStyle}>
      <span className="wb-mono" style={hubKickerStyle}>
        runtime hub
      </span>
      <span style={hubTitleStyle}>apps/worm-core</span>
      <span className="wb-mono" style={hubMetaStyle}>
        cli · http · mcp · ledger · projections
      </span>
    </div>
  );
}

interface AgentNodeProps {
  agent: AgentSpec;
  isActive: boolean;
  onActivate: () => void;
}

function AgentNode({ agent, isActive, onActivate }: AgentNodeProps) {
  return (
    <button
      data-testid={`agent-node-${agent.id}`}
      data-active={isActive ? "true" : "false"}
      type="button"
      onClick={onActivate}
      style={{
        ...nodeStyle,
        borderColor: isActive
          ? "var(--wb-color-botanical-green)"
          : "var(--wb-color-rule-line)",
        boxShadow: isActive
          ? "inset 0 0 0 1px var(--wb-color-botanical-green)"
          : "none",
      }}
    >
      <span className="wb-mono" style={nodeWaveStyle}>
        {agent.wave}
      </span>
      <span style={nodeTitleStyle}>{agent.title}</span>
      <span className="wb-mono" style={nodePkgStyle}>
        {agent.pkg.replace(/^packages\//, "")}
      </span>
      <span style={nodeBlurbStyle}>{agent.blurb}</span>
    </button>
  );
}

interface AgentModalProps {
  agent: AgentSpec;
  onClose: () => void;
}

function AgentModal({ agent, onClose }: AgentModalProps) {
  return (
    <div
      data-testid="agent-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby={`agent-modal-title-${agent.id}`}
      style={modalScrimStyle}
      onClick={onClose}
    >
      <div
        style={modalCardStyle}
        onClick={(e) => e.stopPropagation()}
      >
        <header style={modalHeaderStyle}>
          <div style={modalHeadlineStyle}>
            <span className="wb-mono" style={modalKickerStyle}>
              {agent.wave} · {agent.pkg}
            </span>
            <h3
              id={`agent-modal-title-${agent.id}`}
              style={modalTitleStyle}
            >
              {agent.title}
            </h3>
          </div>
          <button
            data-testid="agent-modal-close"
            type="button"
            onClick={onClose}
            aria-label="Close agent details"
            style={modalCloseStyle}
          >
            ×
          </button>
        </header>

        <p style={modalBodyStyle}>{agent.body}</p>

        <ModalSection title="Reactivities shipped">
          <ul
            data-testid="agent-modal-reactivities"
            style={reactivityListStyle}
          >
            {agent.reactivities.map((r) => (
              <li key={r} className="wb-mono" style={reactivityItemStyle}>
                {r}
              </li>
            ))}
          </ul>
        </ModalSection>

        <footer style={modalFooterStyle} className="wb-mono">
          every fire is a ledger receipt · replay this agent to land on the
          same hash
        </footer>
      </div>
    </div>
  );
}

function ModalSection({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section style={modalSectionStyle}>
      <h4 className="wb-mono" style={modalSectionTitleStyle}>
        {title}
      </h4>
      {children}
    </section>
  );
}

const sectionStyle: CSSProperties = {
  width: "100%",
  borderTop: "1px solid var(--wb-color-rule-line)",
  borderBottom: "1px solid var(--wb-color-rule-line)",
  background: "var(--wb-color-paper-deep)",
  padding: "72px 24px",
};

const sectionInnerStyle: CSSProperties = {
  maxWidth: 1080,
  margin: "0 auto",
  display: "flex",
  flexDirection: "column",
  gap: 24,
};

const eyebrowStyle: CSSProperties = {
  fontSize: 11,
  letterSpacing: "0.24em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
  margin: 0,
};

const headlineStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: "clamp(28px, 3.4vw, 40px)",
  fontWeight: 600,
  color: "var(--wb-color-aged-ink)",
  letterSpacing: "-0.012em",
  lineHeight: 1.15,
  maxWidth: 820,
};

const headlineDashStyle: CSSProperties = {
  color: "var(--wb-color-hash-gray)",
  fontWeight: 400,
};

const headlineSubStyle: CSSProperties = {
  fontStyle: "italic",
  color: "var(--wb-color-aged-ink-soft)",
};

const subheadStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: "var(--wb-text-md)",
  color: "var(--wb-color-aged-ink-soft)",
  lineHeight: 1.55,
  maxWidth: 720,
};

const diagramStyle: CSSProperties = {
  marginTop: 32,
  position: "relative",
  display: "grid",
  gridTemplateColumns: "minmax(240px, 280px) 1fr",
  alignItems: "center",
  gap: 32,
};

const hubStyle: CSSProperties = {
  border: "1.5px solid var(--wb-color-aged-ink)",
  background: "var(--wb-color-paper)",
  padding: "20px 22px",
  borderRadius: 2,
  display: "flex",
  flexDirection: "column",
  gap: 6,
  alignItems: "flex-start",
  textAlign: "left",
};

const hubKickerStyle: CSSProperties = {
  fontSize: 10,
  letterSpacing: "0.16em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
};

const hubTitleStyle: CSSProperties = {
  fontFamily: "var(--wb-font-serif)",
  fontSize: "var(--wb-text-lg)",
  fontWeight: 600,
  color: "var(--wb-color-aged-ink)",
};

const hubMetaStyle: CSSProperties = {
  fontSize: 11,
  color: "var(--wb-color-hash-gray)",
};

const ringStyle: CSSProperties = {
  listStyle: "none",
  margin: 0,
  padding: 0,
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
  gap: 16,
};

const ringItemStyle: CSSProperties = {
  display: "flex",
};

const nodeStyle: CSSProperties = {
  flex: 1,
  textAlign: "left",
  background: "var(--wb-color-paper)",
  border: "1px solid var(--wb-color-rule-line)",
  borderRadius: 2,
  padding: "16px 18px",
  display: "flex",
  flexDirection: "column",
  gap: 6,
  cursor: "pointer",
  fontFamily: "inherit",
  color: "inherit",
  transition:
    "border-color var(--wb-duration-standard) var(--wb-ease-standard), box-shadow var(--wb-duration-standard) var(--wb-ease-standard)",
};

const nodeWaveStyle: CSSProperties = {
  fontSize: 10,
  letterSpacing: "0.18em",
  textTransform: "uppercase",
  color: "var(--wb-color-botanical-green-deep)",
};

const nodeTitleStyle: CSSProperties = {
  fontFamily: "var(--wb-font-serif)",
  fontSize: "var(--wb-text-md)",
  fontWeight: 600,
  color: "var(--wb-color-aged-ink)",
};

const nodePkgStyle: CSSProperties = {
  fontSize: 10,
  color: "var(--wb-color-hash-gray)",
};

const nodeBlurbStyle: CSSProperties = {
  fontFamily: "var(--wb-font-serif)",
  fontSize: "var(--wb-text-sm)",
  color: "var(--wb-color-aged-ink-soft)",
  lineHeight: 1.45,
};

const modalScrimStyle: CSSProperties = {
  position: "fixed",
  inset: 0,
  background: "rgba(42, 42, 42, 0.45)",
  zIndex: 1000,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  padding: "32px 16px",
};

const modalCardStyle: CSSProperties = {
  width: "min(640px, 100%)",
  maxHeight: "min(82vh, 720px)",
  overflowY: "auto",
  background: "var(--wb-color-paper)",
  border: "1px solid var(--wb-color-aged-ink)",
  borderRadius: 2,
  padding: "24px 28px",
  display: "flex",
  flexDirection: "column",
  gap: 16,
};

const modalHeaderStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "flex-start",
  gap: 16,
};

const modalHeadlineStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 4,
};

const modalKickerStyle: CSSProperties = {
  fontSize: 10,
  letterSpacing: "0.18em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
};

const modalTitleStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: "clamp(22px, 2.4vw, 28px)",
  fontWeight: 600,
  color: "var(--wb-color-aged-ink)",
  letterSpacing: "-0.01em",
};

const modalCloseStyle: CSSProperties = {
  background: "transparent",
  border: "1px solid var(--wb-color-rule-line)",
  fontSize: 18,
  width: 32,
  height: 32,
  borderRadius: 2,
  cursor: "pointer",
  color: "var(--wb-color-aged-ink)",
};

const modalBodyStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: "var(--wb-text-base)",
  color: "var(--wb-color-aged-ink)",
  lineHeight: 1.6,
};

const modalSectionStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 8,
  borderTop: "1px solid var(--wb-color-rule-line)",
  paddingTop: 14,
};

const modalSectionTitleStyle: CSSProperties = {
  margin: 0,
  fontSize: 11,
  letterSpacing: "0.18em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
};

const reactivityListStyle: CSSProperties = {
  listStyle: "none",
  margin: 0,
  padding: 0,
  display: "flex",
  flexDirection: "column",
  gap: 6,
};

const reactivityItemStyle: CSSProperties = {
  fontSize: 12,
  color: "var(--wb-color-aged-ink-soft)",
  background: "var(--wb-color-paper-deep)",
  borderLeft: "2px solid var(--wb-color-botanical-green)",
  padding: "8px 10px",
};

const modalFooterStyle: CSSProperties = {
  fontSize: 10,
  letterSpacing: "0.16em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
  borderTop: "1px solid var(--wb-color-rule-line)",
  paddingTop: 12,
};
