"use client";

/**
 * SignupCTA — Phase 4C wire-up.
 *
 * The primary CTA (``signup-primary``) links at ``/api/auth/slack/start``,
 * the canonical Slack-OAuth start endpoint (Phase 1B.C). Slack returns to
 * ``/api/auth/slack/callback`` which runs the install orchestrator and
 * lands the visitor in ``/onboarding/welcome`` with the install cascade
 * playing live.
 *
 * Below the primary CTA, an inline email magic-link form POSTs to
 * ``/api/auth/email/request`` (Phase 1B.D). The form surfaces an honest
 * status panel — success ("check your inbox"), error (invalid email,
 * auth not configured, network failure), or pending. In dev mode
 * (``WORMBASE_AUTH_DEV_MODE=1``) the API returns the rendered link and
 * the form exposes a copy-link affordance so SMTP-less environments
 * can still complete the round-trip.
 *
 * The secondary CTA (``signup-secondary``) keeps the existing
 * ``/onboarding`` walk-the-demo affordance for visitors who'd rather
 * skip the magic-link round-trip. Both signup paths converge on the
 * same dashboard surface — wires aren't duplicated downstream.
 */
import Link from "next/link";
import { Button } from "@wormbase/design";
import { useState, type CSSProperties, type FormEvent } from "react";

type FormStatus =
  | { kind: "idle" }
  | { kind: "pending" }
  | { kind: "success"; magicLink?: string }
  | { kind: "error"; message: string };

export function SignupCTA() {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<FormStatus>({ kind: "idle" });

  async function handleSubmit(ev: FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    const trimmed = email.trim().toLowerCase();
    if (!trimmed) return; // honest no-op on blank input.
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
        const message = friendlyErrorMessage(res.status, json);
        setStatus({ kind: "error", message });
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
    <section
      data-testid="signup-section"
      aria-labelledby="signup-headline"
      style={sectionStyle}
    >
      <div style={innerStyle}>
        <p className="wb-mono" style={eyebrowStyle}>
          plate vi · sign up · 4C
        </p>
        <h2 id="signup-headline" style={headlineStyle}>
          Install on Monday. Read receipts on Friday.
        </h2>
        <p style={subheadStyle}>
          Connect a Slack workspace and the worm starts a fresh tenant. Or
          send a magic link to a demo workspace to evaluate WormBase against
          a seeded carousel without any provisioning of your own.
        </p>

        <div style={ctasStyle}>
          {/* Primary: Slack-OAuth start. The Button component renders an
              <a> when href is provided so keyboard + screen-reader users
              get the right control semantics. */}
          <Link
            href="/api/auth/slack/start"
            data-testid="signup-primary"
            style={primaryLinkStyle}
            // ``rel="external"`` so prefetching doesn't fire the OAuth
            // start handler before the visitor clicks.
            rel="external"
          >
            <Button size="lg" tabIndex={-1}>
              Connect to Slack
            </Button>
          </Link>
          <Link
            href="/onboarding"
            data-testid="signup-secondary"
            style={secondaryLinkStyle}
          >
            <span style={secondaryLabelStyle}>Walk the demo workspace →</span>
            <span className="wb-mono" style={secondaryMetaStyle}>
              /onboarding · live today
            </span>
          </Link>
        </div>

        {/* Email magic-link form — observer-only access to a demo tenant. */}
        <form
          data-testid="signup-email-form"
          onSubmit={handleSubmit}
          style={formStyle}
          aria-describedby="signup-email-help"
          noValidate
        >
          <label
            htmlFor="signup-email-input"
            className="wb-mono"
            style={labelStyle}
          >
            or send a magic link
          </label>
          <div style={formRowStyle}>
            <input
              id="signup-email-input"
              data-testid="signup-email-input"
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
              data-testid="signup-email-submit"
              disabled={status.kind === "pending"}
            >
              {status.kind === "pending" ? "Sending…" : "Send magic link"}
            </Button>
          </div>
          <p id="signup-email-help" className="wb-mono" style={formHelpStyle}>
            magic-link evaluators land on a seeded demo tenant
            (read-only). slack signup creates a fresh tenant for your
            workspace.
          </p>
          {status.kind === "success" ? (
            <div data-testid="signup-email-success" style={successStyle}>
              <p style={successLineStyle}>
                magic link sent — check your inbox to continue. links
                expire in 15 minutes.
              </p>
              {status.magicLink ? (
                <p
                  className="wb-mono"
                  data-testid="signup-email-success-link"
                  style={successDevLinkStyle}
                >
                  dev mode: <a href={status.magicLink}>{status.magicLink}</a>
                </p>
              ) : null}
            </div>
          ) : null}
          {status.kind === "error" ? (
            <p
              data-testid="signup-email-error"
              className="wb-mono"
              style={errorStyle}
              role="alert"
            >
              {status.message}
            </p>
          ) : null}
        </form>
      </div>
    </section>
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

const sectionStyle: CSSProperties = {
  width: "100%",
  padding: "96px 24px",
  background: "var(--wb-color-paper)",
  borderTop: "1px solid var(--wb-color-rule-line)",
};

const innerStyle: CSSProperties = {
  maxWidth: 880,
  margin: "0 auto",
  display: "flex",
  flexDirection: "column",
  gap: 24,
  alignItems: "center",
  textAlign: "center",
};

const eyebrowStyle: CSSProperties = {
  margin: 0,
  fontSize: 11,
  letterSpacing: "0.24em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
};

const headlineStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: "clamp(28px, 3.4vw, 40px)",
  fontWeight: 600,
  color: "var(--wb-color-aged-ink)",
  letterSpacing: "-0.012em",
  lineHeight: 1.15,
};

const subheadStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: "var(--wb-text-md)",
  color: "var(--wb-color-aged-ink-soft)",
  lineHeight: 1.55,
  maxWidth: 640,
};

const ctasStyle: CSSProperties = {
  display: "flex",
  gap: 16,
  alignItems: "center",
  flexWrap: "wrap",
  justifyContent: "center",
  marginTop: 12,
};

const primaryLinkStyle: CSSProperties = {
  textDecoration: "none",
  color: "inherit",
};

const secondaryLinkStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  alignItems: "flex-start",
  gap: 2,
  textDecoration: "none",
  color: "var(--wb-color-aged-ink)",
  borderBottom: "1px solid var(--wb-color-aged-ink)",
  paddingBottom: 4,
};

const secondaryLabelStyle: CSSProperties = {
  fontFamily: "var(--wb-font-serif)",
  fontSize: "var(--wb-text-md)",
};

const secondaryMetaStyle: CSSProperties = {
  fontSize: 10,
  letterSpacing: "0.16em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
};

const formStyle: CSSProperties = {
  marginTop: 24,
  width: "100%",
  maxWidth: 540,
  display: "flex",
  flexDirection: "column",
  gap: 8,
  textAlign: "left",
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

const formHelpStyle: CSSProperties = {
  margin: 0,
  fontSize: 10,
  letterSpacing: "0.04em",
  color: "var(--wb-color-hash-gray)",
};

const successStyle: CSSProperties = {
  marginTop: 8,
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
  margin: "8px 0 0",
  fontSize: 11,
  letterSpacing: "0.04em",
  color: "var(--wb-color-sepia-warning-deep)",
};
