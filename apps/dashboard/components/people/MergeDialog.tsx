"use client";
/**
 * MergeDialog — admin merges two Persons that turn out to be the same human.
 *
 * Triggered from PersonDetailDrawer's "Merge with another Person..." button.
 * The current Person (the one whose drawer is open) is the keeper; the
 * admin picks a second Person to be the mergee. On confirm, POSTs to
 * `/api/people/merge`, which calls worm-core's merge endpoint.
 *
 * Three steps:
 *   1. Display the keeper (read-only).
 *   2. Pick a mergee from the roster (typeahead). Show a side-by-side
 *      preview of both Persons' identities with arrows showing where
 *      identities will move.
 *   3. Confirm. Big red button; warning that mergee will be archived.
 *
 * A6 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 */
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Input } from "@wormbase/design";
import type { PersonRow as PersonRowModel } from "../../lib/ledger-client.types";
import { chipStyle } from "./_styles";

const ADMIN_ACTOR_ID = "dashboard-admin";

export interface MergeDialogProps {
  keeperId: string;
  keeperName: string;
  open: boolean;
  onClose: () => void;
  /** Override the actor id (defaults to dashboard-admin). */
  adminPersonId?: string;
  /** Optional success callback — caller can refresh the drawer. */
  onMerged?: (result: {
    keeper_id: string;
    mergee_id: string;
    identities_moved: number;
  }) => void;
}

interface PeopleListEnvelope {
  persons: PersonRowModel[];
}

export function MergeDialog({
  keeperId,
  keeperName,
  open,
  onClose,
  adminPersonId = ADMIN_ACTOR_ID,
  onMerged,
}: MergeDialogProps) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [persons, setPersons] = useState<PersonRowModel[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [mergeeId, setMergeeId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void (async () => {
      setLoadError(null);
      try {
        const res = await fetch("/api/people");
        if (!res.ok) throw new Error(`fetch failed (${res.status})`);
        const j = (await res.json()) as PeopleListEnvelope;
        if (cancelled) return;
        setPersons(j.persons ?? []);
      } catch (err) {
        if (cancelled) return;
        setLoadError((err as Error).message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open]);

  // Reset transient state when reopened.
  useEffect(() => {
    if (open) {
      setMergeeId(null);
      setQuery("");
      setError(null);
      setSuccess(null);
    }
  }, [open]);

  const candidates = useMemo(() => {
    const q = query.trim().toLowerCase();
    return persons
      .filter((p) => p.personId !== keeperId && p.status !== "archived")
      .filter((p) => {
        if (!q) return true;
        const hay = [p.displayName ?? "", p.email ?? "", p.personId]
          .join(" ")
          .toLowerCase();
        return hay.includes(q);
      })
      .slice(0, 8);
  }, [persons, query, keeperId]);

  const mergee = useMemo(
    () => persons.find((p) => p.personId === mergeeId) ?? null,
    [persons, mergeeId],
  );

  async function confirmMerge() {
    if (!mergee) {
      setError("pick a Person to merge with first");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/people/merge", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          keeper_id: keeperId,
          mergee_id: mergee.personId,
          merged_by: adminPersonId,
        }),
      });
      if (!res.ok) {
        const j = (await res.json().catch(() => ({}))) as { message?: string };
        throw new Error(j.message ?? `merge failed (${res.status})`);
      }
      const result = (await res.json()) as {
        keeper_id: string;
        mergee_id: string;
        identities_moved: number;
      };
      setSuccess(
        `Merge complete: ${result.identities_moved} identities moved to ${keeperName}.`,
      );
      onMerged?.(result);
      router.refresh();
      // Close shortly after success so the user sees the confirmation.
      setTimeout(() => onClose(), 800);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!open) return null;

  return (
    <div
      data-testid="merge-dialog"
      role="dialog"
      aria-label="Merge persons"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 70,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <button
        data-testid="merge-scrim"
        aria-label="Close merge dialog"
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
      <div
        style={{
          position: "relative",
          width: "min(640px, 94vw)",
          maxHeight: "92vh",
          overflowY: "auto",
          background: "var(--wb-color-paper)",
          border: "1px solid var(--wb-color-aged-ink)",
          padding: "24px 28px",
          display: "flex",
          flexDirection: "column",
          gap: 16,
        }}
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
            People · Merge identities
          </span>
          <h2
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 24,
              fontWeight: 500,
            }}
          >
            Merge into {keeperName}
          </h2>
          <p
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 13,
              color: "var(--wb-color-aged-ink)",
            }}
          >
            Move all identities from another Person onto{" "}
            <span className="wb-mono">{keeperId.slice(0, 8)}</span>. The
            other Person will be archived.
          </p>
        </header>

        <section
          data-testid="merge-step-keeper"
          style={{ display: "flex", flexDirection: "column", gap: 6 }}
        >
          <SectionTitle>1 · Keeper (this Person)</SectionTitle>
          <div
            style={{
              border: "1px solid var(--wb-color-paper-edge)",
              padding: "8px 12px",
              background: "var(--wb-color-paper-deep)",
            }}
          >
            <div
              style={{
                fontFamily: "var(--wb-font-serif)",
                fontSize: 16,
              }}
            >
              {keeperName}
            </div>
            <div
              className="wb-mono"
              style={{ fontSize: 11, color: "var(--wb-color-hash-gray)" }}
            >
              {keeperId}
            </div>
          </div>
        </section>

        <section
          data-testid="merge-step-pick"
          style={{ display: "flex", flexDirection: "column", gap: 6 }}
        >
          <SectionTitle>2 · Mergee (pick another Person)</SectionTitle>
          {loadError ? (
            <div
              data-testid="merge-load-error"
              role="alert"
              className="wb-mono"
              style={{
                fontSize: 12,
                color: "var(--wb-color-sepia-warning-deep)",
              }}
            >
              {loadError}
            </div>
          ) : null}
          <Input
            label="Search by name, email, or id"
            data-testid="merge-search"
            placeholder="bob@x.co or U-bob"
            value={query}
            onChange={(e) => setQuery(e.currentTarget.value)}
          />
          <ul
            data-testid="merge-candidates"
            style={{
              listStyle: "none",
              padding: 0,
              margin: 0,
              border: "1px solid var(--wb-color-paper-edge)",
              maxHeight: 180,
              overflowY: "auto",
            }}
          >
            {candidates.length === 0 ? (
              <li
                data-testid="merge-candidates-empty"
                style={{
                  padding: "8px 12px",
                  fontStyle: "italic",
                  fontFamily: "var(--wb-font-serif)",
                  fontSize: 13,
                  color: "var(--wb-color-hash-gray)",
                }}
              >
                no candidates
              </li>
            ) : (
              candidates.map((p) => (
                <li key={p.personId}>
                  <button
                    type="button"
                    data-testid={`merge-candidate-${p.personId}`}
                    onClick={() => setMergeeId(p.personId)}
                    style={{
                      width: "100%",
                      textAlign: "left",
                      padding: "8px 12px",
                      border: "none",
                      borderBottom: "1px dashed var(--wb-color-paper-edge)",
                      background:
                        mergeeId === p.personId
                          ? "var(--wb-color-paper-deep)"
                          : "transparent",
                      cursor: "pointer",
                      fontFamily: "var(--wb-font-serif)",
                      fontSize: 14,
                      display: "flex",
                      flexDirection: "column",
                      gap: 2,
                    }}
                  >
                    <span>{p.displayName ?? "(unnamed)"}</span>
                    <span
                      className="wb-mono"
                      style={{
                        fontSize: 10,
                        color: "var(--wb-color-hash-gray)",
                      }}
                    >
                      {p.email ?? "no email"} · {p.personId.slice(0, 8)} ·{" "}
                      {p.identities.length} identities
                    </span>
                  </button>
                </li>
              ))
            )}
          </ul>
        </section>

        {mergee ? (
          <section
            data-testid="merge-preview"
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 24px 1fr",
              gap: 12,
              border: "1px solid var(--wb-color-paper-edge)",
              padding: 12,
            }}
          >
            <PreviewColumn
              testid="merge-preview-mergee"
              title="From mergee"
              name={mergee.displayName ?? "(unnamed)"}
              identities={mergee.identities.map((i) => ({
                platform: i.platform,
                platformUserId: i.platformUserId,
              }))}
            />
            <div
              aria-hidden="true"
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontFamily: "var(--wb-font-serif)",
                fontSize: 18,
                color: "var(--wb-color-hash-gray)",
              }}
            >
              →
            </div>
            <PreviewColumn
              testid="merge-preview-keeper"
              title="To keeper"
              name={keeperName}
              identities={[]}
              footnote="(merged identities will appear here)"
            />
          </section>
        ) : null}

        <section
          data-testid="merge-step-confirm"
          style={{ display: "flex", flexDirection: "column", gap: 8 }}
        >
          <SectionTitle>3 · Confirm</SectionTitle>
          <div
            className="wb-mono"
            style={{
              fontSize: 11,
              padding: "8px 12px",
              border: "1px solid var(--wb-color-sepia-warning)",
              background: "var(--wb-color-sepia-warning-soft)",
              color: "var(--wb-color-sepia-warning-deep)",
            }}
          >
            {mergee
              ? `${mergee.displayName ?? mergee.personId} will be archived. All of their identities will move to ${keeperName}. This is reversible only via split.`
              : "pick a Person above to enable confirm"}
          </div>
          {error ? (
            <div
              data-testid="merge-error"
              role="alert"
              className="wb-mono"
              style={{
                fontSize: 12,
                color: "var(--wb-color-sepia-warning-deep)",
                border: "1px solid var(--wb-color-sepia-warning-deep)",
                padding: "6px 10px",
              }}
            >
              {error}
            </div>
          ) : null}
          {success ? (
            <div
              data-testid="merge-success"
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
          <div
            style={{
              display: "flex",
              justifyContent: "flex-end",
              gap: 10,
              marginTop: 4,
            }}
          >
            <Button
              type="button"
              variant="ghost"
              size="sm"
              data-testid="merge-cancel"
              onClick={onClose}
            >
              Cancel
            </Button>
            <button
              type="button"
              data-testid="merge-confirm"
              onClick={confirmMerge}
              disabled={busy || !mergee}
              style={{
                padding: "8px 16px",
                fontFamily: "var(--wb-font-mono)",
                fontSize: 12,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                color: "var(--wb-color-paper)",
                background:
                  busy || !mergee
                    ? "var(--wb-color-hash-gray)"
                    : "var(--wb-color-sepia-warning-deep)",
                border: "1px solid var(--wb-color-aged-ink)",
                cursor: busy || !mergee ? "not-allowed" : "pointer",
                borderRadius: 0,
              }}
            >
              {busy ? "Merging…" : "Merge & archive mergee"}
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3
      style={{
        margin: 0,
        fontFamily: "var(--wb-font-serif)",
        fontSize: 14,
        fontWeight: 500,
        color: "var(--wb-color-aged-ink)",
      }}
    >
      {children}
    </h3>
  );
}

function PreviewColumn({
  testid,
  title,
  name,
  identities,
  footnote,
}: {
  testid: string;
  title: string;
  name: string;
  identities: { platform: string; platformUserId: string }[];
  footnote?: string;
}) {
  return (
    <div
      data-testid={testid}
      style={{ display: "flex", flexDirection: "column", gap: 6 }}
    >
      <span
        className="wb-mono"
        style={{
          fontSize: 10,
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        {title}
      </span>
      <span
        style={{
          fontFamily: "var(--wb-font-serif)",
          fontSize: 14,
          fontWeight: 500,
        }}
      >
        {name}
      </span>
      {identities.length > 0 ? (
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {identities.map((i) => (
            <li
              key={`${i.platform}|${i.platformUserId}`}
              style={{
                display: "flex",
                gap: 6,
                padding: "2px 0",
                alignItems: "center",
              }}
            >
              <span className="wb-mono" style={chipStyle("ink")}>
                {i.platform}
              </span>
              <span
                className="wb-mono"
                style={{ fontSize: 11, color: "var(--wb-color-aged-ink)" }}
              >
                {i.platformUserId}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <span
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            fontSize: 12,
            color: "var(--wb-color-hash-gray)",
          }}
        >
          {footnote ?? "no identities"}
        </span>
      )}
    </div>
  );
}
