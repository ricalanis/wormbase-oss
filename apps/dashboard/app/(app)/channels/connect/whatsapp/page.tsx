/**
 * /channels/connect/whatsapp — W2-C of the WhatsApp dashboard surfacing
 * wave (2026-05-07).
 *
 * Dedicated pairing-instructions page reached from the WhatsApp empty
 * state on `/channels`. The page is documentation-as-UI: capability
 * honesty over fakery — the operator runs the docker exec commands
 * themselves; we render copy-paste affordances and an honest
 * "waiting for the install entry" status driven by `router.refresh()`.
 *
 * Three steps surface in `WhatsAppPairingFlow`:
 *   1. ToS acknowledgment + bot phone-number form
 *   2. Operator commands (configure wizard + QR-scan walkthrough)
 *   3. Polling indicator (refresh-driven, ledger-backed)
 *
 * Role gating: admin-only. Members + observers + installers without
 * admin grant see a visible "this is admin-only" empty state — silent
 * 403 redirects are demo seams disguised as security per CLAUDE.md §9.
 * The honest empty state names the role required, links back to
 * /channels, and tells the user their current role.
 *
 * Cross-link: the page footer points at the full operator runbook at
 * `infra/openclaw/WHATSAPP_PAIRING.md` for the credential-persistence,
 * troubleshooting, and re-pair flows the wizard does not cover.
 */
import Link from "next/link";

import { PageBoundary } from "../../../../../components/chrome/PageBoundary";
import { WhatsAppGraduationBanner } from "../../../../../components/channels/WhatsAppGraduationBanner";
import { WhatsAppPairingFlow } from "../../../../../components/channels/WhatsAppPairingFlow";
import { getInstalls } from "../../../../../lib/ledger-client";
import { getCurrentPerson } from "../../../../../lib/server/identity";
import { getTenantFromCookies } from "../../../../../lib/tenant-cookies";

export const metadata = {
  title: "WormBase · Connect WhatsApp",
  description:
    "Pair the WormBase worm to a WhatsApp test number via the OpenClaw + Baileys gateway. Operator-led: ToS acknowledgment, configure-wizard walkthrough, QR scan, and post-pair install confirmation.",
};

export const dynamic = "force-dynamic";

const RUNBOOK_URL =
  "https://github.com/wormbase/wormbase/blob/main/infra/openclaw/WHATSAPP_PAIRING.md";

export default async function ConnectWhatsAppPage() {
  const tenant = await getTenantFromCookies();
  const me = await getCurrentPerson(tenant.companyId);

  const role = me?.tenancyRole ?? null;
  const isAdmin = role === "admin" || role === "installer";

  if (!isAdmin) {
    return (
      <PageBoundary
        surface="connect-whatsapp"
        traceQuery="?surface=connect-whatsapp"
      >
        <PageHeader role={role} />
        <section
          data-testid="connect-whatsapp-not-admin"
          style={notAdminStyle}
        >
          <span className="wb-mono" style={notAdminKickerStyle}>
            admin-only · pairing requires elevated grants
          </span>
          <h2 style={notAdminHeadlineStyle}>
            Pairing WhatsApp is reserved for admins.
          </h2>
          <p style={notAdminBodyStyle}>
            The pairing flow runs operator-level docker commands against the
            OpenClaw container and writes a tenant-wide install entry. Your
            current role —{" "}
            <code className="wb-mono">{role ?? "unresolved"}</code> — is not
            permitted to initiate the pair. Ask an admin for this tenant to
            walk the flow, or request a role upgrade on{" "}
            <Link href="/people" style={notAdminLinkStyle}>
              /people
            </Link>
            .
          </p>
        </section>
      </PageBoundary>
    );
  }

  let hasInstall = false;
  try {
    const installs = await getInstalls(tenant.companyId);
    hasInstall = installs.some(
      (i) => i.platform === "whatsapp" && i.status === "active",
    );
  } catch {
    hasInstall = false;
  }

  const tenantSlugUpper = (tenant.slug ?? "").toUpperCase();

  return (
    <PageBoundary
      surface="connect-whatsapp"
      traceQuery="?surface=connect-whatsapp"
    >
      <PageHeader role={role} />
      <WhatsAppGraduationBanner paired={hasInstall} />
      <p style={leadStyle}>
        Pair the worm to a WhatsApp test number through the OpenClaw +
        Baileys gateway. The flow has three steps: acknowledge the ToS
        posture, run the operator commands from your shell, and wait for
        the install entry to land in the ledger. This page does not run
        the docker commands for you — capability honesty: pairing is an
        operator-shell action, not a dashboard click.
      </p>

      <WhatsAppPairingFlow
        hasInstall={hasInstall}
        tenantSlugUpper={tenantSlugUpper || "TENANT"}
      />

      <footer
        data-testid="connect-whatsapp-runbook"
        style={runbookFooterStyle}
      >
        <span className="wb-mono" style={runbookKickerStyle}>
          full operator runbook
        </span>
        <p style={runbookBodyStyle}>
          The runbook covers the rest: credential persistence, re-pair
          flow when the linked-device session expires, log-grammar
          verification, post-pair operator checklist, and recovery from
          ban / session-revoke.
        </p>
        <a
          href={RUNBOOK_URL}
          target="_blank"
          rel="noopener noreferrer"
          data-testid="connect-whatsapp-runbook-link"
          style={runbookLinkStyle}
        >
          infra/openclaw/WHATSAPP_PAIRING.md →
        </a>
      </footer>
    </PageBoundary>
  );
}

function PageHeader({ role }: { role: string | null }) {
  return (
    <header style={headerStyle}>
      <span className="wb-mono" style={headerKickerStyle}>
        Pl. X.b · Channels · Connect WhatsApp
      </span>
      <h1 style={headerTitleStyle}>Connect WhatsApp</h1>
      <p style={headerSubStyle}>
        Operator-led pairing through OpenClaw Baileys. Bans propagate to
        the linked-device anchor — pair only on a dedicated test number.
      </p>
      <Link
        href="/channels"
        data-testid="connect-whatsapp-back-to-channels"
        style={backLinkStyle}
      >
        ← Back to /channels{role ? ` (you · ${role})` : ""}
      </Link>
    </header>
  );
}

const headerStyle = {
  display: "flex",
  flexDirection: "column",
  gap: 6,
} as const;

const headerKickerStyle = {
  fontSize: 10,
  letterSpacing: "0.18em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
} as const;

const headerTitleStyle = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: 34,
  fontWeight: 500,
  letterSpacing: "-0.01em",
  color: "var(--wb-color-aged-ink)",
} as const;

const headerSubStyle = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontStyle: "italic",
  fontSize: 14,
  color: "var(--wb-color-hash-gray)",
  maxWidth: 720,
  lineHeight: 1.5,
} as const;

const backLinkStyle = {
  marginTop: 4,
  fontFamily: "var(--wb-font-mono)",
  fontSize: 11,
  letterSpacing: "0.04em",
  color: "var(--wb-color-aged-ink)",
  textDecoration: "none",
  alignSelf: "flex-start",
} as const;

const leadStyle = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: 15,
  color: "var(--wb-color-aged-ink)",
  lineHeight: 1.6,
  maxWidth: 760,
} as const;

const runbookFooterStyle = {
  marginTop: 16,
  display: "flex",
  flexDirection: "column",
  gap: 8,
  padding: "20px 24px",
  border: "1px solid var(--wb-color-rule-line)",
  background: "var(--wb-color-paper-deep)",
  borderRadius: 2,
} as const;

const runbookKickerStyle = {
  fontSize: 10,
  letterSpacing: "0.18em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
} as const;

const runbookBodyStyle = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: 13,
  color: "var(--wb-color-aged-ink)",
  lineHeight: 1.6,
} as const;

const runbookLinkStyle = {
  fontFamily: "var(--wb-font-mono)",
  fontSize: 12,
  letterSpacing: "0.04em",
  color: "var(--wb-color-aged-ink)",
  textUnderlineOffset: 3,
  alignSelf: "flex-start",
} as const;

const notAdminStyle = {
  display: "flex",
  flexDirection: "column",
  gap: 8,
  padding: "24px 24px",
  border: "1px dashed var(--wb-color-sepia-warning-deep)",
  background: "var(--wb-color-paper-deep)",
  borderRadius: 2,
} as const;

const notAdminKickerStyle = {
  fontSize: 10,
  letterSpacing: "0.18em",
  textTransform: "uppercase",
  color: "var(--wb-color-sepia-warning-deep)",
} as const;

const notAdminHeadlineStyle = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: 22,
  fontWeight: 600,
  color: "var(--wb-color-aged-ink)",
} as const;

const notAdminBodyStyle = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: 14,
  color: "var(--wb-color-aged-ink)",
  lineHeight: 1.6,
} as const;

const notAdminLinkStyle = {
  color: "var(--wb-color-aged-ink)",
  textUnderlineOffset: 3,
} as const;
