"use client";
/**
 * SetupModeSwitcher — admin-only setup-mode switcher (Block G6).
 *
 * Three modes of display:
 *   - completedAt set: read-only, "setup is complete; switching is a no-op".
 *   - currentMode null: hint to complete onboarding via /onboarding/setup-mode/choose.
 *   - currentMode in {wizard, bot}: radio buttons + confirm modal; admin-only.
 */
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

type SetupMode = "wizard" | "bot" | null;

export function SetupModeSwitcher({
  currentMode,
  completedAt,
  connectedPlatform,
  isAdmin,
}: {
  currentMode: SetupMode;
  completedAt: string | null;
  connectedPlatform: string | null;
  isAdmin: boolean;
}) {
  const router = useRouter();
  const [pending, setPending] = useState<SetupMode>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function commit(mode: "wizard" | "bot") {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/onboarding/setup-mode", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ mode }),
      });
      const text = await res.text();
      if (!res.ok) {
        throw new Error(`switch failed (${res.status}): ${text.slice(0, 200)}`);
      }
      // Refresh — the projection update + new redirect-guard decision
      // will re-render this page with the new mode.
      router.refresh();
      setPending(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      data-testid="setup-mode-switcher"
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
          settings · setup mode
        </span>
        <h2
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 22,
            fontWeight: 500,
          }}
        >
          How does the worm finish onboarding?
        </h2>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-aged-ink-soft)",
            fontSize: 13,
            lineHeight: 1.55,
          }}
        >
          Both modes write the same ledger entries. Wizard is form-driven;
          bot is a DM conversation in your chat platform.
        </p>
      </header>

      {completedAt ? (
        <p
          data-testid="setup-mode-completed-state"
          className="wb-mono"
          style={{
            fontSize: 11,
            color: "var(--wb-color-botanical-green-deep)",
            margin: 0,
          }}
        >
          Setup complete (
          {new Date(completedAt).toLocaleString()}). Mode is historical:{" "}
          <strong>{currentMode ?? "unknown"}</strong>. Switching is a no-op.
        </p>
      ) : currentMode === null ? (
        <p
          data-testid="setup-mode-uninitialized-state"
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontSize: 13,
            margin: 0,
            color: "var(--wb-color-aged-ink-soft)",
          }}
        >
          You haven't picked a setup mode yet.{" "}
          <Link
            href="/onboarding/setup-mode/choose"
            data-testid="setup-mode-go-to-choose"
            style={{ color: "var(--wb-color-aged-ink)" }}
          >
            Pick wizard or bot →
          </Link>
        </p>
      ) : (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 10,
          }}
        >
          <p
            data-testid="setup-mode-current"
            className="wb-mono"
            style={{
              fontSize: 11,
              color: "var(--wb-color-aged-ink)",
              margin: 0,
            }}
          >
            current mode: <strong>{currentMode}</strong>
          </p>

          {!isAdmin ? (
            <p
              data-testid="setup-mode-not-admin"
              className="wb-mono"
              style={{
                fontSize: 11,
                color: "var(--wb-color-hash-gray)",
                margin: 0,
              }}
            >
              Only admins can switch setup mode.
            </p>
          ) : (
            <div
              role="radiogroup"
              aria-label="Setup mode"
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 6,
              }}
            >
              <ModeRadio
                testId="setup-mode-radio-wizard"
                label="Dashboard wizard"
                hint="Step through the dashboard's setup forms."
                checked={currentMode === "wizard"}
                disabled={busy || currentMode === "wizard"}
                onClick={() => setPending("wizard")}
              />
              <ModeRadio
                testId="setup-mode-radio-bot"
                label="Worm in chat"
                hint={
                  connectedPlatform
                    ? `Worm DMs you in ${connectedPlatform}.`
                    : "Connect a chat platform first."
                }
                checked={currentMode === "bot"}
                disabled={
                  busy || currentMode === "bot" || !connectedPlatform
                }
                onClick={() => setPending("bot")}
              />
            </div>
          )}
        </div>
      )}

      {pending ? (
        <div
          data-testid="setup-mode-confirm-modal"
          role="dialog"
          aria-label="Confirm setup mode switch"
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(20, 20, 20, 0.45)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 100,
          }}
        >
          <div
            style={{
              background: "var(--wb-color-paper)",
              border: "1px solid var(--wb-color-aged-ink)",
              padding: 24,
              maxWidth: 460,
              display: "flex",
              flexDirection: "column",
              gap: 14,
            }}
          >
            <h3
              style={{
                margin: 0,
                fontFamily: "var(--wb-font-serif)",
                fontSize: 20,
              }}
            >
              Switch setup mode?
            </h3>
            <p
              style={{
                margin: 0,
                fontFamily: "var(--wb-font-serif)",
                fontSize: 13,
                color: "var(--wb-color-aged-ink-soft)",
                lineHeight: 1.5,
              }}
            >
              Switching from <strong>{currentMode}</strong> to{" "}
              <strong>{pending}</strong> resets in-flight progress. Already-
              answered steps remain in the ledger; the new mode picks up
              from where the prior path left off.
            </p>
            {error ? (
              <div
                data-testid="setup-mode-switcher-error"
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
            <div
              style={{
                display: "flex",
                justifyContent: "flex-end",
                gap: 8,
              }}
            >
              <button
                type="button"
                onClick={() => setPending(null)}
                disabled={busy}
                data-testid="setup-mode-cancel"
                className="wb-mono"
                style={{
                  fontSize: 11,
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                  padding: "6px 12px",
                  border: "1px solid var(--wb-color-aged-ink)",
                  background: "var(--wb-color-paper)",
                  cursor: busy ? "wait" : "pointer",
                  borderRadius: 0,
                }}
              >
                cancel
              </button>
              <button
                type="button"
                onClick={() => pending && commit(pending)}
                disabled={busy}
                data-testid="setup-mode-confirm"
                className="wb-mono"
                style={{
                  fontSize: 11,
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                  padding: "6px 12px",
                  border: "1px solid var(--wb-color-aged-ink)",
                  background: "var(--wb-color-botanical-green-soft)",
                  cursor: busy ? "wait" : "pointer",
                  borderRadius: 0,
                }}
              >
                {busy ? "switching…" : `switch to ${pending}`}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function ModeRadio({
  testId,
  label,
  hint,
  checked,
  disabled,
  onClick,
}: {
  testId: string;
  label: string;
  hint: string;
  checked: boolean;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="radio"
      data-testid={testId}
      aria-checked={checked}
      aria-disabled={disabled}
      disabled={disabled}
      onClick={onClick}
      style={{
        textAlign: "left",
        display: "flex",
        alignItems: "baseline",
        gap: 10,
        border: "1px solid var(--wb-color-paper-edge)",
        background: checked
          ? "var(--wb-color-botanical-green-soft)"
          : "var(--wb-color-paper)",
        padding: "10px 12px",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled && !checked ? 0.55 : 1,
        borderRadius: 0,
      }}
    >
      <span
        className="wb-mono"
        style={{
          fontSize: 11,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: checked
            ? "var(--wb-color-botanical-green-deep)"
            : "var(--wb-color-hash-gray)",
        }}
      >
        {checked ? "●" : "○"}
      </span>
      <span style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <span
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontSize: 14,
            fontWeight: 500,
          }}
        >
          {label}
        </span>
        <span
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontSize: 11,
            fontStyle: "italic",
            color: "var(--wb-color-aged-ink-soft)",
          }}
        >
          {hint}
        </span>
      </span>
    </button>
  );
}
