"use client";

/**
 * MagicLinkForm — Phase 4C visitor-facing magic-link form.
 *
 * Lives at /login (alongside the tenant picker) and on the landing
 * page (via SignupCTA). POSTs the entered email to
 * ``/api/auth/email/request`` and surfaces success/error inline. In
 * dev mode (``WORMBASE_AUTH_DEV_MODE=1``) the API returns the
 * rendered link and the form exposes a copy-link affordance so
 * SMTP-less environments can still complete the round-trip.
 *
 * Re-used between SignupCTA's inline form and the /login page's
 * "or send a magic link" surface so behaviour stays consistent.
 */
import { Button } from "@wormbase/design";
import { useState, type CSSProperties, type FormEvent } from "react";

type Status =
  | { kind: "idle" }
  | { kind: "pending" }
  | { kind: "success"; magicLink?: string }
  | { kind: "error"; message: string };

export interface MagicLinkFormProps {
  /** Test-id prefix so the same component can be reused on /login + landing. */
  testidPrefix: string;
  /** Optional secondary copy below the input row. */
  helpText?: string;
}

export function MagicLinkForm({ testidPrefix, helpText }: MagicLinkFormProps) {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  async function handleSubmit(ev: FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    const trimmed = email.trim().toLowerCase();
    if (!trimmed) return;
    setStatus({ kind: "pending" });
    try {
      const res = await fetch("/api/auth/email/request", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: trimmed }),
      });
      if (!res.ok) {
        const json = (await res.json().catch(() => ({}))) as {
          error?: string;
          message?: string;
        };
        setStatus({
          kind: "error",
          message: friendlyErrorMessage(res.status, json),
        });
        return;
      }
      const json = (await res.json()) as { magic_link?: string };
      setStatus({ kind: "success", magicLink: json.magic_link });
    } catch (err) {
      setStatus({
        kind: "error",
        message: `network error sending magic link: ${(err as Error).message}`,
      });
    }
  }

  return (
    <form
      data-testid={`${testidPrefix}-form`}
      onSubmit={handleSubmit}
      style={formStyle}
      noValidate
    >
      <label
        htmlFor={`${testidPrefix}-input`}
        className="wb-mono"
        style={labelStyle}
      >
        send a magic link
      </label>
      <div style={formRowStyle}>
        <input
          id={`${testidPrefix}-input`}
          data-testid={`${testidPrefix}-input`}
          type="email"
          required
          autoComplete="email"
          placeholder="you@company.com"
          value={email}
          onChange={(ev) => setEmail(ev.target.value)}
          disabled={status.kind === "pending"}
          style={inputStyle}
        />
        <Button
          type="submit"
          size="md"
          data-testid={`${testidPrefix}-submit`}
          disabled={status.kind === "pending"}
        >
          {status.kind === "pending" ? "Sending…" : "Send magic link"}
        </Button>
      </div>
      {helpText ? (
        <p className="wb-mono" style={helpStyle}>
          {helpText}
        </p>
      ) : null}
      {status.kind === "success" ? (
        <div data-testid={`${testidPrefix}-success`} style={successStyle}>
          <p style={successLineStyle}>
            magic link sent — check your inbox to continue. links expire in
            15 minutes.
          </p>
          {status.magicLink ? (
            <p
              className="wb-mono"
              data-testid={`${testidPrefix}-success-link`}
              style={successDevLinkStyle}
            >
              dev mode: <a href={status.magicLink}>{status.magicLink}</a>
            </p>
          ) : null}
        </div>
      ) : null}
      {status.kind === "error" ? (
        <p
          data-testid={`${testidPrefix}-error`}
          className="wb-mono"
          style={errorStyle}
          role="alert"
        >
          {status.message}
        </p>
      ) : null}
    </form>
  );
}

function friendlyErrorMessage(
  status: number,
  body: { error?: string; message?: string },
): string {
  if (body.error === "invalid_email") {
    return "that email address didn't parse — try again.";
  }
  if (body.error === "auth_secret_unset") {
    return "magic-link signup is not configured on this deployment yet. install via Slack instead, or contact the operator.";
  }
  if (body.error === "no_demo_tenants") {
    return "no demo tenants are seeded on this deployment yet — install via Slack to start a fresh tenant.";
  }
  return body.message ?? `unexpected status ${status} — please try again.`;
}

const formStyle: CSSProperties = {
  width: "100%",
  display: "flex",
  flexDirection: "column",
  gap: 8,
};

const labelStyle: CSSProperties = {
  fontSize: 10,
  letterSpacing: "0.18em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
};

const formRowStyle: CSSProperties = {
  display: "flex",
  gap: 8,
  alignItems: "stretch",
};

const inputStyle: CSSProperties = {
  flex: 1,
  font: "inherit",
  padding: "12px 14px",
  border: "1px solid var(--wb-color-aged-ink)",
  background: "var(--wb-color-paper)",
  color: "var(--wb-color-aged-ink)",
  borderRadius: 0,
  fontFamily: "var(--wb-font-serif)",
};

const helpStyle: CSSProperties = {
  margin: 0,
  fontSize: 10,
  letterSpacing: "0.04em",
  color: "var(--wb-color-hash-gray)",
};

const successStyle: CSSProperties = {
  marginTop: 4,
  padding: "12px 14px",
  border: "1px dashed var(--wb-color-rule-line)",
  background: "var(--wb-color-botanical-green-soft)",
  color: "var(--wb-color-aged-ink)",
};

const successLineStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: 14,
};

const successDevLinkStyle: CSSProperties = {
  margin: "8px 0 0",
  fontSize: 11,
  wordBreak: "break-all",
};

const errorStyle: CSSProperties = {
  margin: "4px 0 0",
  fontSize: 11,
  letterSpacing: "0.04em",
  color: "var(--wb-color-sepia-warning-deep)",
};
