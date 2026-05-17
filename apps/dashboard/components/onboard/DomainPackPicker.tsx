/**
 * Tier 2 domain pack picker — Onboarding Sub-wave C (2026-05-30).
 *
 * Client component renders the 4 canonical pack rows + a per-row
 * "Pick" button that calls ``selectDomainPackAction`` server action.
 * The action threads the current admin Person UUID through
 * ``getCurrentPerson``; this component knows only the pack id.
 *
 * The picker is idempotent at the worm-core layer — a re-pick on a
 * tenant that already has a pack-selection surfaces honestly as
 * "already seeded" in the receipt strip.
 */
"use client";

import { useCallback, useState } from "react";

import { selectDomainPackAction } from "../../app/(app)/onboard/domain/actions";
import type { DomainPackDescriptor } from "../../lib/onboard";
import { CapabilityBadges } from "./CapabilityBadges";

interface PickReceipt {
  packId: string;
  packVersion: string;
  alreadySeeded: boolean;
  domainIds: string[];
  policyIds: string[];
}

interface PickError {
  packId: string;
  message: string;
}

interface Props {
  packs: readonly DomainPackDescriptor[];
}

export function DomainPackPicker({ packs }: Props): React.JSX.Element {
  const [busyPackId, setBusyPackId] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<PickReceipt | null>(null);
  const [error, setError] = useState<PickError | null>(null);

  const handlePick = useCallback(async (packId: string) => {
    setBusyPackId(packId);
    setError(null);
    setReceipt(null);
    try {
      const result = await selectDomainPackAction(packId);
      if (result.ok) {
        setReceipt({
          packId: result.packId ?? packId,
          packVersion: result.packVersion ?? "v1.0",
          alreadySeeded: Boolean(result.alreadySeeded),
          domainIds: result.domainIds ?? [],
          policyIds: result.policyIds ?? [],
        });
      } else {
        setError({ packId, message: result.error ?? "unknown error" });
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError({ packId, message: msg });
    } finally {
      setBusyPackId(null);
    }
  }, []);

  return (
    <div
      data-testid="onboard-domain-pack-picker"
      style={{ display: "flex", flexDirection: "column", gap: 12 }}
    >
      <ul
        style={{
          listStyle: "none",
          padding: 0,
          margin: 0,
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
          gap: 12,
        }}
      >
        {packs.map((pack) => {
          const isBusy = busyPackId === pack.packId;
          const isPicked = receipt?.packId === pack.packId;
          const isError = error?.packId === pack.packId;
          return (
            <li
              key={pack.packId}
              data-testid={`onboard-domain-pack-${pack.packId}`}
              style={{
                border: "1px solid var(--wb-color-paper-edge)",
                background: "var(--wb-color-paper)",
                padding: 14,
                display: "flex",
                flexDirection: "column",
                gap: 8,
              }}
            >
              <header>
                <strong
                  style={{
                    fontFamily: "var(--wb-font-serif)",
                    fontSize: 16,
                  }}
                >
                  {pack.label}
                </strong>
                <code
                  className="wb-mono"
                  style={{
                    fontSize: 11,
                    color: "var(--wb-color-hash-gray)",
                    display: "block",
                  }}
                >
                  {pack.packId} · {pack.packVersion} · {pack.domainCount} domain
                  {pack.domainCount === 1 ? "" : "s"}
                </code>
              </header>
              <p
                style={{
                  margin: 0,
                  fontFamily: "var(--wb-font-serif)",
                  fontStyle: "italic",
                  color: "var(--wb-color-hash-gray)",
                  fontSize: 12,
                }}
              >
                {pack.description}
              </p>
              <CapabilityBadges
                kind="domain"
                id={pack.packId}
                status="production"
                statusNote="Pack pick fans out domain + policy entries in one PEVR batch."
              />
              <button
                type="button"
                data-testid={`onboard-domain-pack-pick-${pack.packId}`}
                onClick={() => handlePick(pack.packId)}
                disabled={isBusy || busyPackId !== null}
                className="wb-mono"
                style={{
                  fontSize: 11,
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                  padding: "8px 14px",
                  border: "1px solid var(--wb-color-aged-ink)",
                  background: isBusy
                    ? "var(--wb-color-paper-edge)"
                    : "var(--wb-color-aged-ink)",
                  color: "var(--wb-color-paper)",
                  cursor: isBusy ? "wait" : "pointer",
                }}
              >
                {isBusy ? "Picking…" : `Pick ${pack.label}`}
              </button>
              {isPicked && receipt && (
                <div
                  data-testid={`onboard-domain-pack-receipt-${pack.packId}`}
                  style={{
                    fontFamily: "var(--wb-font-serif)",
                    fontSize: 12,
                    color: receipt.alreadySeeded
                      ? "var(--wb-color-hash-gray)"
                      : "var(--wb-color-aged-ink)",
                    background: "var(--wb-color-paper-edge)",
                    padding: 6,
                  }}
                >
                  {receipt.alreadySeeded
                    ? `Already seeded — pack ${receipt.packId} (${receipt.packVersion}) earlier.`
                    : `Seeded ${receipt.domainIds.length} domain${receipt.domainIds.length === 1 ? "" : "s"} · ${receipt.policyIds.length} polic${receipt.policyIds.length === 1 ? "y" : "ies"}.`}
                </div>
              )}
              {isError && error && (
                <div
                  data-testid={`onboard-domain-pack-error-${pack.packId}`}
                  style={{
                    fontFamily: "var(--wb-font-serif)",
                    fontSize: 12,
                    color: "var(--wb-color-aged-ink)",
                    background: "var(--wb-color-paper-edge)",
                    padding: 6,
                  }}
                >
                  Error: {error.message}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
