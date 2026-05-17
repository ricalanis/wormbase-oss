"use client";
/**
 * WhatsAppPairingFlow — W2-C of the WhatsApp dashboard surfacing wave.
 *
 * Stepwise pairing-instructions UI rendered on `/channels/connect/whatsapp`.
 * Documentation-as-UI: the operator runs the docker-exec commands from
 * their terminal, not the browser. We surface copy-paste affordances and
 * an honest "waiting for Install entry" status — no fake interactivity.
 *
 * Steps:
 *   1. ToS acknowledgment + bot phone-number form
 *   2. Operator commands (docker exec into wormbase-openclaw + wizard
 *      invocation, with QR-scan walk-through)
 *   3. Polling indicator: a "Refresh status" button that re-runs the
 *      install check via a `router.refresh()` round-trip back through
 *      the server component. No real-time polling — refresh-driven is
 *      capability-honest.
 *
 * The bot phone is captured local-only (component state) — production
 * env wiring is the operator's responsibility per the runbook
 * (`WORMBASE_WHATSAPP_BOT_PHONE_<TENANT>`). Capturing it here makes the
 * runbook's `<TENANT>` placeholder render with the operator's actual
 * value, which they then paste into `.env`.
 */
import { useCallback, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

export interface WhatsAppPairingFlowProps {
  /**
   * Whether a WhatsApp install row exists for this tenant. When true,
   * the page renders a "you're paired — confirm at /channels" success
   * banner instead of the pairing steps.
   */
  hasInstall: boolean;
  /**
   * The tenant slug (upper-cased and used as the suffix in
   * `WORMBASE_WHATSAPP_BOT_PHONE_<TENANT>`). Drives the rendered command
   * snippet so operators see the env var name they need.
   */
  tenantSlugUpper: string;
}

const DOCKER_CONFIGURE_CMD =
  "docker exec -it wormbase-openclaw openclaw configure --section channels";
const DOCKER_CHANNELS_LOGIN_CMD = (account: string) =>
  `docker exec -it wormbase-openclaw openclaw channels login --channel whatsapp --account ${account}`;

export function WhatsAppPairingFlow({
  hasInstall,
  tenantSlugUpper,
}: WhatsAppPairingFlowProps) {
  const router = useRouter();
  const [tosAcked, setTosAcked] = useState(false);
  const [phone, setPhone] = useState("");
  const account = tenantSlugUpper.toLowerCase() || "default";

  if (hasInstall) {
    return (
      <section
        data-testid="whatsapp-pairing-success"
        style={successSectionStyle}
      >
        <header style={successHeaderStyle}>
          <span className="wb-mono" style={successKickerStyle}>
            paired · install row landed
          </span>
          <h2 style={successHeadlineStyle}>WhatsApp is connected.</h2>
        </header>
        <p style={successBodyStyle}>
          A WhatsApp install entry is in this tenant&rsquo;s ledger. Open
          {" "}
          <Link
            href="/channels"
            data-testid="whatsapp-pairing-success-channels"
            style={successLinkStyle}
          >
            /channels
          </Link>
          {" "}to see the install card and confirm the channel roster, and
          {" "}
          <Link
            href="/channels"
            style={successLinkStyle}
          >
            drill in
          </Link>
          {" "}to the per-channel sync history.
        </p>
      </section>
    );
  }

  return (
    <div
      data-testid="whatsapp-pairing-flow"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 32,
      }}
    >
      <Step1ToSAndPhone
        tosAcked={tosAcked}
        onAck={(v) => setTosAcked(v)}
        phone={phone}
        onPhoneChange={setPhone}
        tenantSlugUpper={tenantSlugUpper}
      />
      <Step2OperatorCommands
        enabled={tosAcked}
        account={account}
        phone={phone}
        tenantSlugUpper={tenantSlugUpper}
      />
      <Step3PollingIndicator
        enabled={tosAcked}
        onRefresh={() => router.refresh()}
      />
    </div>
  );
}

interface Step1Props {
  tosAcked: boolean;
  onAck: (value: boolean) => void;
  phone: string;
  onPhoneChange: (value: string) => void;
  tenantSlugUpper: string;
}

function Step1ToSAndPhone({
  tosAcked,
  onAck,
  phone,
  onPhoneChange,
  tenantSlugUpper,
}: Step1Props) {
  return (
    <section data-testid="pairing-step-1" style={stepSectionStyle}>
      <StepHeader numeral="i" label="step one" title="Acknowledge the ToS posture" />
      <p style={stepBodyStyle}>
        OpenClaw&rsquo;s WhatsApp adapter rides{" "}
        <a
          href="https://github.com/WhiskeySockets/Baileys"
          target="_blank"
          rel="noopener noreferrer"
          style={stepLinkStyle}
        >
          Baileys
        </a>
        , an unofficial WhatsApp Web client. Pairing this adapter violates
        WhatsApp&rsquo;s Terms of Service. Bans propagate to the device
        WhatsApp identifies as the linked-device anchor — pair only on a
        dedicated test SIM you can lose tomorrow. Never pair an executive
        or customer-success personal number.
      </p>
      <label
        htmlFor="whatsapp-tos-ack"
        style={tosLabelStyle}
        data-testid="pairing-tos-label"
      >
        <input
          id="whatsapp-tos-ack"
          type="checkbox"
          data-testid="pairing-tos-ack"
          checked={tosAcked}
          onChange={(event) => onAck(event.target.checked)}
          style={{ marginRight: 10 }}
        />
        I&rsquo;m pairing on a dedicated test number, not a personal or
        executive WhatsApp account.
      </label>

      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <label
          htmlFor="whatsapp-bot-phone"
          className="wb-mono"
          style={inputLabelStyle}
        >
          Bot phone (E.164, no leading +)
        </label>
        <input
          id="whatsapp-bot-phone"
          type="text"
          data-testid="pairing-bot-phone"
          inputMode="tel"
          pattern="[0-9]*"
          placeholder="5511999999999"
          value={phone}
          onChange={(event) =>
            onPhoneChange(event.target.value.replace(/[^0-9]/g, ""))
          }
          style={textInputStyle}
        />
        <span style={inputHintStyle}>
          Local-only. After pairing, set this in your `.env` as{" "}
          <code className="wb-mono">
            WORMBASE_WHATSAPP_BOT_PHONE_{tenantSlugUpper}
          </code>
          {" "}— the env-var-resolution precedence is documented in
          {" "}
          <a
            href="https://github.com/wormbase/wormbase/blob/main/infra/openclaw/WHATSAPP_PAIRING.md"
            target="_blank"
            rel="noopener noreferrer"
            style={stepLinkStyle}
          >
            infra/openclaw/WHATSAPP_PAIRING.md
          </a>
          .
        </span>
      </div>
    </section>
  );
}

interface Step2Props {
  enabled: boolean;
  account: string;
  phone: string;
  tenantSlugUpper: string;
}

function Step2OperatorCommands({
  enabled,
  account,
  phone,
  tenantSlugUpper,
}: Step2Props) {
  return (
    <section
      data-testid="pairing-step-2"
      data-enabled={enabled ? "true" : "false"}
      style={{
        ...stepSectionStyle,
        opacity: enabled ? 1 : 0.55,
      }}
    >
      <StepHeader
        numeral="ii"
        label="step two"
        title="Run the operator commands"
      />
      <p style={stepBodyStyle}>
        From your operator shell, walk the OpenClaw configuration wizard
        and pick the WhatsApp option. The wizard prints a QR code to the
        container logs; scan it from the test phone&rsquo;s{" "}
        <em>WhatsApp → Settings → Linked Devices → Link a Device</em>.
      </p>

      <CopyableCommand
        label="configure wizard"
        testid="pairing-cmd-configure"
        command={DOCKER_CONFIGURE_CMD}
      />
      <CopyableCommand
        label={`fresh QR (account: ${account})`}
        testid="pairing-cmd-login"
        command={DOCKER_CHANNELS_LOGIN_CMD(account)}
      />

      <ol style={walkthroughStyle}>
        <li>
          <strong>Wizard option:</strong> when the configure prompt asks
          which channel to wire, select <code>whatsapp</code>. The wizard
          asks for the account slot — use{" "}
          <code className="wb-mono">{account}</code> (matches
          {" "}
          <code className="wb-mono">
            WORMBASE_WHATSAPP_OPENCLAW_ACCOUNT
          </code>
          ).
        </li>
        <li>
          <strong>Watch the logs.</strong>{" "}
          <code className="wb-mono">docker compose logs -f openclaw</code>
          {" "}prints the QR code and, once you scan, the line{" "}
          <code className="wb-mono">QR scanned, awaiting approval</code>.
        </li>
        <li>
          <strong>Approve the pairing.</strong> The wizard asks you to
          confirm; approve. The line{" "}
          <code className="wb-mono">whatsapp: account {account} online</code>
          {" "}lands when the session is live.
        </li>
        {phone ? (
          <li data-testid="pairing-env-snippet">
            <strong>Set the bot phone env var:</strong>{" "}
            <code className="wb-mono">
              WORMBASE_WHATSAPP_BOT_PHONE_{tenantSlugUpper}={phone}
            </code>
            {" "}in <code>.env</code>, then restart the channel-adapter so
            the resolver picks up the new value.
          </li>
        ) : null}
      </ol>
    </section>
  );
}

interface Step3Props {
  enabled: boolean;
  onRefresh: () => void;
}

function Step3PollingIndicator({ enabled, onRefresh }: Step3Props) {
  return (
    <section
      data-testid="pairing-step-3"
      data-enabled={enabled ? "true" : "false"}
      style={{
        ...stepSectionStyle,
        opacity: enabled ? 1 : 0.55,
      }}
    >
      <StepHeader
        numeral="iii"
        label="step three"
        title="Wait for the install entry"
      />
      <p style={stepBodyStyle}>
        Once the QR scan completes and the channel-adapter sees the first
        WhatsApp infrastructure event, the worm writes an{" "}
        <code className="wb-mono">install_completed</code> ledger entry.
        That ledger row is what the dashboard reads to switch this page
        into its &ldquo;paired&rdquo; state. We don&rsquo;t poll the
        ledger continuously here — pairing typically completes in
        under a minute, and the explicit refresh keeps the surface
        capability-honest.
      </p>
      <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        <button
          type="button"
          data-testid="pairing-refresh"
          onClick={onRefresh}
          disabled={!enabled}
          style={refreshButtonStyle}
        >
          Refresh status
        </button>
        <span
          data-testid="pairing-waiting-status"
          className="wb-mono"
          style={waitingStatusStyle}
        >
          waiting for install entry to land&hellip;
        </span>
      </div>
      <p style={{ ...stepBodyStyle, marginTop: 4 }}>
        Or open{" "}
        <Link href="/channels" data-testid="pairing-channels-link" style={stepLinkStyle}>
          /channels
        </Link>
        {" "}directly to confirm — the install card surfaces the moment the
        ledger entry lands.
      </p>
    </section>
  );
}

interface CopyableCommandProps {
  label: string;
  command: string;
  testid: string;
}

function CopyableCommand({ label, command, testid }: CopyableCommandProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(command);
        setCopied(true);
        setTimeout(() => setCopied(false), 2500);
      }
    } catch {
      // Clipboard API may be denied (insecure context, browser config); the
      // command block stays selectable so operators can copy manually.
    }
  }, [command]);

  return (
    <div data-testid={testid} style={cmdBlockStyle}>
      <header style={cmdHeaderStyle}>
        <span className="wb-mono" style={cmdLabelStyle}>
          {label}
        </span>
        <button
          type="button"
          data-testid={`${testid}-copy`}
          onClick={handleCopy}
          style={copyButtonStyle}
        >
          {copied ? "copied ✓" : "copy"}
        </button>
      </header>
      <pre style={preStyle}>
        <code className="wb-mono">{command}</code>
      </pre>
    </div>
  );
}

function StepHeader({
  numeral,
  label,
  title,
}: {
  numeral: string;
  label: string;
  title: string;
}) {
  return (
    <header style={stepHeaderStyle}>
      <span className="wb-mono" style={stepKickerStyle}>
        plate {numeral} · {label}
      </span>
      <h2 style={stepTitleStyle}>{title}</h2>
    </header>
  );
}

const stepSectionStyle = {
  display: "flex",
  flexDirection: "column",
  gap: 14,
  padding: "24px 24px",
  border: "1px solid var(--wb-color-rule-line)",
  background: "var(--wb-color-paper)",
  borderRadius: 2,
  transition: "opacity 120ms ease",
} as const;

const stepHeaderStyle = {
  display: "flex",
  flexDirection: "column",
  gap: 4,
} as const;

const stepKickerStyle = {
  fontSize: 10,
  letterSpacing: "0.18em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
} as const;

const stepTitleStyle = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: 22,
  fontWeight: 600,
  color: "var(--wb-color-aged-ink)",
} as const;

const stepBodyStyle = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: 14,
  color: "var(--wb-color-aged-ink)",
  lineHeight: 1.6,
} as const;

const stepLinkStyle = {
  color: "var(--wb-color-aged-ink)",
  textUnderlineOffset: 3,
} as const;

const tosLabelStyle = {
  display: "flex",
  alignItems: "flex-start",
  fontFamily: "var(--wb-font-serif)",
  fontSize: 13,
  color: "var(--wb-color-aged-ink)",
  lineHeight: 1.5,
  cursor: "pointer",
  padding: "8px 0",
} as const;

const inputLabelStyle = {
  fontSize: 10,
  letterSpacing: "0.16em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
} as const;

const textInputStyle = {
  fontFamily: "var(--wb-font-mono)",
  fontSize: 13,
  padding: "8px 10px",
  border: "1px solid var(--wb-color-aged-ink)",
  background: "var(--wb-color-paper)",
  color: "var(--wb-color-aged-ink)",
  borderRadius: 2,
  width: "100%",
  maxWidth: 320,
} as const;

const inputHintStyle = {
  fontFamily: "var(--wb-font-serif)",
  fontStyle: "italic",
  fontSize: 12,
  color: "var(--wb-color-hash-gray)",
  lineHeight: 1.55,
} as const;

const cmdBlockStyle = {
  display: "flex",
  flexDirection: "column",
  gap: 8,
  border: "1px solid var(--wb-color-rule-line)",
  background: "var(--wb-color-paper-deep)",
  padding: "12px 14px",
  borderRadius: 2,
} as const;

const cmdHeaderStyle = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 12,
} as const;

const cmdLabelStyle = {
  fontSize: 10,
  letterSpacing: "0.16em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
} as const;

const copyButtonStyle = {
  fontFamily: "var(--wb-font-mono)",
  fontSize: 11,
  letterSpacing: "0.04em",
  padding: "4px 10px",
  border: "1px solid var(--wb-color-aged-ink)",
  background: "var(--wb-color-paper)",
  color: "var(--wb-color-aged-ink)",
  cursor: "pointer",
  borderRadius: 2,
} as const;

const preStyle = {
  margin: 0,
  fontFamily: "var(--wb-font-mono)",
  fontSize: 12,
  color: "var(--wb-color-aged-ink)",
  background: "transparent",
  whiteSpace: "pre-wrap",
  wordBreak: "break-word",
  lineHeight: 1.6,
} as const;

const walkthroughStyle = {
  margin: "8px 0 0",
  paddingLeft: 22,
  display: "flex",
  flexDirection: "column",
  gap: 8,
  fontFamily: "var(--wb-font-serif)",
  fontSize: 14,
  lineHeight: 1.55,
  color: "var(--wb-color-aged-ink)",
} as const;

const refreshButtonStyle = {
  fontFamily: "var(--wb-font-mono)",
  fontSize: 12,
  letterSpacing: "0.04em",
  padding: "8px 16px",
  border: "1px solid var(--wb-color-aged-ink)",
  background: "var(--wb-color-paper)",
  color: "var(--wb-color-aged-ink)",
  cursor: "pointer",
  borderRadius: 2,
} as const;

const waitingStatusStyle = {
  fontSize: 11,
  letterSpacing: "0.06em",
  color: "var(--wb-color-hash-gray)",
} as const;

const successSectionStyle = {
  border: "1px solid var(--wb-color-aged-ink)",
  background: "var(--wb-color-paper-deep)",
  padding: "24px 24px",
  display: "flex",
  flexDirection: "column",
  gap: 10,
  borderRadius: 2,
} as const;

const successHeaderStyle = {
  display: "flex",
  flexDirection: "column",
  gap: 4,
} as const;

const successKickerStyle = {
  fontSize: 10,
  letterSpacing: "0.18em",
  textTransform: "uppercase",
  color: "var(--wb-color-aged-ink-soft)",
} as const;

const successHeadlineStyle = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: 22,
  fontWeight: 600,
  color: "var(--wb-color-aged-ink)",
} as const;

const successBodyStyle = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: 14,
  color: "var(--wb-color-aged-ink)",
  lineHeight: 1.6,
} as const;

const successLinkStyle = {
  color: "var(--wb-color-aged-ink)",
  textUnderlineOffset: 3,
} as const;
