"use client";
/**
 * PendingProposals — Persons the worm has auto-discovered (A4 identity
 * discovery loop) but admin hasn't confirmed.
 *
 * Each row offers Confirm / Archive buttons that POST to the dashboard
 * /api/people/[id]/{confirm,archive} endpoints — those calls flow through
 * to worm-core's HTTP write API and produce hash-chained PEVR ledger
 * entries. A "Confirm all" header button iterates over the proposals.
 *
 * Section is hidden entirely when there are no proposals — the calling
 * page filters on `status === "proposed"` before rendering us.
 *
 * A5 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 */
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@wormbase/design";
import type { PersonRow as PersonRowModel } from "../../lib/ledger-client.types";
import { chipStyle } from "./_styles";

const ADMIN_ACTOR_ID = "dashboard-admin";

export interface PendingProposalsProps {
  proposals: PersonRowModel[];
  /** Optional current admin Person id (UUID). Defaults to a stable placeholder
   *  so the surface doesn't fail closed if no Person chip is wired yet. The
   *  ledger entry will record this string verbatim in `confirmed_by`. */
  adminPersonId?: string;
}

export function PendingProposals({
  proposals,
  adminPersonId = ADMIN_ACTOR_ID,
}: PendingProposalsProps) {
  const router = useRouter();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (proposals.length === 0) return null;

  async function confirmOne(personId: string) {
    setBusyId(personId);
    setError(null);
    try {
      const res = await fetch(`/api/people/${personId}/confirm`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ confirmed_by: adminPersonId }),
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as {
          message?: string;
        };
        throw new Error(body.message ?? `confirm failed (${res.status})`);
      }
      router.refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusyId(null);
    }
  }

  async function archiveOne(personId: string) {
    setBusyId(personId);
    setError(null);
    try {
      const res = await fetch(`/api/people/${personId}/archive`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          archived_by: adminPersonId,
          reason: "rejected from pending proposals",
        }),
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as {
          message?: string;
        };
        throw new Error(body.message ?? `archive failed (${res.status})`);
      }
      router.refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusyId(null);
    }
  }

  async function confirmAll() {
    setBulkBusy(true);
    setError(null);
    try {
      for (const p of proposals) {
        const res = await fetch(`/api/people/${p.personId}/confirm`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ confirmed_by: adminPersonId }),
        });
        if (!res.ok) {
          const body = (await res.json().catch(() => ({}))) as {
            message?: string;
          };
          throw new Error(body.message ?? `confirm failed for ${p.displayName}`);
        }
      }
      router.refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBulkBusy(false);
    }
  }

  return (
    <section
      data-testid="pending-proposals"
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
            Auto-discovered · Admin confirm
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
            The worm proposed these Persons from chatter. Confirm to activate or
            archive to reject.
          </p>
        </div>
        {proposals.length > 1 ? (
          <Button
            data-testid="pending-confirm-all"
            variant="primary"
            size="sm"
            onClick={confirmAll}
            disabled={bulkBusy}
          >
            {bulkBusy ? "Confirming…" : "Confirm all"}
          </Button>
        ) : null}
      </header>

      {error ? (
        <div
          data-testid="pending-error"
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

      <ul
        data-testid="pending-proposals-list"
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
          const proposedBy =
            (typeof p.receipt.owner === "string" && p.receipt.owner) ||
            "system";
          return (
            <li
              key={p.personId}
              data-testid={`pending-row-${p.personId}`}
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
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 2,
                  minWidth: 200,
                  flex: "1 1 200px",
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
                  style={{ fontSize: 11, color: "var(--wb-color-hash-gray)" }}
                >
                  {p.email ?? "no email"}
                </span>
              </div>
              <span
                className="wb-mono"
                data-testid={`pending-platform-${p.personId}`}
                style={chipStyle("muted")}
              >
                {platform}
              </span>
              <span
                className="wb-mono"
                data-testid={`pending-platform-user-${p.personId}`}
                style={{
                  fontSize: 11,
                  color: "var(--wb-color-aged-ink-soft)",
                }}
              >
                {platformUserId}
              </span>
              <span
                className="wb-mono"
                style={{
                  fontSize: 10,
                  color: "var(--wb-color-hash-gray)",
                  marginLeft: "auto",
                }}
              >
                proposed by {proposedBy}
              </span>
              <div style={{ display: "flex", gap: 8 }}>
                <Button
                  data-testid={`pending-confirm-${p.personId}`}
                  variant="primary"
                  size="sm"
                  onClick={() => confirmOne(p.personId)}
                  disabled={busyId === p.personId || bulkBusy}
                >
                  Confirm
                </Button>
                <Button
                  data-testid={`pending-archive-${p.personId}`}
                  variant="secondary"
                  size="sm"
                  onClick={() => archiveOne(p.personId)}
                  disabled={busyId === p.personId || bulkBusy}
                >
                  Archive
                </Button>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
