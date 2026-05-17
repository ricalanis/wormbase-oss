/**
 * GET /onboarding/connect/{connector}/credentials — Tier 1 credential paste.
 *
 * G3 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 *
 * Server component. Resolves the connector kind from the catalog,
 * renders the IdentityForm + the schema-driven CredentialForm in one
 * page. Submitting both yields a single POST to
 * /onboarding/connect/{kind}/connect that:
 *
 *   1. Calls proposeInstaller_FromForm (writes Person + tenancy roles +
 *      install_completed via worm-core POST /api/v1/installs).
 *   2. Runs Connector.authenticate + discover via the Python connector.
 *   3. Writes emit_source_proposed + bronze + silver + gold cascade.
 *   4. Redirects to /onboarding/whats-next.
 */
import { notFound } from "next/navigation";
import { Page } from "@wormbase/design";

import {
  getConnectorByKind,
} from "../../../../../lib/lake-surfaces-catalog";
import { CredentialForm } from "../../../../../components/onboarding/CredentialForm";

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ connector: string }>;
}

export default async function CredentialsPage({ params }: Props) {
  const { connector } = await params;
  const entry = getConnectorByKind(connector);
  if (!entry || entry.status === "coming_soon") {
    notFound();
  }

  return (
    <Page subtitle={`onboarding · tier 1 · connect ${entry.label}`}>
      <CredentialForm connector={entry} />
    </Page>
  );
}
