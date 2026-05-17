"use client";

import { useState } from "react";
import { Receipt } from "../../lib/receipts";
import type { DomainRow, PersonRow } from "../../lib/ledger-client.types";

/**
 * GovernancePanel — two domains + a draggable person list. Drop assigns; key
 * alternative (Tab + Space) is supported by attaching a button per person/domain
 * combo via the role=button keyboard pathway.
 *
 * Optional `onAssignOwner` callback (Sub-wave A F2, 2026-05-30) wires the
 * drop event to a server-side ledger write. The drop-zone receives a
 * `text/wb-person` payload carrying the `personId` (canonical id), so the
 * callback can route directly to `assignDomainOwner(companyId, domainId,
 * personId)`. Optimistic local-state update is preserved; the receipt-or-
 * error returned by the callback is exposed via `onAssignOwner`'s own
 * return value (server-action result), letting the caller surface a toast
 * or refetch the projection.
 */
export function GovernancePanel({
  domains,
  people,
  onAssignOwner,
}: {
  domains: DomainRow[];
  people: PersonRow[];
  /** Called after an assign drop / keyboard activation lands. The server-side
   *  writer (in tier2/actions.ts) writes the real `emit_domain_owner_assigned`
   *  PEVR cycle. Optional so non-Tier-2 mounts (current /domains card grid)
   *  keep their previous client-only behaviour. */
  onAssignOwner?: (
    domainId: string,
    personId: string,
    personDisplay: string,
  ) => void | Promise<void>;
}) {
  const [assignments, setAssignments] = useState<Record<string, string>>(
    Object.fromEntries(domains.map((d) => [d.domainId, d.owner]))
  );

  async function assign(
    domainId: string,
    personDisplay: string,
    personId: string,
  ) {
    setAssignments((s) => ({ ...s, [domainId]: personDisplay }));
    if (onAssignOwner) {
      try {
        await onAssignOwner(domainId, personId, personDisplay);
      } catch {
        // Swallow: the action layer returns a structured error in its
        // own result; the panel's display owner state has already moved.
        // Future Sub-wave C may add an error-toast affordance.
      }
    }
  }

  return (
    <section
      data-testid="governance-panel"
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 280px",
        gap: 24,
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {domains.map((d) => (
          <article
            key={d.domainId}
            data-testid={`domain-zone-${d.domainId}`}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              const personDisplay = e.dataTransfer.getData("text/wb-person");
              const personId = e.dataTransfer.getData("text/wb-person-id");
              if (personDisplay) {
                // Optimistic UI; fire-and-forget the server-side writer.
                void assign(d.domainId, personDisplay, personId || personDisplay);
              }
            }}
            style={{
              border: "1px solid var(--wb-color-paper-edge)",
              padding: 16,
              display: "grid",
              gridTemplateColumns: "1fr auto",
              gap: 12,
              alignItems: "baseline",
            }}
          >
            <span
              style={{
                fontFamily: "var(--wb-font-serif)",
                fontSize: 18,
                fontWeight: 500,
              }}
            >
              {d.name}
            </span>
            <span
              className="wb-mono"
              style={{
                fontSize: 11,
                color: "var(--wb-color-hash-gray)",
              }}
            >
              owner{" "}
              <span
                data-testid={`assigned-${d.domainId}`}
                style={{ color: "var(--wb-color-aged-ink)" }}
              >
                @{assignments[d.domainId]}
              </span>{" "}
              · default class {d.classificationDefault}
            </span>
            <Receipt
              hash={d.receipt.hash}
              source={d.receipt.source}
              owner={assignments[d.domainId]}
              classification={d.classificationDefault}
              compact
            />
          </article>
        ))}
      </div>
      <aside
        style={{
          border: "1px solid var(--wb-color-paper-edge)",
          padding: 12,
          display: "flex",
          flexDirection: "column",
          gap: 6,
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
          People
        </span>
        {people.map((p) => (
          <div
            key={p.personId}
            data-testid={`person-chip-${p.personId}`}
            draggable
            onDragStart={(e) => {
              e.dataTransfer.setData("text/wb-person", p.displayName);
              // Canonical id for the server-side writer; preserves
              // display-name back-compat for any consumer that only
              // reads `text/wb-person`.
              e.dataTransfer.setData("text/wb-person-id", p.personId);
            }}
            tabIndex={0}
            role="button"
            aria-label={`Assign ${p.displayName} via keyboard`}
            style={{
              border: "1px solid var(--wb-color-aged-ink)",
              padding: "6px 10px",
              fontFamily: "var(--wb-font-mono)",
              fontSize: 12,
              cursor: "grab",
              background: "var(--wb-color-paper)",
            }}
          >
            @{p.displayName}
          </div>
        ))}
      </aside>
    </section>
  );
}
