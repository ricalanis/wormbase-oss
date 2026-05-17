"use client";
/**
 * PersonDetailDrawer — right-side drawer with the full Person surface.
 *
 * On open, fetches /api/people/[id], /identities, /roles, and /audit in
 * parallel. Renders four sections:
 *   - Header: name, email, position, status + tenancy role badges
 *   - Identities: list + Unlink + Add-identity form (POST/DELETE /identities)
 *   - Roles: tenancy / domain / resource via RoleGrantPanel
 *   - Audit log: last 20 ledger entries scoped to this Person
 *
 * No shared Drawer primitive existed in the repo when this landed — this
 * file embeds a self-contained fixed-position right pane with an overlay
 * scrim. Future tasks can extract it into @wormbase/design if reused.
 *
 * A5 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 */
import { useCallback, useEffect, useState } from "react";
import { Button, Input, Select } from "@wormbase/design";
import type {
  PersonIdentityDetailRow,
  PersonRoleGrant,
  PersonRow as PersonRowModel,
} from "../../lib/ledger-client.types";
import { formatChannelDisplay } from "../../lib/whatsapp-display";
import { DataProductSections } from "./DataProductSections";
import { MergeDialog } from "./MergeDialog";
import { RoleGrantPanel } from "./RoleGrantPanel";
import { SplitDialog } from "./SplitDialog";
import { chipStyle, statusTone, tenancyRoleTone } from "./_styles";

const ADMIN_ACTOR_ID = "dashboard-admin";

const PLATFORM_OPTIONS = [
  { value: "slack", label: "Slack" },
  { value: "discord", label: "Discord" },
  { value: "teams", label: "Microsoft Teams" },
  { value: "whatsapp", label: "WhatsApp" },
  { value: "signal", label: "Signal" },
  { value: "matrix", label: "Matrix" },
  { value: "irc", label: "IRC" },
  { value: "google_chat", label: "Google Chat" },
];

interface AuditEntry {
  seq: string;
  ts: string;
  kind: string;
  tool: string | null;
  hash: string;
}

export interface PersonDetailDrawerProps {
  personId: string;
  onClose: () => void;
  adminPersonId?: string;
  /**
   * Whether the current viewer is an admin / installer. When false the
   * Unlink, Add-identity, Merge, Split, and Role-grant affordances are
   * gated per CLAUDE.md §5 (identity merge / unlink are admin-only).
   * Defaults to true so legacy callers (and the existing test suite)
   * keep their original behaviour; the production /people page threads
   * the resolved role through.
   */
  isAdmin?: boolean;
}

export function PersonDetailDrawer({
  personId,
  onClose,
  adminPersonId = ADMIN_ACTOR_ID,
  isAdmin = true,
}: PersonDetailDrawerProps) {
  const [person, setPerson] = useState<PersonRowModel | null>(null);
  const [identities, setIdentities] = useState<PersonIdentityDetailRow[]>([]);
  const [roles, setRoles] = useState<PersonRoleGrant[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [mergeOpen, setMergeOpen] = useState(false);
  const [splitOpen, setSplitOpen] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [personRes, idRes, rolesRes, auditRes] = await Promise.all([
        fetch(`/api/people/${personId}`),
        fetch(`/api/people/${personId}/identities`),
        fetch(`/api/people/${personId}/roles`),
        fetch(`/api/people/${personId}/audit?limit=20`),
      ]);
      if (!personRes.ok) {
        throw new Error(`person fetch failed (${personRes.status})`);
      }
      const personJson = (await personRes.json()) as { person: PersonRowModel };
      setPerson(personJson.person);
      if (idRes.ok) {
        const j = (await idRes.json()) as {
          identities: PersonIdentityDetailRow[];
        };
        setIdentities(j.identities ?? []);
      }
      if (rolesRes.ok) {
        const j = (await rolesRes.json()) as { roles: PersonRoleGrant[] };
        setRoles(j.roles ?? []);
      }
      if (auditRes.ok) {
        const j = (await auditRes.json()) as { entries: AuditEntry[] };
        setAudit(j.entries ?? []);
      }
    } catch (err) {
      setLoadError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [personId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <div
      data-testid="person-detail-drawer"
      role="dialog"
      aria-label="Person detail"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 50,
        display: "flex",
        justifyContent: "flex-end",
      }}
    >
      <button
        data-testid="drawer-scrim"
        aria-label="Close drawer"
        onClick={onClose}
        style={{
          position: "absolute",
          inset: 0,
          background: "rgba(20, 16, 8, 0.32)",
          border: "none",
          padding: 0,
          margin: 0,
          cursor: "pointer",
        }}
      />
      <aside
        style={{
          position: "relative",
          width: "min(560px, 100vw)",
          height: "100vh",
          background: "var(--wb-color-paper)",
          borderLeft: "1px solid var(--wb-color-aged-ink)",
          padding: "20px 24px",
          overflowY: "auto",
          display: "flex",
          flexDirection: "column",
          gap: 20,
          boxShadow: "-4px 0 0 rgba(20, 16, 8, 0.04)",
        }}
      >
        <header
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            gap: 12,
          }}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span
              className="wb-mono"
              style={{
                fontSize: 10,
                letterSpacing: "0.18em",
                textTransform: "uppercase",
                color: "var(--wb-color-hash-gray)",
              }}
            >
              Person · {personId.slice(0, 8)}
            </span>
            <h2
              data-testid="drawer-name"
              style={{
                margin: 0,
                fontFamily: "var(--wb-font-serif)",
                fontSize: 26,
                fontWeight: 500,
              }}
            >
              {person?.displayName ?? "—"}
            </h2>
            <div
              className="wb-mono"
              style={{
                fontSize: 12,
                color: "var(--wb-color-hash-gray)",
              }}
            >
              {person?.email ?? "no email"}
              {person?.position ? ` · ${person.position}` : ""}
            </div>
            <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
              {person ? (
                <>
                  <span
                    className="wb-mono"
                    data-testid="drawer-status"
                    style={chipStyle(statusTone(person.status))}
                  >
                    {person.status}
                  </span>
                  <span
                    className="wb-mono"
                    data-testid="drawer-tenancy"
                    style={chipStyle(tenancyRoleTone(person.tenancyRole))}
                  >
                    {person.tenancyRole ?? "no tenancy role"}
                  </span>
                </>
              ) : null}
            </div>
          </div>
          <Button
            variant="ghost"
            size="sm"
            data-testid="drawer-close"
            onClick={onClose}
          >
            Close
          </Button>
        </header>

        {loading ? (
          <div
            data-testid="drawer-loading"
            className="wb-mono"
            style={{ fontSize: 12, color: "var(--wb-color-hash-gray)" }}
          >
            Loading…
          </div>
        ) : null}

        {loadError ? (
          <div
            data-testid="drawer-error"
            role="alert"
            className="wb-mono"
            style={{
              fontSize: 12,
              color: "var(--wb-color-sepia-warning-deep)",
              border: "1px solid var(--wb-color-sepia-warning-deep)",
              padding: "6px 10px",
            }}
          >
            {loadError}
          </div>
        ) : null}

        <IdentitiesSection
          personId={personId}
          identities={identities}
          adminPersonId={adminPersonId}
          isAdmin={isAdmin}
          onMutated={refresh}
          onMergeRequested={() => setMergeOpen(true)}
          onSplitRequested={() => setSplitOpen(true)}
        />

        <section
          data-testid="drawer-roles-section"
          style={{ display: "flex", flexDirection: "column", gap: 10 }}
        >
          <SectionHeading>Roles</SectionHeading>
          <RoleGrantPanel
            personId={personId}
            roles={roles}
            adminPersonId={adminPersonId}
            onMutated={refresh}
          />
        </section>

        <DataProductSections personId={personId} />

        <AuditSection entries={audit} />
      </aside>

      <MergeDialog
        keeperId={personId}
        keeperName={person?.displayName ?? personId}
        open={mergeOpen}
        onClose={() => setMergeOpen(false)}
        adminPersonId={adminPersonId}
        onMerged={() => {
          void refresh();
        }}
      />

      <SplitDialog
        sourcePersonId={personId}
        sourceName={person?.displayName ?? personId}
        identities={identities}
        open={splitOpen}
        onClose={() => setSplitOpen(false)}
        adminPersonId={adminPersonId}
        onSplit={() => {
          void refresh();
        }}
      />
    </div>
  );
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h3
      style={{
        margin: 0,
        fontFamily: "var(--wb-font-serif)",
        fontSize: 18,
        fontWeight: 500,
        borderBottom: "1px solid var(--wb-color-paper-edge)",
        paddingBottom: 6,
      }}
    >
      {children}
    </h3>
  );
}

function IdentitiesSection({
  personId,
  identities,
  adminPersonId,
  isAdmin,
  onMutated,
  onMergeRequested,
  onSplitRequested,
}: {
  personId: string;
  identities: PersonIdentityDetailRow[];
  adminPersonId: string;
  isAdmin: boolean;
  onMutated: () => void;
  onMergeRequested: () => void;
  onSplitRequested: () => void;
}) {
  const [platform, setPlatform] = useState(PLATFORM_OPTIONS[0].value);
  const [platformUserId, setPlatformUserId] = useState("");
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function unlink(p: PersonIdentityDetailRow) {
    const key = `${p.platform}|${p.platformUserId}`;
    setBusyKey(key);
    setError(null);
    try {
      const res = await fetch(
        `/api/people/${personId}/identities/${encodeURIComponent(p.platform)}/${encodeURIComponent(p.platformUserId)}`,
        {
          method: "DELETE",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ unlinked_by: adminPersonId }),
        },
      );
      if (!res.ok) {
        const j = (await res.json().catch(() => ({}))) as { message?: string };
        throw new Error(j.message ?? `unlink failed (${res.status})`);
      }
      onMutated();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusyKey(null);
    }
  }

  async function link(e: React.FormEvent) {
    e.preventDefault();
    if (!platformUserId.trim()) {
      setError("platform_user_id is required");
      return;
    }
    setBusyKey("__add__");
    setError(null);
    try {
      const res = await fetch(`/api/people/${personId}/identities`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          platform,
          platform_user_id: platformUserId.trim(),
          linked_by: adminPersonId,
        }),
      });
      if (!res.ok) {
        const j = (await res.json().catch(() => ({}))) as { message?: string };
        throw new Error(j.message ?? `link failed (${res.status})`);
      }
      setPlatformUserId("");
      onMutated();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusyKey(null);
    }
  }

  const splitDisabled = identities.length === 0 || !isAdmin;
  const hasWhatsApp = identities.some((i) => i.platform === "whatsapp");

  return (
    <section
      data-testid="drawer-identities-section"
      style={{ display: "flex", flexDirection: "column", gap: 10 }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
          borderBottom: "1px solid var(--wb-color-paper-edge)",
          paddingBottom: 6,
        }}
      >
        <h3
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 18,
            fontWeight: 500,
          }}
        >
          Linked identities
        </h3>
        {isAdmin ? (
          <div style={{ display: "flex", gap: 6 }}>
            <Button
              data-testid="drawer-merge-trigger"
              variant="ghost"
              size="sm"
              onClick={onMergeRequested}
            >
              Merge with another Person…
            </Button>
            <Button
              data-testid="drawer-split-trigger"
              variant="ghost"
              size="sm"
              onClick={onSplitRequested}
              disabled={splitDisabled}
            >
              Split this Person…
            </Button>
          </div>
        ) : (
          <span
            data-testid="drawer-identities-role-gated"
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            Admin only
          </span>
        )}
      </div>
      {identities.length === 0 ? (
        <span
          data-testid="identities-empty"
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
            fontSize: 13,
          }}
        >
          no identities linked yet
        </span>
      ) : (
        <ul
          data-testid="identities-list"
          style={{ listStyle: "none", padding: 0, margin: 0 }}
        >
          {identities.map((p) => {
            const key = `${p.platform}|${p.platformUserId}`;
            return (
              <IdentityRow
                key={key}
                identity={p}
                busy={busyKey === key}
                onUnlink={isAdmin ? () => unlink(p) : null}
              />
            );
          })}
        </ul>
      )}

      {/*
        D2 / CLAUDE.md §9 — when a Person has at least one identity but
        no WhatsApp identity linked, surface a quiet hint (NOT a silent
        empty panel) prompting the admin to link one. The hint
        disappears once a whatsapp PersonIdentity row is present.
      */}
      {!hasWhatsApp && identities.length > 0 ? (
        <div
          data-testid="identities-no-whatsapp"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "8px 12px",
            border: "1px dashed var(--wb-color-paper-edge)",
            background: "var(--wb-color-paper-deep)",
          }}
        >
          <PhoneIcon />
          <span
            style={{
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              fontSize: 12,
              color: "var(--wb-color-hash-gray)",
              flex: 1,
            }}
          >
            No WhatsApp identity linked.
            {isAdmin
              ? " Link this Person's WhatsApp jid below to surface their messages on the conversation lake."
              : " Ask an admin to link this Person's WhatsApp jid."}
          </span>
          {isAdmin ? (
            <Button
              data-testid="identities-link-whatsapp-cta"
              variant="ghost"
              size="sm"
              type="button"
              onClick={() => setPlatform("whatsapp")}
            >
              Link…
            </Button>
          ) : null}
        </div>
      ) : null}

      {isAdmin ? (
        <form
          data-testid="identity-link-form"
          onSubmit={link}
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 10,
            padding: 12,
            border: "1px solid var(--wb-color-paper-edge)",
            background: "var(--wb-color-paper-deep)",
          }}
        >
          <Select
            label="Platform"
            options={PLATFORM_OPTIONS}
            value={platform}
            onChange={(e) => setPlatform(e.currentTarget.value)}
            data-testid="identity-platform"
          />
          <Input
            label="Platform user id"
            placeholder={
              platform === "whatsapp"
                ? "5511999999999@s.whatsapp.net"
                : "U12345 / discord#1234 / …"
            }
            value={platformUserId}
            onChange={(e) => setPlatformUserId(e.currentTarget.value)}
            data-testid="identity-platform-user-id"
          />
          {error ? (
            <div
              data-testid="identity-error"
              role="alert"
              className="wb-mono"
              style={{
                gridColumn: "span 2",
                fontSize: 12,
                color: "var(--wb-color-sepia-warning-deep)",
              }}
            >
              {error}
            </div>
          ) : null}
          <div style={{ gridColumn: "span 2" }}>
            <Button
              type="submit"
              data-testid="identity-link-submit"
              variant="primary"
              size="sm"
              disabled={busyKey === "__add__"}
            >
              {busyKey === "__add__" ? "Linking…" : "Link identity"}
            </Button>
          </div>
        </form>
      ) : null}
    </section>
  );
}

/**
 * Discovery-source label for a PersonIdentity row.
 *
 * The substrate stores `proposed_by` as a free-form string. Three
 * categories matter at the surface:
 *
 *   - `worm:whatsapp_organic_discovery` — Path B from B2 (D2 plan §1)
 *   - `worm:slack_roster` / `worm` (legacy) — Slack roster pull
 *   - `admin_invite` / a real admin Person UUID — manual invite
 *
 * Anything that doesn't match collapses to "(unknown source)" — quiet,
 * not load-bearing in the UI but visible enough to investigate when
 * unusual proposers turn up.
 */
function describeProposedBy(proposedBy: string | null | undefined): string {
  if (!proposedBy) return "Unknown source";
  if (proposedBy === "worm:whatsapp_organic_discovery") {
    return "Worm (organic from WhatsApp)";
  }
  if (proposedBy === "worm:slack_roster" || proposedBy === "worm") {
    return "Worm (Slack roster)";
  }
  if (proposedBy === "admin_invite") return "Admin manual";
  // Real admin UUIDs and other concrete attributions surface as "Admin
  // (<short id>)" so the source is visible without disclosing the full
  // attribution string in the chip line.
  if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(proposedBy)) {
    return `Admin manual · ${proposedBy.slice(0, 8)}`;
  }
  return proposedBy;
}

/**
 * Render one PersonIdentity row. WhatsApp branches through the shared
 * `formatChannelDisplay` helper from D1 (`+<E.164>` for DM jids); group
 * jids never reach here because B2 excludes them from PersonIdentity
 * discovery (groups aren't people). Slack and other platforms render
 * the raw `platform_user_id` (byte-identical to pre-D2).
 */
function IdentityRow({
  identity,
  busy,
  onUnlink,
}: {
  identity: PersonIdentityDetailRow;
  busy: boolean;
  onUnlink: (() => void) | null;
}) {
  const { platform, platformUserId, displayName, proposedBy } = identity;
  const isWhatsApp = platform === "whatsapp";
  const display = isWhatsApp
    ? formatChannelDisplay(platformUserId, "whatsapp", null)
    : null;
  const friendlyId = display?.label ?? platformUserId;

  return (
    <li
      data-testid={`identity-row-${platform}-${platformUserId}`}
      data-platform={platform}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "6px 0",
        borderBottom: "1px dashed var(--wb-color-paper-edge)",
        flexWrap: "wrap",
      }}
    >
      {isWhatsApp ? <PhoneIcon /> : null}
      <span className="wb-mono" style={chipStyle("ink")}>
        {platform}
      </span>
      <span
        className="wb-mono"
        data-testid={`identity-display-${platform}-${platformUserId}`}
        style={{
          fontSize: 12,
          color: "var(--wb-color-aged-ink)",
        }}
      >
        {friendlyId}
      </span>
      {displayName ? (
        <span
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            fontSize: 12,
            color: "var(--wb-color-hash-gray)",
          }}
        >
          {displayName}
        </span>
      ) : null}
      <span
        data-testid={`identity-source-${platform}-${platformUserId}`}
        className="wb-mono"
        style={{
          fontSize: 10,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        {describeProposedBy(proposedBy)}
      </span>
      {onUnlink ? (
        <Button
          data-testid={`identity-unlink-${platform}-${platformUserId}`}
          variant="ghost"
          size="sm"
          style={{ marginLeft: "auto" }}
          onClick={onUnlink}
          disabled={busy}
        >
          {busy ? "Unlinking…" : "Unlink"}
        </Button>
      ) : null}
    </li>
  );
}

/**
 * Inline phone-receiver glyph. Used to visually distinguish a WhatsApp
 * PersonIdentity row from a Slack U-id row (and the empty-state
 * affordance) per the D2 plan. SVG inline so no asset pipeline is
 * required and `currentColor` lets it pick up surrounding text styles.
 */
function PhoneIcon() {
  return (
    <svg
      data-testid="identity-phone-icon"
      aria-hidden="true"
      width={14}
      height={14}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ color: "var(--wb-color-botanical-green-deep)" }}
    >
      <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z" />
    </svg>
  );
}

function AuditSection({ entries }: { entries: AuditEntry[] }) {
  return (
    <section
      data-testid="drawer-audit-section"
      style={{ display: "flex", flexDirection: "column", gap: 6 }}
    >
      <SectionHeading>Audit log</SectionHeading>
      {entries.length === 0 ? (
        <span
          data-testid="audit-empty"
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
            fontSize: 13,
          }}
        >
          no audit entries
        </span>
      ) : (
        <ol
          data-testid="audit-list"
          style={{ listStyle: "none", padding: 0, margin: 0 }}
        >
          {entries.map((e) => (
            <li
              key={e.seq}
              data-testid={`audit-row-${e.seq}`}
              className="wb-mono"
              style={{
                display: "grid",
                gridTemplateColumns: "60px 1fr auto",
                gap: 10,
                fontSize: 11,
                color: "var(--wb-color-aged-ink)",
                padding: "4px 0",
                borderBottom: "1px dashed var(--wb-color-paper-edge)",
              }}
            >
              <span style={{ color: "var(--wb-color-hash-gray)" }}>
                #{e.seq}
              </span>
              <span>{e.tool ?? e.kind}</span>
              <span style={{ color: "var(--wb-color-hash-gray)" }}>
                {new Date(e.ts).toISOString().slice(0, 19).replace("T", " ")}
              </span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
