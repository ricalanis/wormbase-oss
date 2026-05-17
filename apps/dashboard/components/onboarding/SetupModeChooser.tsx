"use client";
/**
 * SetupModeChooser — wizard-vs-bot fork UI (Block G4 / PRD §17).
 *
 * Two cards:
 *   - Wizard (always available): green pill, primary; routes to
 *     /onboarding/tier2 after persisting the choice via the API.
 *   - Bot (gated on connectedPlatform != null): amber pill, secondary;
 *     disabled when no chat platform is connected, with a back link.
 */
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

export function SetupModeChooser({
  connectedPlatform,
}: {
  connectedPlatform: string | null;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function pick(mode: "wizard" | "bot") {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/onboarding/setup-mode", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ mode }),
      });
      const text = await res.text();
      let body: { redirect?: string; error?: string };
      try {
        body = JSON.parse(text);
      } catch {
        throw new Error(`server returned non-JSON: ${text.slice(0, 200)}`);
      }
      if (!res.ok) {
        throw new Error(body.error || `setup-mode failed (${res.status})`);
      }
      router.push(
        body.redirect ?? (mode === "wizard" ? "/onboarding/tier2" : "/"),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <section
      data-testid="setup-mode-chooser"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 16,
        border: "1px solid var(--wb-color-paper-edge)",
        padding: 22,
        background: "var(--wb-color-paper)",
      }}
    >
      <header style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          setup mode
        </span>
        <h2
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 24,
            fontWeight: 500,
          }}
        >
          How should the worm finish setup?
        </h2>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-aged-ink-soft)",
            fontSize: 14,
            lineHeight: 1.55,
            maxWidth: 640,
          }}
        >
          Pick one. Both paths produce the same ledger output — domain pack,
          classifications, admin invites, KPI tree. You can switch later
          from /settings.
        </p>
      </header>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))",
          gap: 12,
        }}
      >
        <ModeCard
          testId="setup-mode-wizard"
          title="Dashboard wizard"
          blurb="Step through the dashboard's setup forms. Domain pack, classifications, admin invites, KPI tree. Fastest path; ~90 seconds."
          pillLabel="recommended"
          pillColor="var(--wb-color-botanical-green-deep)"
          pillBorder="var(--wb-color-botanical-green)"
          disabled={busy}
          onClick={() => pick("wizard")}
        />
        <ModeCard
          testId="setup-mode-bot"
          title="Worm in chat"
          blurb={
            connectedPlatform
              ? `The worm DMs you in ${connectedPlatform} and walks through setup conversationally. Same outcomes, different surface.`
              : "The worm DMs you in your chat platform and walks through setup. Connect a chat platform first to enable this path."
          }
          pillLabel={connectedPlatform ? "conversational" : "needs chat platform"}
          pillColor={
            connectedPlatform
              ? "var(--wb-color-sepia-warning-deep)"
              : "var(--wb-color-hash-gray)"
          }
          pillBorder={
            connectedPlatform
              ? "var(--wb-color-sepia-warning-deep)"
              : "var(--wb-color-paper-edge)"
          }
          disabled={busy || !connectedPlatform}
          onClick={() => pick("bot")}
        />
      </div>

      {!connectedPlatform ? (
        <p
          data-testid="setup-mode-bot-blocker"
          className="wb-mono"
          style={{
            fontSize: 11,
            color: "var(--wb-color-hash-gray)",
            margin: 0,
          }}
        >
          Bot mode needs a chat platform.{" "}
          <Link
            href="/onboarding/whats-next"
            data-testid="setup-mode-back-to-whats-next"
            style={{ color: "var(--wb-color-aged-ink)" }}
          >
            ← back
          </Link>
        </p>
      ) : null}

      {error ? (
        <div
          data-testid="setup-mode-error"
          className="wb-mono"
          style={{
            fontSize: 11,
            color: "var(--wb-color-sepia-warning-deep)",
            border: "1px solid var(--wb-color-sepia-warning-deep)",
            background: "var(--wb-color-sepia-warning-soft)",
            padding: "8px 12px",
          }}
        >
          {error}
        </div>
      ) : null}
    </section>
  );
}

function ModeCard({
  testId,
  title,
  blurb,
  pillLabel,
  pillColor,
  pillBorder,
  disabled,
  onClick,
}: {
  testId: string;
  title: string;
  blurb: string;
  pillLabel: string;
  pillColor: string;
  pillBorder: string;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      data-testid={testId}
      data-disabled={disabled ? "true" : "false"}
      aria-disabled={disabled}
      disabled={disabled}
      onClick={onClick}
      style={{
        textAlign: "left",
        display: "flex",
        flexDirection: "column",
        gap: 8,
        border: "1px solid var(--wb-color-paper-edge)",
        background: disabled
          ? "var(--wb-color-paper-deep)"
          : "var(--wb-color-paper)",
        padding: 18,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.55 : 1,
        borderRadius: 0,
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 8,
        }}
      >
        <span
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontSize: 18,
            fontWeight: 500,
          }}
        >
          {title}
        </span>
        <span
          className="wb-mono"
          style={{
            fontSize: 9,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: pillColor,
            border: `1px solid ${pillBorder}`,
            padding: "1px 6px",
            borderRadius: 0,
            whiteSpace: "nowrap",
          }}
        >
          {pillLabel}
        </span>
      </header>
      <span
        style={{
          fontFamily: "var(--wb-font-serif)",
          fontSize: 13,
          color: "var(--wb-color-aged-ink)",
          lineHeight: 1.5,
        }}
      >
        {blurb}
      </span>
    </button>
  );
}
