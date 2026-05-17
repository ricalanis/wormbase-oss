"use client";
/**
 * IdentityMergePanel — admin merges two Persons that turn out to be the same
 * human across platforms.
 *
 * W2.A6 of `docs/superpowers/plans/2026-04-28-production-hardening.md`.
 *
 * Surface contract:
 *   1. Two pickers — keeper + mergee — drawn from the active roster.
 *   2. A confirmation modal with explicit "this is irreversible" copy
 *      MUST be cleared before the merge fires. Per the brief's quality
 *      bar; see `feedback_no_demo_seams` in user memory.
 *   3. POST to `/api/people/merge` (existing route) which calls
 *      worm-core's `POST /api/v1/people/merge` — that endpoint writes a
 *      sequence of independent `emit_identity_unlinked` /
 *      `emit_identity_linked` / `emit_person_archived` PEVR cycles,
 *      i.e. the full audit trail per the architecture spec.
 *
 * Why a panel and not a dialog: the existing `MergeDialog` is launched
 * from `PersonDetailDrawer` (the keeper context is implicit). This
 * panel surfaces merge as a top-level admin action on /people for the
 * case where the admin already knows both Person ids — typical after
 * the auto-discovery loop seeded duplicates in pending proposals.
 */
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@wormbase/design";
import type { PersonRow as PersonRowModel } from "../../lib/ledger-client.types";
import { chipStyle } from "./_styles";

export interface IdentityMergePanelProps {
  persons: PersonRowModel[];
  /**
   * Current admin Person id — threaded through `merged_by` on the wire
   * so the resulting `emit_identity_linked` / `emit_identity_unlinked` /
   * `emit_person_archived` ledger entries carry real attribution per
   * CLAUDE.md §9 (no self-grant placeholders). When null the panel still
   * renders for callers that haven't been wired through, falling back
   * to the keeper id as in the W2.A6 default.
   */
  adminPersonId?: string | null;
  /**
   * Whether the current viewer is an admin or installer. When false the
   * Review / Merge affordance is hidden behind a role-gated explanation
   * panel per CLAUDE.md §5 (identity merge is admin-only).
   */
  isAdmin?: boolean;
}

export function IdentityMergePanel({
  persons,
  adminPersonId = null,
  isAdmin = true,
}: IdentityMergePanelProps) {
  const router = useRouter();
  const [keeperId, setKeeperId] = useState<string>("");
  const [mergeeId, setMergeeId] = useState<string>("");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const keeper = useMemo(
    () => persons.find((p) => p.personId === keeperId) ?? null,
    [persons, keeperId],
  );
  const mergee = useMemo(
    () => persons.find((p) => p.personId === mergeeId) ?? null,
    [persons, mergeeId],
  );

  const canOpenConfirm =
    keeper !== null && mergee !== null && keeper.personId !== mergee.personId;

  function openConfirm() {
    if (!canOpenConfirm) {
      setError(
        keeperId === mergeeId
          ? "keeper and mergee must be different Persons"
          : "pick a keeper and a mergee first",
      );
      return;
    }
    setError(null);
    setSuccess(null);
    setConfirmOpen(true);
  }

  async function runMerge() {
    if (!keeper || !mergee) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/people/merge", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          keeper_id: keeper.personId,
          mergee_id: mergee.personId,
          // D2: thread the resolved admin Person id through `merged_by`
          // so the ledger audit trail carries real attribution per
          // CLAUDE.md §9. Falls back to the keeper id only when the
          // panel was rendered without an `adminPersonId` (legacy path
          // / pre-D2 callers); production /people threads it through.
          merged_by: adminPersonId ?? keeper.personId,
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
        `Merge complete · ${result.identities_moved} identities moved to ${
          keeper.displayName
        }. Mergee archived.`,
      );
      setConfirmOpen(false);
      setKeeperId("");
      setMergeeId("");
      router.refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (persons.length < 2) {
    return (
      <section
        data-testid="identity-merge-panel"
        style={{
          border: "1px solid var(--wb-color-paper-edge)",
          padding: "16px 20px",
          display: "flex",
          flexDirection: "column",
          gap: 8,
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
            Identity merges
          </span>
          <h2
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 22,
              fontWeight: 500,
            }}
          >
            Merge multi-platform identities
          </h2>
        </header>
        <p
          data-testid="identity-merge-empty"
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            fontSize: 13,
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Need at least two confirmed Persons before a merge becomes possible.
          The auto-discovery loop seeds candidates as it finds chatter on
          additional platforms.
        </p>
      </section>
    );
  }

  if (!isAdmin) {
    // D2 / CLAUDE.md §5 — identity merge is admin-only. Render a quiet,
    // visible explanation panel rather than hiding the surface entirely;
    // members and observers still see that the affordance exists, just
    // not the trigger.
    return (
      <section
        data-testid="identity-merge-panel"
        style={{
          border: "1px solid var(--wb-color-paper-edge)",
          padding: "16px 20px",
          display: "flex",
          flexDirection: "column",
          gap: 8,
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
            Identity merges · Admin only
          </span>
          <h2
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 22,
              fontWeight: 500,
            }}
          >
            Merge multi-platform identities
          </h2>
        </header>
        <p
          data-testid="identity-merge-role-gated"
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            fontSize: 13,
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Only admins / installers can merge multi-platform identities. Ask
          a tenancy admin to link your Slack U-id to your WhatsApp jid (or
          vice versa) — both actions land an audit trail on the ledger.
        </p>
      </section>
    );
  }

  return (
    <section
      data-testid="identity-merge-panel"
      style={{
        border: "1px solid var(--wb-color-paper-edge)",
        padding: "16px 20px",
        display: "flex",
        flexDirection: "column",
        gap: 12,
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
          Identity merges · Admin only
        </span>
        <h2
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 22,
            fontWeight: 500,
          }}
        >
          Merge multi-platform identities
        </h2>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            fontSize: 13,
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Pick the keeper and the duplicate. All of the duplicate&apos;s
          identities move to the keeper; the duplicate is archived. The
          full audit trail lands as `emit_identity_linked` /
          `emit_identity_unlinked` ledger entries.
        </p>
      </header>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 12,
        }}
      >
        <PersonPicker
          testid="identity-merge-keeper"
          label="Keeper"
          placeholder="pick a Person to keep"
          value={keeperId}
          options={persons.filter((p) => p.personId !== mergeeId)}
          onChange={setKeeperId}
        />
        <PersonPicker
          testid="identity-merge-mergee"
          label="Mergee (will be archived)"
          placeholder="pick a Person to merge in"
          value={mergeeId}
          options={persons.filter((p) => p.personId !== keeperId)}
          onChange={setMergeeId}
        />
      </div>

      {keeper && mergee ? (
        <div
          data-testid="identity-merge-preview"
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 24px 1fr",
            gap: 12,
            border: "1px solid var(--wb-color-paper-edge)",
            padding: 12,
            background: "var(--wb-color-paper-deep)",
          }}
        >
          <PreviewColumn
            testid="identity-merge-preview-mergee"
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
            testid="identity-merge-preview-keeper"
            title="To keeper"
            name={keeper.displayName ?? "(unnamed)"}
            identities={keeper.identities.map((i) => ({
              platform: i.platform,
              platformUserId: i.platformUserId,
            }))}
            footnote="(plus mergee's identities, after merge)"
          />
        </div>
      ) : null}

      {error ? (
        <div
          data-testid="identity-merge-error"
          role="alert"
          className="wb-mono"
          style={{
            fontSize: 12,
            color: "var(--wb-color-sepia-warning-deep)",
            border: "1px solid var(--wb-color-sepia-warning-deep)",
            padding: "6px 10px",
            background: "var(--wb-color-sepia-warning-soft)",
          }}
        >
          {error}
        </div>
      ) : null}
      {success ? (
        <div
          data-testid="identity-merge-success"
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

      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
        <Button
          data-testid="identity-merge-open-confirm"
          variant="primary"
          size="sm"
          onClick={openConfirm}
          disabled={!canOpenConfirm}
        >
          Review merge
        </Button>
      </div>

      {confirmOpen && keeper && mergee ? (
        <ConfirmIrreversibleModal
          keeperName={keeper.displayName ?? keeper.personId.slice(0, 8)}
          mergeeName={mergee.displayName ?? mergee.personId.slice(0, 8)}
          identityCount={mergee.identities.length}
          busy={busy}
          onCancel={() => setConfirmOpen(false)}
          onConfirm={runMerge}
        />
      ) : null}
    </section>
  );
}

interface PersonPickerProps {
  testid: string;
  label: string;
  placeholder: string;
  value: string;
  options: PersonRowModel[];
  onChange: (personId: string) => void;
}

function PersonPicker({
  testid,
  label,
  placeholder,
  value,
  options,
  onChange,
}: PersonPickerProps) {
  return (
    <label
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 4,
        fontFamily: "var(--wb-font-serif)",
        fontSize: 13,
      }}
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
        {label}
      </span>
      <select
        data-testid={testid}
        value={value}
        onChange={(e) => onChange(e.currentTarget.value)}
        style={{
          padding: "6px 8px",
          fontFamily: "var(--wb-font-mono)",
          fontSize: 12,
          border: "1px solid var(--wb-color-aged-ink)",
          background: "var(--wb-color-paper)",
          borderRadius: 0,
        }}
      >
        <option value="">{placeholder}</option>
        {options.map((p) => (
          <option key={p.personId} value={p.personId}>
            {p.displayName ?? "(unnamed)"} · {p.email ?? p.personId.slice(0, 8)}{" "}
            · {p.identities.length} identities
          </option>
        ))}
      </select>
    </label>
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

interface ConfirmIrreversibleModalProps {
  keeperName: string;
  mergeeName: string;
  identityCount: number;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

/**
 * Irreversibility confirmation modal — displays an explicit warning per
 * the W2.A6 quality bar before any merge fires. The "this is irreversible"
 * copy is required, not advisory; the parent will not call worm-core
 * until the user clicks the destructive button here.
 */
function ConfirmIrreversibleModal({
  keeperName,
  mergeeName,
  identityCount,
  busy,
  onCancel,
  onConfirm,
}: ConfirmIrreversibleModalProps) {
  const [acknowledged, setAcknowledged] = useState(false);

  return (
    <div
      data-testid="identity-merge-confirm-modal"
      role="dialog"
      aria-label="Confirm identity merge"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 80,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <button
        data-testid="identity-merge-confirm-scrim"
        aria-label="Close confirm-merge modal"
        onClick={busy ? undefined : onCancel}
        disabled={busy}
        style={{
          position: "absolute",
          inset: 0,
          background: "rgba(20, 16, 8, 0.42)",
          border: "none",
          padding: 0,
          margin: 0,
          cursor: busy ? "not-allowed" : "pointer",
        }}
      />
      <div
        style={{
          position: "relative",
          width: "min(540px, 92vw)",
          background: "var(--wb-color-paper)",
          border: "1px solid var(--wb-color-sepia-warning-deep)",
          padding: "22px 24px",
          display: "flex",
          flexDirection: "column",
          gap: 14,
        }}
      >
        <header style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: "var(--wb-color-sepia-warning-deep)",
            }}
          >
            Irreversible action
          </span>
          <h3
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 22,
              fontWeight: 500,
            }}
          >
            Merge {mergeeName} into {keeperName}
          </h3>
        </header>
        <p
          data-testid="identity-merge-irreversible-copy"
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 14,
            lineHeight: 1.5,
            color: "var(--wb-color-aged-ink)",
          }}
        >
          This is irreversible. {identityCount} identit
          {identityCount === 1 ? "y" : "ies"} will move from{" "}
          <strong>{mergeeName}</strong> onto <strong>{keeperName}</strong>, and{" "}
          <strong>{mergeeName}</strong> will be archived. The action lands a
          full audit trail (`emit_identity_linked`,
          `emit_identity_unlinked`, `emit_person_archived`) on the ledger and
          cannot be undone in-place — only by issuing a compensating split.
        </p>
        <label
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 13,
          }}
        >
          <input
            type="checkbox"
            data-testid="identity-merge-acknowledge"
            checked={acknowledged}
            onChange={(e) => setAcknowledged(e.currentTarget.checked)}
            disabled={busy}
          />
          I understand this is irreversible.
        </label>
        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            gap: 10,
          }}
        >
          <Button
            type="button"
            variant="ghost"
            size="sm"
            data-testid="identity-merge-confirm-cancel"
            onClick={onCancel}
            disabled={busy}
          >
            Cancel
          </Button>
          <button
            type="button"
            data-testid="identity-merge-confirm-run"
            onClick={onConfirm}
            disabled={busy || !acknowledged}
            style={{
              padding: "8px 16px",
              fontFamily: "var(--wb-font-mono)",
              fontSize: 12,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              color: "var(--wb-color-paper)",
              background:
                busy || !acknowledged
                  ? "var(--wb-color-hash-gray)"
                  : "var(--wb-color-sepia-warning-deep)",
              border: "1px solid var(--wb-color-aged-ink)",
              cursor: busy || !acknowledged ? "not-allowed" : "pointer",
              borderRadius: 0,
            }}
          >
            {busy ? "Merging…" : "Merge & archive mergee"}
          </button>
        </div>
      </div>
    </div>
  );
}
