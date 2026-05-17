/**
 * GET /settings/setup-mode — admin-only setup-mode switcher (Block G6).
 *
 * Reads the current install row's setup_mode + setup_completed_at from
 * the ledger projection. Admins can switch via the SetupModeSwitcher
 * component, which POSTs to /api/onboarding/setup-mode (G4).
 *
 * Per PRD §17, switching only resets progress when the previous mode is
 * incomplete; if setup_completed_at is set, switching is a no-op (the
 * choice is historical and the dashboard banner reflects that).
 */
import { Page } from "@wormbase/design";
import { SetupModeSwitcher } from "../../../../components/settings/SetupModeSwitcher";
import { PageBoundary } from "../../../../components/chrome/PageBoundary";
import { getCurrentPerson } from "../../../../lib/server/identity";
import { getInstalls } from "../../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";

export const metadata = { title: "WormBase · Settings · Setup mode" };

export const dynamic = "force-dynamic";

const CHAT_PLATFORMS = new Set(["slack", "discord", "teams"]);

export default async function SetupModeSettingsPage() {
  const companyId = await getCurrentCompanyId();
  const me = await getCurrentPerson(companyId);
  const installs = await getInstalls(companyId);

  // Pick a representative install for the read (every install row in a
  // tenant carries the same setup_mode + setup_completed_at since the
  // projection stamps tenant-level).
  const representative = installs.find((i) => i.status === "active");
  const currentMode = representative?.setupMode ?? null;
  const completedAt = representative?.setupCompletedAt ?? null;
  const connectedPlatform =
    installs.find(
      (i) => i.status === "active" && CHAT_PLATFORMS.has(i.platform),
    )?.platform ?? null;

  const isAdmin =
    me?.tenancyRole === "admin" || me?.tenancyRole === "installer";

  return (
    <PageBoundary surface="setup mode" traceQuery="?surface=setup-mode">
      <Page subtitle="settings · setup mode">
        <SetupModeSwitcher
          currentMode={currentMode}
          completedAt={completedAt}
          connectedPlatform={connectedPlatform}
          isAdmin={isAdmin}
        />
      </Page>
    </PageBoundary>
  );
}
