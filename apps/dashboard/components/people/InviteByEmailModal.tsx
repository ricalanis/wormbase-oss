"use client";
/**
 * InviteByEmailModal — admin invites a Person via email + position.
 *
 * W2.A6 of `docs/superpowers/plans/2026-04-28-production-hardening.md`.
 *
 * Differs from the legacy `InviteModal`: this modal POSTs to the new
 * `/api/v1/people/invite` route, which threads the current admin's
 * Person id through as `proposed_by` (no placeholder string). Required
 * fields: name, email, position, plus the production-onboarding pair
 * `platform` + `platform_user_id`.
 *
 * On success the modal closes and the page refreshes; failures surface
 * an alert at the bottom of the form.
 */
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Input, Select } from "@wormbase/design";

const PLATFORM_OPTIONS = [
  { value: "slack", label: "Slack" },
  { value: "discord", label: "Discord" },
  { value: "teams", label: "Microsoft Teams" },
  { value: "whatsapp", label: "WhatsApp" },
  { value: "signal", label: "Signal" },
  { value: "matrix", label: "Matrix" },
  { value: "irc", label: "IRC" },
  { value: "google_chat", label: "Google Chat" },
];

export interface InviteByEmailModalProps {
  /** Optional override for the trigger label. */
  triggerLabel?: string;
}

export function InviteByEmailModal({
  triggerLabel = "Invite by email",
}: InviteByEmailModalProps) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [position, setPosition] = useState("");
  const [platform, setPlatform] = useState("slack");
  const [platformUserId, setPlatformUserId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function reset() {
    setName("");
    setEmail("");
    setPosition("");
    setPlatform("slack");
    setPlatformUserId("");
    setError(null);
  }

  function close() {
    setOpen(false);
    reset();
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    const trimmedName = name.trim();
    const trimmedEmail = email.trim();
    const trimmedPosition = position.trim();
    const trimmedPlatformUserId = platformUserId.trim();

    if (!trimmedName) {
      setError("name is required");
      return;
    }
    if (!trimmedEmail) {
      setError("email is required");
      return;
    }
    if (!trimmedPosition) {
      setError("position is required");
      return;
    }
    if (!trimmedPlatformUserId) {
      setError(
        "platform_user_id is required (the invitee's Slack / Discord / Teams handle)",
      );
      return;
    }

    setBusy(true);
    try {
      const res = await fetch("/api/v1/people/invite", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          name: trimmedName,
          email: trimmedEmail,
          position: trimmedPosition,
          platform,
          platform_user_id: trimmedPlatformUserId,
        }),
      });
      if (!res.ok) {
        const j = (await res.json().catch(() => ({}))) as { message?: string };
        throw new Error(j.message ?? `invite failed (${res.status})`);
      }
      close();
      router.refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button
        data-testid="invite-by-email-open"
        variant="primary"
        size="sm"
        onClick={() => setOpen(true)}
      >
        {triggerLabel}
      </Button>
      {open ? (
        <div
          data-testid="invite-by-email-modal"
          role="dialog"
          aria-label="Invite by email"
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 60,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <button
            data-testid="invite-by-email-scrim"
            aria-label="Close invite-by-email modal"
            onClick={close}
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
          <form
            onSubmit={submit}
            data-testid="invite-by-email-form"
            style={{
              position: "relative",
              width: "min(520px, 92vw)",
              background: "var(--wb-color-paper)",
              border: "1px solid var(--wb-color-aged-ink)",
              padding: "24px 28px",
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
                  color: "var(--wb-color-hash-gray)",
                }}
              >
                People · Invite by email
              </span>
              <h2
                style={{
                  margin: 0,
                  fontFamily: "var(--wb-font-serif)",
                  fontSize: 24,
                  fontWeight: 500,
                }}
              >
                Invite a Person
              </h2>
              <p
                data-testid="invite-by-email-help"
                style={{
                  margin: 0,
                  fontFamily: "var(--wb-font-serif)",
                  fontSize: 13,
                  fontStyle: "italic",
                  color: "var(--wb-color-hash-gray)",
                }}
              >
                Email + position seed the audit trail. The current admin's
                Person id is recorded as the proposer — there is no synthesized
                fallback.
              </p>
            </header>
            <Input
              label="Name"
              data-testid="invite-by-email-name"
              value={name}
              onChange={(e) => setName(e.currentTarget.value)}
              placeholder="Carol Reyes"
            />
            <Input
              label="Email"
              data-testid="invite-by-email-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.currentTarget.value)}
              placeholder="carol@x.co"
              helperText="required — used for audit attribution and merging proposals"
            />
            <Input
              label="Position"
              data-testid="invite-by-email-position"
              value={position}
              onChange={(e) => setPosition(e.currentTarget.value)}
              placeholder="CFO"
              helperText="required — drives autoresearch routing"
            />
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: 10,
              }}
            >
              <Select
                label="Platform"
                data-testid="invite-by-email-platform"
                options={PLATFORM_OPTIONS}
                value={platform}
                onChange={(e) => setPlatform(e.currentTarget.value)}
                helperText="required"
              />
              <Input
                label="Platform user id"
                data-testid="invite-by-email-platform-user-id"
                value={platformUserId}
                onChange={(e) => setPlatformUserId(e.currentTarget.value)}
                placeholder="U12345 / discord#1234 / …"
                helperText="required"
              />
            </div>
            {error ? (
              <div
                data-testid="invite-by-email-error"
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
            <div
              style={{
                display: "flex",
                justifyContent: "flex-end",
                gap: 10,
                marginTop: 6,
              }}
            >
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={close}
                data-testid="invite-by-email-cancel"
              >
                Cancel
              </Button>
              <Button
                type="submit"
                variant="primary"
                size="sm"
                disabled={busy}
                data-testid="invite-by-email-submit"
              >
                {busy ? "Inviting…" : "Invite"}
              </Button>
            </div>
          </form>
        </div>
      ) : null}
    </>
  );
}
