"use client";
/**
 * InviteModal — admin invites a new Person.
 *
 * The admin must provide a real platform identity (Slack/Discord/Teams
 * handle) for the invitee. There is no "Send SSO link" no-op toggle and
 * no synthesized ``pending_email`` platform shim — both of which were
 * deleted in the production-onboarding pass.
 *
 * Workflow:
 *   1. Admin opens modal, types name + email + position + platform +
 *      platform_user_id. Platform + platform_user_id are required.
 *   2. POST /api/people with the canonical body. The server invokes
 *      worm-core ``POST /api/v1/people`` (full PEVR cycle).
 *   3. On success, modal closes and the page refreshes.
 *
 * If the admin doesn't have the invitee's platform handle yet, the modal
 * surfaces an explanation: ask them for it, or wait for the worm to
 * auto-discover them when they post in a channel. There is no shim.
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

export function InviteModal() {
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
    if (!platform) {
      setError("platform is required");
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
      const body: Record<string, unknown> = {
        name: trimmedName,
        platform,
        platform_user_id: trimmedPlatformUserId,
        proposed_by: "admin_invite",
      };
      if (trimmedEmail) body.email = trimmedEmail;
      if (trimmedPosition) body.position = trimmedPosition;

      const res = await fetch("/api/people", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
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
        data-testid="invite-open"
        variant="primary"
        size="sm"
        onClick={() => setOpen(true)}
      >
        Invite person
      </Button>
      {open ? (
        <div
          data-testid="invite-modal"
          role="dialog"
          aria-label="Invite person"
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
            data-testid="invite-scrim"
            aria-label="Close invite modal"
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
            data-testid="invite-form"
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
                People · Admin invite
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
                data-testid="invite-help"
                style={{
                  margin: 0,
                  fontFamily: "var(--wb-font-serif)",
                  fontSize: 13,
                  fontStyle: "italic",
                  color: "var(--wb-color-hash-gray)",
                }}
              >
                The invitee's platform handle (Slack U-id, Discord
                username#discriminator, etc.) is required. If you don't have
                it yet, ask them to share it or wait — the worm
                auto-discovers chatters in connected channels and proposes
                them on /people.
              </p>
            </header>
            <Input
              label="Name"
              data-testid="invite-name"
              value={name}
              onChange={(e) => setName(e.currentTarget.value)}
              placeholder="Carol Reyes"
            />
            <Input
              label="Email"
              data-testid="invite-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.currentTarget.value)}
              placeholder="carol@x.co"
              helperText="optional — used for audit attribution and merging proposals"
            />
            <Input
              label="Position"
              data-testid="invite-position"
              value={position}
              onChange={(e) => setPosition(e.currentTarget.value)}
              placeholder="CFO"
              helperText="optional"
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
                data-testid="invite-platform"
                options={PLATFORM_OPTIONS}
                value={platform}
                onChange={(e) => setPlatform(e.currentTarget.value)}
                helperText="required"
              />
              <Input
                label="Platform user id"
                data-testid="invite-platform-user-id"
                value={platformUserId}
                onChange={(e) => setPlatformUserId(e.currentTarget.value)}
                placeholder="U12345 / discord#1234 / …"
                helperText="required"
              />
            </div>
            {error ? (
              <div
                data-testid="invite-error"
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
                data-testid="invite-cancel"
              >
                Cancel
              </Button>
              <Button
                type="submit"
                variant="primary"
                size="sm"
                disabled={busy}
                data-testid="invite-submit"
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
