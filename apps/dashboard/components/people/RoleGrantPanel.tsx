"use client";
/**
 * RoleGrantPanel — render + grant + revoke a Person's role surface.
 *
 * Three sub-lists (tenancy / domain / resource) + a "Grant role" form
 * below. The form's role options change per facet:
 *   - tenancy:  installer | admin | member | observer
 *   - domain:   owner | contributor    (requires scope_id = domain_id)
 *   - resource: maintainer | contributor (requires scope_id + scope_type)
 *
 * Submission POSTs to /api/people/[id]/roles. Tenancy revoke calls
 * /api/people/[id]/roles/[grant_id]/revoke. Both write hash-chained PEVR
 * cycles via worm-core.
 *
 * Extracted so the future MergeDialog / SplitDialog (A6) can re-use it.
 *
 * A5 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 */
import { useMemo, useState } from "react";
import { Button, Input, Select } from "@wormbase/design";
import type {
  PersonRoleGrant,
  RoleFacet,
} from "../../lib/ledger-client.types";
import { chipStyle } from "./_styles";

const TENANCY_ROLES = ["installer", "admin", "member", "observer"];
const DOMAIN_ROLES = ["owner", "contributor"];
const RESOURCE_ROLES = ["maintainer", "contributor"];

const ADMIN_ACTOR_ID = "dashboard-admin";

export interface RoleGrantPanelProps {
  personId: string;
  roles: PersonRoleGrant[];
  /** Called after a grant or revoke succeeds — typically refetches the list. */
  onMutated?: () => void;
  /** Optional admin Person id (UUID); recorded in granted_by / revoked_by. */
  adminPersonId?: string;
}

export function RoleGrantPanel({
  personId,
  roles,
  onMutated,
  adminPersonId = ADMIN_ACTOR_ID,
}: RoleGrantPanelProps) {
  const [facet, setFacet] = useState<RoleFacet>("tenancy");
  const [role, setRole] = useState<string>(TENANCY_ROLES[0]);
  const [scopeId, setScopeId] = useState("");
  const [scopeType, setScopeType] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revokingKey, setRevokingKey] = useState<string | null>(null);

  const tenancy = useMemo(
    () => roles.filter((r) => r.facet === "tenancy"),
    [roles],
  );
  const domain = useMemo(
    () => roles.filter((r) => r.facet === "domain"),
    [roles],
  );
  const resource = useMemo(
    () => roles.filter((r) => r.facet === "resource"),
    [roles],
  );

  function roleOptions() {
    const list =
      facet === "tenancy"
        ? TENANCY_ROLES
        : facet === "domain"
          ? DOMAIN_ROLES
          : RESOURCE_ROLES;
    return list.map((r) => ({ value: r, label: r }));
  }

  function onFacetChange(next: RoleFacet) {
    setFacet(next);
    const list =
      next === "tenancy"
        ? TENANCY_ROLES
        : next === "domain"
          ? DOMAIN_ROLES
          : RESOURCE_ROLES;
    setRole(list[0]);
  }

  async function submitGrant(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if ((facet === "domain" || facet === "resource") && !scopeId.trim()) {
      setError(`${facet} grants require a scope_id`);
      return;
    }
    if (facet === "resource" && !scopeType.trim()) {
      setError("resource grants require a scope_type");
      return;
    }
    setBusy(true);
    try {
      const body: Record<string, unknown> = {
        facet,
        role,
        granted_by: adminPersonId,
      };
      if (facet === "domain" || facet === "resource") {
        body.scope_id = scopeId.trim();
      }
      if (facet === "resource") {
        body.scope_type = scopeType.trim();
      }
      const res = await fetch(`/api/people/${personId}/roles`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const j = (await res.json().catch(() => ({}))) as { message?: string };
        throw new Error(j.message ?? `grant failed (${res.status})`);
      }
      // Reset scope-only inputs; keep facet/role for repeated grants.
      setScopeId("");
      setScopeType("");
      onMutated?.();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function revokeTenancy(roleName: string) {
    const key = `tenancy:${roleName}`;
    setRevokingKey(key);
    setError(null);
    try {
      // The grant_id is opaque on the read side (only tenancy revoke is
      // wired); worm-core uses (person_id, role) as the addressing key, so
      // we forward the role name as the path segment.
      const grantId = encodeURIComponent(roleName);
      const res = await fetch(
        `/api/people/${personId}/roles/${grantId}/revoke`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            revoked_by: adminPersonId,
            role: roleName,
          }),
        },
      );
      if (!res.ok) {
        const j = (await res.json().catch(() => ({}))) as { message?: string };
        throw new Error(j.message ?? `revoke failed (${res.status})`);
      }
      onMutated?.();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setRevokingKey(null);
    }
  }

  return (
    <section
      data-testid="role-grant-panel"
      style={{ display: "flex", flexDirection: "column", gap: 16 }}
    >
      <RoleSubList
        title="Tenancy"
        rows={tenancy}
        onRevoke={revokeTenancy}
        revokingKey={revokingKey}
        revokable
      />
      <RoleSubList title="Domain" rows={domain} />
      <RoleSubList title="Resource" rows={resource} />

      <form
        data-testid="role-grant-form"
        onSubmit={submitGrant}
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 10,
          padding: 12,
          border: "1px solid var(--wb-color-paper-edge)",
          background: "var(--wb-color-paper-deep)",
        }}
      >
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.16em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Grant role
        </span>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 10,
          }}
        >
          <Select
            label="Facet"
            data-testid="grant-facet"
            options={[
              { value: "tenancy", label: "Tenancy" },
              { value: "domain", label: "Domain" },
              { value: "resource", label: "Resource" },
            ]}
            value={facet}
            onChange={(e) => onFacetChange(e.currentTarget.value as RoleFacet)}
          />
          <Select
            label="Role"
            data-testid="grant-role"
            options={roleOptions()}
            value={role}
            onChange={(e) => setRole(e.currentTarget.value)}
          />
        </div>
        {facet === "domain" || facet === "resource" ? (
          <Input
            label="Scope id"
            data-testid="grant-scope-id"
            placeholder={
              facet === "domain" ? "domain_id" : "resource_id (UUID)"
            }
            value={scopeId}
            onChange={(e) => setScopeId(e.currentTarget.value)}
          />
        ) : null}
        {facet === "resource" ? (
          <Input
            label="Scope type"
            data-testid="grant-scope-type"
            placeholder="kpi | source | mart | …"
            value={scopeType}
            onChange={(e) => setScopeType(e.currentTarget.value)}
          />
        ) : null}
        {error ? (
          <div
            data-testid="grant-error"
            role="alert"
            className="wb-mono"
            style={{
              fontSize: 12,
              color: "var(--wb-color-sepia-warning-deep)",
            }}
          >
            {error}
          </div>
        ) : null}
        <Button
          type="submit"
          data-testid="grant-submit"
          variant="primary"
          size="sm"
          disabled={busy}
        >
          {busy ? "Granting…" : "Grant"}
        </Button>
      </form>
    </section>
  );
}

function RoleSubList({
  title,
  rows,
  onRevoke,
  revokingKey,
  revokable,
}: {
  title: string;
  rows: PersonRoleGrant[];
  onRevoke?: (role: string) => void;
  revokingKey?: string | null;
  revokable?: boolean;
}) {
  return (
    <div
      data-testid={`role-sublist-${title.toLowerCase()}`}
      style={{ display: "flex", flexDirection: "column", gap: 6 }}
    >
      <span
        className="wb-mono"
        style={{
          fontSize: 10,
          letterSpacing: "0.16em",
          textTransform: "uppercase",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        {title} ({rows.length})
      </span>
      {rows.length === 0 ? (
        <span
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
            fontSize: 13,
          }}
        >
          no {title.toLowerCase()} grants
        </span>
      ) : (
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {rows.map((r) => {
            const key = `${r.facet}:${r.role}:${r.scopeId ?? ""}`;
            return (
              <li
                key={key}
                data-testid={`role-row-${title.toLowerCase()}-${r.role}-${r.scopeId ?? ""}`}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "6px 0",
                  borderBottom: "1px dashed var(--wb-color-paper-edge)",
                }}
              >
                <span className="wb-mono" style={chipStyle("ink")}>
                  {r.role}
                </span>
                {r.scopeId ? (
                  <span
                    className="wb-mono"
                    style={{
                      fontSize: 11,
                      color: "var(--wb-color-aged-ink-soft)",
                    }}
                  >
                    {r.scopeType ? `${r.scopeType}:` : ""}
                    {r.scopeId}
                  </span>
                ) : null}
                <span
                  className="wb-mono"
                  style={{
                    marginLeft: "auto",
                    fontSize: 10,
                    color: "var(--wb-color-hash-gray)",
                  }}
                >
                  by {r.grantedBy ?? "—"} ·{" "}
                  {new Date(r.grantedAt).toISOString().slice(0, 10)}
                </span>
                {revokable && onRevoke ? (
                  <Button
                    data-testid={`role-revoke-${r.role}`}
                    variant="ghost"
                    size="sm"
                    type="button"
                    onClick={() => onRevoke(r.role)}
                    disabled={revokingKey === `tenancy:${r.role}`}
                  >
                    {revokingKey === `tenancy:${r.role}`
                      ? "Revoking…"
                      : "Revoke"}
                  </Button>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
