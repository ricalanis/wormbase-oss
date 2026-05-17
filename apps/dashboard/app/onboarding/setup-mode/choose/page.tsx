/**
 * GET /onboarding/setup-mode/choose — wizard-vs-bot fork (Block G4 / PRD §17).
 *
 * Two-card chooser:
 *   - Wizard: always available. Steps through the dashboard's existing
 *     T2 + T3 forms (domain pack, classifications, admin invites, KPI tree).
 *   - Bot: gated on at least one chat-platform install. The worm DMs the
 *     installer and walks through the same steps in chat. If no chat
 *     platform is connected, the card is disabled with a "Connect a chat
 *     platform first" hint + back link.
 *
 * Submitting either card POSTs to /api/onboarding/setup-mode (G4) which
 * proxies to worm-core POST /api/v1/setup-mode → emit_setup_mode_chosen.
 */
import { Page } from "@wormbase/design";
import { SetupModeChooser } from "../../../../components/onboarding/SetupModeChooser";
import { getInstalls } from "../../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";

export const metadata = {
  title: "WormBase · Pick setup mode",
};

export const dynamic = "force-dynamic";

const CHAT_PLATFORMS = new Set(["slack", "discord", "teams"]);

export default async function SetupModeChoosePage() {
  const companyId = await getCurrentCompanyId();
  const installs = await getInstalls(companyId);
  const chatInstalls = installs.filter(
    (i) => i.status === "active" && CHAT_PLATFORMS.has(i.platform),
  );
  const connectedPlatform = chatInstalls[0]?.platform ?? null;

  return (
    <Page subtitle="onboarding · setup mode · pick a path">
      <SetupModeChooser connectedPlatform={connectedPlatform} />
    </Page>
  );
}
