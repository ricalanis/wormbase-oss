"use client";
/**
 * BulkConfirmDrawer — admin confirms many proposed Persons in one POST.
 *
 * W2.A6 of `docs/superpowers/plans/2026-04-28-production-hardening.md`.
 *
 * The drawer renders a checkbox list of pending proposals, supports
 * "select all," and dispatches a single `POST /api/v1/people/bulk-confirm`
 * carrying the full `person_ids[]`. The dashboard route threads the
 * current admin's Person id through as `confirmed_by`, then forwards to
 * worm-core which writes one `emit_person_confirmed` PEVR cycle per id
 * (4 ledger entries each).
 *
 * Atomicity contract: the wire request is treated as all-or-nothing.
 * On success the page refreshes; on failure the error surfaces and the
 * selection is preserved so the admin can retry.
 *
 * Differs from PendingProposals: this is the new bulk-first surface
 * (checkbox + single POST) for production-hardened /people. The legacy
 * one-at-a-time `Confirm` / `Archive` buttons remain available there for
 * single-row operations.
 */
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@wormbase/design";
import type { PersonRow as PersonRowModel } from "../../lib/ledger-client.types";
import { formatProposalProvenance, relativeTime } from "../../lib/people-display";
import { chipStyle } from "./_styles";

export interface BulkConfirmDrawerProps {
  proposals: PersonRowModel[];
}

export function BulkConfirmDrawer({ proposals }: BulkConfirmDrawerProps) {
  const router = useRouter();
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(proposals.map((p) => p.personId)),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const allSelected = useMemo(
    () => proposals.length > 0 && selected.size === proposals.length,
    [proposals.length, selected.size],
  );
  const noneSelected = selected.size === 0;

  function toggle(id: string) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  }

  function toggleAll() {
    if (allSelected) {
      setSelected(new Set());
    } else {
      setSelected(new Set(proposals.map((p) => p.personId)));
    }
  }

  async function confirmSelected() {
    if (selected.size === 0) {
      setError("pick at least one proposal to confirm");
      return;
    }
    setBusy(true);
    setError(null);
    setSuccess(null);
    try {
      const res = await fetch("/api/v1/people/bulk-confirm", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          person_ids: Array.from(selected),
        }),
      });
      if (!res.ok) {
        const j = (await res.json().catch(() => ({}))) as { message?: string };
        throw new Error(j.message ?? `bulk-confirm failed (${res.status})`);
      }
      const result = (await res.json()) as {
        confirmed_count: number;
        person_ids: string[];
        entry_ids: string[];
      };
      setSuccess(
        `${result.confirmed_count} proposal${
          result.confirmed_count === 1 ? "" : "s"
        } confirmed · ${result.entry_ids.length} ledger entries written.`,
      );
      // Clear selection so a follow-on render with a smaller proposals list
      // doesn't carry stale ids.
      setSelected(new Set());
      router.refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (proposals.length === 0) return null;

  return (
    <section
      data-testid="bulk-confirm-drawer"
      style={{
        border: "1px solid var(--wb-color-sepia-warning)",
        background: "var(--wb-color-sepia-warning-soft)",
        padding: "16px 20px",
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 16,
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: "var(--wb-color-sepia-warning-deep)",
            }}
          >
            Bulk-confirm · One transaction
          </span>
          <h2
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 22,
              fontWeight: 500,
            }}
          >
            Pending Proposals · {proposals.length}
          </h2>
          <p
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              color: "var(--wb-color-aged-ink-soft)",
              fontSize: 13,
            }}
          >
            Pick rows to confirm; the request lands one ledger entry per
            Person, all in one wire call.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button
            type="button"
            data-testid="bulk-confirm-toggle-all"
            onClick={toggleAll}
            style={{
              fontFamily: "var(--wb-font-mono)",
              fontSize: 11,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              padding: "4px 10px",
              border: "1px solid var(--wb-color-aged-ink)",
              background: "var(--wb-color-paper)",
              color: "var(--wb-color-aged-ink)",
              cursor: "pointer",
            }}
          >
            {allSelected ? "Clear selection" : "Select all"}
          </button>
          <Button
            data-testid="bulk-confirm-submit"
            variant="primary"
            size="sm"
            onClick={confirmSelected}
            disabled={busy || noneSelected}
          >
            {busy
              ? "Confirming…"
              : `Confirm ${selected.size}/${proposals.length}`}
          </Button>
        </div>
      </header>

      {error ? (
        <div
          data-testid="bulk-confirm-error"
          role="alert"
          className="wb-mono"
          style={{
            fontSize: 12,
            color: "var(--wb-color-sepia-warning-deep)",
            border: "1px solid var(--wb-color-sepia-warning-deep)",
            padding: "6px 10px",
            background: "var(--wb-color-paper)",
          }}
        >
          {error}
        </div>
      ) : null}
      {success ? (
        <div
          data-testid="bulk-confirm-success"
          role="status"
          className="wb-mono"
          style={{
            fontSize: 12,
            color: "var(--wb-color-botanical-green-deep)",
            border: "1px solid var(--wb-color-botanical-green)",
            padding: "6px 10px",
            background: "var(--wb-color-botanical-green-soft)",
          }}
        >
          {success}
        </div>
      ) : null}

      <ul
        data-testid="bulk-confirm-list"
        style={{
          listStyle: "none",
          padding: 0,
          margin: 0,
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}
      >
        {proposals.map((p) => {
          const identity = p.identities[0];
          const platform = identity?.platform ?? "—";
          const platformUserId = identity?.platformUserId ?? "—";
          const checked = selected.has(p.personId);
          const provenance = formatProposalProvenance(
            identity?.proposedBy ?? null,
            identity,
          );
          const addedAtRel = identity?.addedAt
            ? relativeTime(identity.addedAt)
            : null;
          return (
            <li
              key={p.personId}
              data-testid={`bulk-confirm-row-${p.personId}`}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 16,
                flexWrap: "wrap",
                padding: "10px 12px",
                background: "var(--wb-color-paper)",
                border: "1px solid var(--wb-color-paper-edge)",
              }}
            >
              <label
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  cursor: "pointer",
                  flex: "1 1 200px",
                }}
              >
                <input
                  type="checkbox"
                  data-testid={`bulk-confirm-check-${p.personId}`}
                  checked={checked}
                  onChange={() => toggle(p.personId)}
                  disabled={busy}
                />
                <span
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: 2,
                  }}
                >
                  <span
                    style={{
                      fontFamily: "var(--wb-font-serif)",
                      fontSize: 15,
                      fontWeight: 500,
                    }}
                  >
                    {p.displayName}
                  </span>
                  <span
                    className="wb-mono"
                    style={{
                      fontSize: 11,
                      color: "var(--wb-color-hash-gray)",
                    }}
                  >
                    {p.email ?? "no email"}
                  </span>
                </span>
              </label>
              <span
                className="wb-mono"
                data-testid={`bulk-confirm-platform-${p.personId}`}
                style={chipStyle("muted")}
              >
                {platform}
              </span>
              <span
                className="wb-mono"
                data-testid={`bulk-confirm-platform-user-${p.personId}`}
                style={{
                  fontSize: 11,
                  color: "var(--wb-color-aged-ink-soft)",
                }}
              >
                {platformUserId}
              </span>
              <span
                data-testid={`bulk-confirm-provenance-${p.personId}`}
                data-provenance-kind={provenance.kind}
                style={{
                  flexBasis: "100%",
                  fontFamily: "var(--wb-font-serif)",
                  fontSize: 12,
                  fontStyle: "italic",
                  color: "var(--wb-color-aged-ink-soft)",
                  marginLeft: 24,
                }}
              >
                {provenance.highlight ? (
                  <>
                    {provenance.label.replace(provenance.highlight, "")}
                    <strong
                      className="wb-mono"
                      style={{
                        fontStyle: "normal",
                        color: "var(--wb-color-aged-ink)",
                      }}
                    >
                      {provenance.highlight}
                    </strong>
                  </>
                ) : (
                  provenance.label
                )}
                {addedAtRel ? (
                  <span
                    style={{
                      color: "var(--wb-color-hash-gray)",
                      marginLeft: 6,
                    }}
                  >
                    · {addedAtRel}
                  </span>
                ) : null}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
