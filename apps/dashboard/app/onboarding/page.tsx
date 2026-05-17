import { Suspense } from "react";

import { Page } from "@wormbase/design";
import { Tier0 } from "../../components/onboarding/Tier0";
import { TimeToAhaPanel } from "../../components/onboarding/TimeToAhaPanel";
import { getOnboardingMilestones } from "../../lib/ledger-client";
import { getCurrentCompanyId } from "../../lib/tenant-cookies";

export const metadata = {
  title: "WormBase · Onboarding",
};

/**
 * Onboarding landing — Tier 0 chat-first connect (Block I3).
 *
 * Block I (production-dashboard PRD §17, REVISED 2026-04-27):
 * minimal-friction onboarding. The connector grid retired from
 * /onboarding (it stays at /sources/new for post-install progressive
 * enhancement). One tap on a chat-platform button drives Tier 0;
 * complete_install auto-provisions the default local lake (see
 * provision_local_lake in worm-core/write_actions.py — Block I2) so
 * the tenant has bronze + silver + gold visible at /sources from
 * minute zero, before any external source connects.
 *
 * The wizard-vs-bot fork moves to a banner CTA on the dashboard
 * post-install (Block I5) — no longer a forced redirect.
 */
export default async function OnboardingPage() {
  const companyId = await getCurrentCompanyId();
  const milestones = await getOnboardingMilestones(companyId);
  return (
    <Page subtitle="onboarding · tier 0 · connect a channel">
      <Suspense fallback={null}>
        <Tier0 />
      </Suspense>

      <section
        style={{ display: "flex", flexDirection: "column", gap: 8 }}
        aria-label="time to aha"
      >
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 14,
            color: "var(--wb-color-aged-ink)",
            lineHeight: 1.55,
          }}
        >
          The worm builds the lake as it lurks. These six milestones are the
          canonical first-day proof that the knowledge factory is running:
          install → first source proposal → first concept confirmed → first
          gold KPI → first process map → first autoresearch experiment.
          Lit milestones below are derived from the live ledger.
        </p>
        <TimeToAhaPanel milestones={milestones} />
      </section>
    </Page>
  );
}
