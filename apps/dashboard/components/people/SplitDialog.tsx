"use client";
/**
 * SplitDialog — admin splits a Person whose identities were misattributed.
 *
 * Triggered from PersonDetailDrawer's "Split this Person..." button. Shows
 * the source's identities with checkboxes; admin picks the subset to extract,
 * provides name/email/position for the new Person; on confirm POSTs to
 * `/api/people/[id]/split` which calls worm-core's split endpoint.
 *
 * Three steps:
 *   1. Pick identities to extract (checkbox list of the source's
 *      currently-linked identities).
 *   2. Fill the new Person's metadata (name, email, position).
 *   3. Confirm.
 *
 * A6 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 */
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Input } from "@wormbase/design";
import type { PersonIdentityDetailRow } from "../../lib/ledger-client.types";
import { chipStyle } from "./_styles";

const ADMIN_ACTOR_ID = "dashboard-admin";

export interface SplitDialogProps {
  sourcePersonId: string;
  sourceName: string;
  identities: PersonIdentityDetailRow[];
  open: boolean;
  onClose: () => void;
  adminPersonId?: string;
  onSplit?: (result: {
    source_person_id: string;
    new_person_id: string;
    identities_moved: number;
  }) => void;
}

export function SplitDialog({
  sourcePersonId,
  sourceName,
  identities,
  open,
  onClose,
  adminPersonId = ADMIN_ACTOR_ID,
  onSplit,
}: SplitDialogProps) {
  const router = useRouter();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [position, setPosition] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setSelected(new Set());
      setName("");
      setEmail("");
      setPosition("");
      setError(null);
      setSuccess(null);
    }
  }, [open]);

  const identitiesToMove = useMemo(
    () =>
      identities.filter((i) => selected.has(`${i.platform}|${i.platformUserId}`)),
    [identities, selected],
  );

  function toggle(key: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  async function confirmSplit() {
    if (identitiesToMove.length === 0) {
      setError("pick at least one identity to extract");
      return;
    }
    if (!name.trim()) {
      setError("new Person name is required");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/people/${encodeURIComponent(sourcePersonId)}/split`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            new_person_name: name.trim(),
            new_person_email: email.trim() || null,
            new_person_position: position.trim() || null,
            identities_to_move: identitiesToMove.map((i) => ({
              platform: i.platform,
              platform_user_id: i.platformUserId,
            })),
            split_by: adminPersonId,
          }),
        },
      );
      if (!res.ok) {
        const j = (await res.json().catch(() => ({}))) as { message?: string };
        throw new Error(j.message ?? `split failed (${res.status})`);
      }
      const result = (await res.json()) as {
        source_person_id: string;
        new_person_id: string;
        identities_moved: number;
      };
      setSuccess(
        `Split complete: ${result.identities_moved} identities moved to ${name.trim()}.`,
      );
      onSplit?.(result);
      router.refresh();
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
      data-testid="split-dialog"
      role="dialog"
      aria-label="Split person"
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
        data-testid="split-scrim"
        aria-label="Close split dialog"
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
          width: "min(620px, 94vw)",
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
            People · Split identities
          </span>
          <h2
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 24,
              fontWeight: 500,
            }}
          >
            Split {sourceName}
          </h2>
          <p
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 13,
              color: "var(--wb-color-aged-ink)",
            }}
          >
            Pick the identities that belong to a different human, and give
            the new Person a name. The source Person keeps everything else.
          </p>
        </header>

        <section
          data-testid="split-step-pick"
          style={{ display: "flex", flexDirection: "column", gap: 6 }}
        >
          <SectionTitle>1 · Identities to extract</SectionTitle>
          {identities.length === 0 ? (
            <span
              data-testid="split-no-identities"
              style={{
                fontFamily: "var(--wb-font-serif)",
                fontStyle: "italic",
                color: "var(--wb-color-hash-gray)",
                fontSize: 13,
              }}
            >
              this Person has no identities to split
            </span>
          ) : (
            <ul
              data-testid="split-identities-list"
              style={{
                listStyle: "none",
                padding: 0,
                margin: 0,
                border: "1px solid var(--wb-color-paper-edge)",
              }}
            >
              {identities.map((i) => {
                const key = `${i.platform}|${i.platformUserId}`;
                const checked = selected.has(key);
                return (
                  <li
                    key={key}
                    data-testid={`split-identity-${i.platform}-${i.platformUserId}`}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 10,
                      padding: "6px 12px",
                      borderBottom: "1px dashed var(--wb-color-paper-edge)",
                    }}
                  >
                    <input
                      type="checkbox"
                      data-testid={`split-checkbox-${i.platform}-${i.platformUserId}`}
                      checked={checked}
                      onChange={() => toggle(key)}
                    />
                    <span className="wb-mono" style={chipStyle("ink")}>
                      {i.platform}
                    </span>
                    <span
                      className="wb-mono"
                      style={{
                        fontSize: 12,
                        color: "var(--wb-color-aged-ink)",
                      }}
                    >
                      {i.platformUserId}
                    </span>
                    {i.displayName ? (
                      <span
                        style={{
                          fontFamily: "var(--wb-font-serif)",
                          fontStyle: "italic",
                          fontSize: 12,
                          color: "var(--wb-color-hash-gray)",
                          marginLeft: "auto",
                        }}
                      >
                        {i.displayName}
                      </span>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <section
          data-testid="split-step-meta"
          style={{ display: "flex", flexDirection: "column", gap: 8 }}
        >
          <SectionTitle>2 · New Person</SectionTitle>
          <Input
            label="Name (required)"
            data-testid="split-name"
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
            placeholder="Bob Martin"
          />
          <Input
            label="Email"
            data-testid="split-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.currentTarget.value)}
            placeholder="bob@x.co"
          />
          <Input
            label="Position"
            data-testid="split-position"
            value={position}
            onChange={(e) => setPosition(e.currentTarget.value)}
            placeholder="Engineer"
          />
        </section>

        <section
          data-testid="split-step-confirm"
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
            {identitiesToMove.length === 0
              ? "pick at least one identity above"
              : `${identitiesToMove.length} identit${identitiesToMove.length === 1 ? "y" : "ies"} will be detached from ${sourceName} and attached to the new Person.`}
          </div>
          {error ? (
            <div
              data-testid="split-error"
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
              data-testid="split-success"
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
              data-testid="split-cancel"
              onClick={onClose}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="primary"
              size="sm"
              data-testid="split-confirm"
              onClick={confirmSplit}
              disabled={busy || identitiesToMove.length === 0 || !name.trim()}
            >
              {busy ? "Splitting…" : "Split into new Person"}
            </Button>
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
