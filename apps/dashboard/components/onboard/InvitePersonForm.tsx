/**
 * Tier 2 co-admin invite form — Onboarding Sub-wave C (2026-05-30).
 *
 * Client component renders a small form with email + platform_id +
 * role_intent fields. Submits via the ``invitePersonAction`` server
 * action, which threads the current admin Person UUID through
 * ``getCurrentPerson`` and emits a ``person_invited`` PEVR cycle.
 *
 * At least one of email / platform_id must be supplied; the action
 * (and the underlying worm-core handler) enforces this with HTTP
 * 400. The component surfaces the wire error honestly.
 */
"use client";

import { useCallback, useState } from "react";

import { invitePersonAction } from "../../app/(app)/onboard/person/actions";

interface InviteReceipt {
  inviteeEmail: string | null;
  inviteePlatformId: string | null;
  roleIntent: string;
}

interface InviteError {
  message: string;
}

const ROLE_OPTIONS: readonly { value: string; label: string }[] = [
  { value: "member", label: "Member" },
  { value: "admin", label: "Admin" },
  { value: "observer", label: "Observer" },
];

export function InvitePersonForm(): React.JSX.Element {
  const [email, setEmail] = useState("");
  const [platformId, setPlatformId] = useState("");
  const [roleIntent, setRoleIntent] = useState("member");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [receipt, setReceipt] = useState<InviteReceipt | null>(null);
  const [error, setError] = useState<InviteError | null>(null);

  const handleSubmit = useCallback(
    async (e: React.FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      setBusy(true);
      setError(null);
      setReceipt(null);
      try {
        const result = await invitePersonAction({
          inviteeEmail: email,
          inviteePlatformId: platformId,
          roleIntent,
          notes,
        });
        if (result.ok) {
          setReceipt({
            inviteeEmail: result.inviteeEmail ?? null,
            inviteePlatformId: result.inviteePlatformId ?? null,
            roleIntent: result.roleIntent ?? "member",
          });
          // Reset form for next invite.
          setEmail("");
          setPlatformId("");
          setNotes("");
        } else {
          setError({ message: result.error ?? "unknown error" });
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setError({ message: msg });
      } finally {
        setBusy(false);
      }
    },
    [email, platformId, roleIntent, notes],
  );

  return (
    <form
      data-testid="onboard-person-invite-form"
      onSubmit={handleSubmit}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 10,
        border: "1px solid var(--wb-color-paper-edge)",
        background: "var(--wb-color-paper)",
        padding: 14,
        maxWidth: 520,
      }}
    >
      <header style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          invite co-admin
        </span>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
            fontSize: 12,
          }}
        >
          Supply at least one of email or platform identity. Acceptance
          fires the production person_proposed → person_confirmed flow.
        </p>
      </header>
      <label
        style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12 }}
      >
        <span className="wb-mono" style={{ fontSize: 11 }}>
          Email
        </span>
        <input
          data-testid="onboard-person-invite-email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="alice@example.com"
          maxLength={320}
          style={{
            padding: "6px 8px",
            fontFamily: "var(--wb-font-mono)",
            fontSize: 12,
            border: "1px solid var(--wb-color-paper-edge)",
          }}
        />
      </label>
      <label
        style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12 }}
      >
        <span className="wb-mono" style={{ fontSize: 11 }}>
          Platform Identity (optional)
        </span>
        <input
          data-testid="onboard-person-invite-platform-id"
          type="text"
          value={platformId}
          onChange={(e) => setPlatformId(e.target.value)}
          placeholder="slack:U01ALICE"
          maxLength={256}
          style={{
            padding: "6px 8px",
            fontFamily: "var(--wb-font-mono)",
            fontSize: 12,
            border: "1px solid var(--wb-color-paper-edge)",
          }}
        />
      </label>
      <label
        style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12 }}
      >
        <span className="wb-mono" style={{ fontSize: 11 }}>
          Role Intent
        </span>
        <select
          data-testid="onboard-person-invite-role-intent"
          value={roleIntent}
          onChange={(e) => setRoleIntent(e.target.value)}
          style={{
            padding: "6px 8px",
            fontFamily: "var(--wb-font-mono)",
            fontSize: 12,
            border: "1px solid var(--wb-color-paper-edge)",
          }}
        >
          {ROLE_OPTIONS.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </select>
      </label>
      <label
        style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12 }}
      >
        <span className="wb-mono" style={{ fontSize: 11 }}>
          Notes (optional)
        </span>
        <textarea
          data-testid="onboard-person-invite-notes"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Adding for the finance domain"
          rows={2}
          maxLength={2048}
          style={{
            padding: "6px 8px",
            fontFamily: "var(--wb-font-mono)",
            fontSize: 12,
            border: "1px solid var(--wb-color-paper-edge)",
          }}
        />
      </label>
      <button
        type="submit"
        data-testid="onboard-person-invite-submit"
        disabled={busy || (!email.trim() && !platformId.trim())}
        className="wb-mono"
        style={{
          fontSize: 11,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          padding: "8px 14px",
          border: "1px solid var(--wb-color-aged-ink)",
          background:
            busy || (!email.trim() && !platformId.trim())
              ? "var(--wb-color-paper-edge)"
              : "var(--wb-color-aged-ink)",
          color: "var(--wb-color-paper)",
          cursor: busy ? "wait" : "pointer",
          alignSelf: "flex-start",
        }}
      >
        {busy ? "Inviting…" : "Send Invite"}
      </button>
      {receipt && (
        <div
          data-testid="onboard-person-invite-receipt"
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontSize: 12,
            color: "var(--wb-color-aged-ink)",
            background: "var(--wb-color-paper-edge)",
            padding: 6,
          }}
        >
          Invited{" "}
          <code className="wb-mono">
            {receipt.inviteeEmail ?? receipt.inviteePlatformId ?? "—"}
          </code>{" "}
          as {receipt.roleIntent}.
        </div>
      )}
      {error && (
        <div
          data-testid="onboard-person-invite-error"
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
    </form>
  );
}
