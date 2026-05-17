"use client";
/**
 * DomainCardGrid — dynamic, drag-and-drop governance view for /domains
 * (Step 3b of the canonical product arc).
 *
 * Each domain is a card. The card carries:
 *   - inline owner editing (click the @owner chip → dropdown of people →
 *     POST /api/governance/domain → optimistic UI; revert on error). The
 *     write triggers the ledger PEVR cycle so the audience sees it land in
 *     /trace within the next poll tick.
 *   - a drop target for resources. Drag a resource card from the
 *     "unassigned" lane into a domain → the resource is recorded against
 *     that domain (client-side bookkeeping today; the backend write
 *     lands with W2.K when resource-level grants come online).
 *
 * Polls /api/governance/domain every 10s — slower than the KPI tree (5s)
 * because governance moves slower than the KPI tree, but fast enough that
 * the audience sees the new owner ratify within a single demo beat.
 *
 * Field-Notebook tokens only. Square corners. No SaaS-pastel rounded pills.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  DndContext,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";

import { Receipt } from "../../lib/receipts";
import { usePoll } from "../../lib/use-poll";
import type {
  DomainRow as DomainRowModel,
  PersonRow,
} from "../../lib/ledger-client.types";

const UNASSIGNED_LANE_ID = "__unassigned__";

interface ResourceRef {
  id: string;
  label: string;
  classification: string;
}

export function DomainCardGrid({
  initialDomains,
  initialPeople,
  initialResources,
  currentPersonId,
}: {
  initialDomains: DomainRowModel[];
  initialPeople: PersonRow[];
  initialResources: ResourceRef[];
  /** Current admin Person id; recorded as `granted_by` on owner grants.
   *  Resolved server-side via `getCurrentPerson(companyId)`. */
  currentPersonId: string | null;
}) {
  // Live-polled domain set. The poll function is stable across renders, so
  // usePoll keeps the same interval timer regardless of re-renders driven
  // by inline edits.
  const { data: domainsData, lastTickAt } = usePoll<{
    domains: DomainRowModel[];
  }>(
    async () => {
      const r = await fetch("/api/governance/domain", { cache: "no-store" });
      if (!r.ok) throw new Error(`refresh failed: ${r.status}`);
      const j = (await r.json()) as { domains: DomainRowModel[] };
      return { domains: j.domains };
    },
    { intervalMs: 10_000, initial: { domains: initialDomains } },
  );

  // Optimistic owner overrides — applied on top of the polled snapshot. A
  // successful POST keeps the override until the next poll tick reflects
  // it; a failure reverts.
  const [optimistic, setOptimistic] = useState<Record<string, string>>({});

  const domains = useMemo<DomainRowModel[]>(() => {
    const src = domainsData?.domains ?? initialDomains;
    return src.map((d) => {
      const o = optimistic[d.domainId];
      if (!o || o === d.owner) return d;
      return { ...d, owner: o };
    });
  }, [domainsData, initialDomains, optimistic]);

  // Resource → domain assignment is local-only today; the backend write
  // (resource-level domain assignment) lands with W2.K. Map: resourceId
  // → domainId.
  const [assignments, setAssignments] = useState<Record<string, string>>({});

  const sensors = useSensors(useSensor(PointerSensor));

  /**
   * D6 — drag a Person chip onto a Domain card to grant `domain.owner`.
   *
   * Person draggables carry id `person:{personId}`. Resource draggables
   * carry the bare resource id (back-compat with the existing
   * resource-drag gesture). The drag-end handler discriminates on the
   * prefix.
   *
   * On a Person → Domain drop we POST `/api/people/{personId}/roles` with
   * `{facet: "domain", role: "owner", scope_id: domainId, granted_by:
   * currentPersonId}`. The read-side fold in `getRolesForPerson` keeps
   * every domain grant; the dashboard's owner column resolves to "latest
   * unrevoked owner per domain" so re-assigning a Person simply layers
   * a new grant. This is intentional: every reassignment is preserved
   * in the audit log.
   */
  const grantPersonAsOwner = useCallback(
    async (personId: string, domainId: string) => {
      // Optimistic apply.
      setOptimistic((prev) => ({ ...prev, [domainId]: personId }));
      try {
        // `granted_by` is the current admin (PersonChip-resolved) — falls
        // back to the target only if no current Person is wired (a
        // bootstrap edge case the layout redirect normally prevents). The
        // ledger entry records this verbatim in `granted_by` for audit.
        const grantedBy = currentPersonId ?? personId;
        const res = await fetch(`/api/people/${personId}/roles`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            facet: "domain",
            role: "owner",
            scope_id: domainId,
            granted_by: grantedBy,
          }),
        });
        if (!res.ok) throw new Error(`status ${res.status}`);
      } catch {
        setOptimistic((prev) => {
          const next = { ...prev };
          delete next[domainId];
          return next;
        });
      }
    },
    [currentPersonId],
  );

  const handleDragEnd = useCallback(
    (e: DragEndEvent) => {
      const activeId = String(e.active.id);
      const target = e.over?.id ? String(e.over.id) : null;
      if (!target) return;

      // Person → Domain owner-grant path (D6).
      if (activeId.startsWith("person:")) {
        const personId = activeId.slice("person:".length);
        if (target === UNASSIGNED_LANE_ID) return;
        void grantPersonAsOwner(personId, target);
        return;
      }

      // Resource → Domain client-side assignment path (existing gesture;
      // backend write lands with W2.K).
      const resourceId = activeId;
      setAssignments((prev) => {
        if (target === UNASSIGNED_LANE_ID) {
          const next = { ...prev };
          delete next[resourceId];
          return next;
        }
        return { ...prev, [resourceId]: target };
      });
    },
    [grantPersonAsOwner],
  );

  const setOwner = useCallback(
    async (domainId: string, personId: string) => {
      // Optimistic apply.
      setOptimistic((prev) => ({ ...prev, [domainId]: personId }));
      try {
        const res = await fetch("/api/governance/domain", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ domain_id: domainId, owner_person_id: personId }),
        });
        if (!res.ok) throw new Error(`status ${res.status}`);
      } catch {
        // Revert.
        setOptimistic((prev) => {
          const next = { ...prev };
          delete next[domainId];
          return next;
        });
      }
    },
    [],
  );

  const livenessLabel = lastTickAt
    ? `live · ${Math.max(1, Math.round((Date.now() - lastTickAt) / 1000))}s ago`
    : "live · connecting…";

  // Build per-domain resource lists from current assignments.
  const resourceLists = useMemo(() => {
    const map = new Map<string, ResourceRef[]>();
    for (const d of domains) map.set(d.domainId, []);
    map.set(UNASSIGNED_LANE_ID, []);
    for (const r of initialResources) {
      const did = assignments[r.id] ?? UNASSIGNED_LANE_ID;
      const list = map.get(did) ?? map.get(UNASSIGNED_LANE_ID)!;
      list.push(r);
    }
    return map;
  }, [domains, initialResources, assignments]);

  return (
    <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
      <div
        data-testid="domain-card-grid"
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        <span
          className="wb-mono"
          data-testid="domains-liveness"
          style={{
            alignSelf: "flex-end",
            fontSize: 10,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: "var(--wb-color-botanical-green-deep)",
          }}
        >
          {livenessLabel}
        </span>
        <PeopleLane people={initialPeople} />
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
            gap: 16,
          }}
        >
          {domains.map((d) => (
            <DomainCard
              key={d.domainId}
              domain={d}
              people={initialPeople}
              resources={resourceLists.get(d.domainId) ?? []}
              onOwnerChange={setOwner}
            />
          ))}
        </div>
        <UnassignedLane resources={resourceLists.get(UNASSIGNED_LANE_ID) ?? []} />
      </div>
    </DndContext>
  );
}

function DomainCard({
  domain,
  people,
  resources,
  onOwnerChange,
}: {
  domain: DomainRowModel;
  people: PersonRow[];
  resources: ResourceRef[];
  onOwnerChange: (domainId: string, personId: string) => Promise<void>;
}) {
  const sev =
    domain.classificationDefault === "pii" ||
    domain.classificationDefault === "restricted"
      ? "warn"
      : domain.classificationDefault === "public"
        ? "ok"
        : "neutral";

  const accent =
    sev === "warn"
      ? "var(--wb-color-sepia-warning)"
      : sev === "ok"
        ? "var(--wb-color-botanical-green)"
        : "var(--wb-color-aged-ink)";

  const { setNodeRef, isOver } = useDroppable({ id: domain.domainId });

  return (
    <article
      ref={setNodeRef}
      data-testid={`domain-card-${domain.domainId}`}
      data-sev={sev}
      data-drop-active={isOver ? "true" : "false"}
      style={{
        border: `1px solid ${isOver ? accent : "var(--wb-color-paper-edge)"}`,
        borderLeft: `3px solid ${accent}`,
        background: isOver
          ? "var(--wb-color-paper-deep)"
          : "var(--wb-color-paper)",
        padding: 16,
        display: "flex",
        flexDirection: "column",
        gap: 10,
        minHeight: 220,
      }}
    >
      <header
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 4,
        }}
      >
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          domain
        </span>
        <h3
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 22,
            fontWeight: 500,
            letterSpacing: "-0.005em",
          }}
        >
          {domain.name}
        </h3>
      </header>

      <OwnerPicker
        domainId={domain.domainId}
        currentOwner={domain.owner}
        people={people}
        onChange={onOwnerChange}
      />

      <span
        data-chip
        className="wb-mono"
        style={{
          alignSelf: "flex-start",
          fontSize: 10,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          padding: "3px 8px",
          border: `1px solid ${accent}`,
          color: accent,
          background:
            sev === "warn"
              ? "var(--wb-color-sepia-warning-soft)"
              : sev === "ok"
                ? "var(--wb-color-botanical-green-soft)"
                : "var(--wb-color-paper-deep)",
          borderRadius: 0,
        }}
      >
        {domain.classificationDefault}
      </span>

      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 6,
        }}
      >
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          resources · {resources.length}
        </span>
        <ul
          data-testid={`domain-resources-${domain.domainId}`}
          style={{
            margin: 0,
            padding: 0,
            listStyle: "none",
            display: "flex",
            flexDirection: "column",
            gap: 4,
            minHeight: 36,
          }}
        >
          {resources.length === 0 ? (
            <li
              style={{
                fontFamily: "var(--wb-font-serif)",
                fontStyle: "italic",
                fontSize: 12,
                color: "var(--wb-color-hash-gray)",
              }}
            >
              drop a resource here ↩
            </li>
          ) : (
            resources.map((r) => <ResourceChip key={r.id} resource={r} />)
          )}
        </ul>
      </div>

      <Receipt
        hash={domain.receipt.hash}
        source={domain.receipt.source}
        owner={domain.receipt.owner}
        classification={domain.receipt.classification}
        compact
      />
    </article>
  );
}

function OwnerPicker({
  domainId,
  currentOwner,
  people,
  onChange,
}: {
  domainId: string;
  currentOwner: string;
  people: PersonRow[];
  onChange: (domainId: string, personId: string) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);

  // Close on outside click / Escape.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!ref.current) return;
      if (!ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const peopleOptions = useMemo(() => {
    if (people.length === 0) return [];
    return people;
  }, [people]);

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button
        type="button"
        data-testid={`domain-owner-button-${domainId}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="wb-mono"
        style={{
          background: "transparent",
          border: "1px dashed var(--wb-color-paper-edge)",
          padding: "4px 8px",
          fontSize: 12,
          color: "var(--wb-color-aged-ink)",
          cursor: "pointer",
          textAlign: "left",
        }}
      >
        @{currentOwner} <span style={{ color: "var(--wb-color-hash-gray)" }}>▾</span>
      </button>
      {open ? (
        <ul
          role="listbox"
          data-testid={`domain-owner-list-${domainId}`}
          style={{
            position: "absolute",
            top: "calc(100% + 4px)",
            left: 0,
            zIndex: 20,
            margin: 0,
            padding: 4,
            listStyle: "none",
            background: "var(--wb-color-paper)",
            border: "1px solid var(--wb-color-aged-ink)",
            minWidth: 180,
            display: "flex",
            flexDirection: "column",
            gap: 2,
          }}
        >
          {peopleOptions.length === 0 ? (
            <li
              style={{
                padding: "4px 8px",
                fontFamily: "var(--wb-font-serif)",
                fontSize: 12,
                color: "var(--wb-color-hash-gray)",
              }}
            >
              no people in tenant yet
            </li>
          ) : (
            peopleOptions.map((p) => (
              <li key={p.personId}>
                <button
                  type="button"
                  data-testid={`domain-owner-pick-${domainId}-${p.personId}`}
                  onClick={async () => {
                    setOpen(false);
                    await onChange(domainId, p.displayName);
                  }}
                  className="wb-mono"
                  style={{
                    width: "100%",
                    background: "transparent",
                    border: "none",
                    textAlign: "left",
                    padding: "4px 8px",
                    fontSize: 12,
                    color: "var(--wb-color-aged-ink)",
                    cursor: "pointer",
                  }}
                >
                  @{p.displayName}
                </button>
              </li>
            ))
          )}
        </ul>
      ) : null}
    </div>
  );
}

function ResourceChip({ resource }: { resource: ResourceRef }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: resource.id,
  });
  return (
    <li
      ref={setNodeRef}
      data-testid={`resource-chip-${resource.id}`}
      data-dragging={isDragging ? "true" : "false"}
      {...attributes}
      {...listeners}
      style={{
        background: "var(--wb-color-paper-deep)",
        border: "1px solid var(--wb-color-paper-edge)",
        padding: "4px 8px",
        cursor: "grab",
        opacity: isDragging ? 0.5 : 1,
        display: "flex",
        justifyContent: "space-between",
        gap: 8,
      }}
    >
      <span
        className="wb-mono"
        style={{
          fontSize: 11,
          color: "var(--wb-color-aged-ink)",
        }}
      >
        {resource.label}
      </span>
      <span
        className="wb-mono"
        style={{
          fontSize: 9,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        {resource.classification}
      </span>
    </li>
  );
}

function UnassignedLane({ resources }: { resources: ResourceRef[] }) {
  const { setNodeRef, isOver } = useDroppable({ id: UNASSIGNED_LANE_ID });
  return (
    <section
      ref={setNodeRef}
      data-testid="unassigned-lane"
      style={{
        border: `1px dashed ${isOver ? "var(--wb-color-aged-ink)" : "var(--wb-color-paper-edge)"}`,
        background: isOver
          ? "var(--wb-color-paper-deep)"
          : "var(--wb-color-paper)",
        padding: 12,
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <span
        className="wb-mono"
        style={{
          fontSize: 10,
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        unassigned resources · {resources.length}
      </span>
      <ul
        style={{
          margin: 0,
          padding: 0,
          listStyle: "none",
          display: "flex",
          flexWrap: "wrap",
          gap: 6,
          minHeight: 36,
        }}
      >
        {resources.map((r) => (
          <ResourceChip key={r.id} resource={r} />
        ))}
      </ul>
    </section>
  );
}

/**
 * People lane (D6) — draggable Person chips. Drop one onto a domain card
 * to grant `domain.owner`. Empty when the tenant has no people yet.
 */
function PeopleLane({ people }: { people: PersonRow[] }) {
  if (people.length === 0) return null;
  return (
    <section
      data-testid="people-lane"
      style={{
        border: "1px dashed var(--wb-color-paper-edge)",
        padding: 12,
        display: "flex",
        flexDirection: "column",
        gap: 8,
        background: "var(--wb-color-paper)",
      }}
    >
      <span
        className="wb-mono"
        style={{
          fontSize: 10,
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        people · drag onto a domain to grant ownership
      </span>
      <ul
        style={{
          margin: 0,
          padding: 0,
          listStyle: "none",
          display: "flex",
          flexWrap: "wrap",
          gap: 6,
        }}
      >
        {people.map((p) => (
          <DraggablePersonChip key={p.personId} person={p} />
        ))}
      </ul>
    </section>
  );
}

function DraggablePersonChip({ person }: { person: PersonRow }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `person:${person.personId}`,
  });
  return (
    <li
      ref={setNodeRef}
      data-testid={`draggable-person-${person.personId}`}
      data-dragging={isDragging ? "true" : "false"}
      {...attributes}
      {...listeners}
      style={{
        background: "var(--wb-color-paper-deep)",
        border: "1px solid var(--wb-color-aged-ink)",
        padding: "4px 10px",
        cursor: "grab",
        opacity: isDragging ? 0.5 : 1,
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
      }}
    >
      <span
        className="wb-mono"
        style={{ fontSize: 11, color: "var(--wb-color-aged-ink)" }}
      >
        @{person.displayName}
      </span>
      {person.position ? (
        <span
          className="wb-mono"
          style={{
            fontSize: 9,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          {person.position}
        </span>
      ) : null}
    </li>
  );
}
