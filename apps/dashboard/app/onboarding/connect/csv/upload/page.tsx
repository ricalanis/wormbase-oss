/**
 * GET /onboarding/connect/csv/upload — CSV upload UI (Block G3 / PRD §17).
 *
 * Server component. Hosts the IdentityForm + CsvUploadForm composition.
 * Submitting both yields a single multipart POST to
 * /api/onboarding/upload that:
 *
 *   1. Calls proposeInstaller_FromForm.
 *   2. Streams the file bytes into worm-core's storage backend
 *      (LocalFsBackend in dev; S3Backend in prod).
 *   3. Writes emit_source_proposed pointing at the storage URI.
 *   4. Triggers the medallion cascade off the source_proposed entry.
 *   5. Redirects to /onboarding/whats-next.
 */
import { Page } from "@wormbase/design";
import { CsvUploadForm } from "../../../../../components/onboarding/CsvUploadForm";

export const metadata = {
  title: "WormBase · Connect CSV",
};

export const dynamic = "force-dynamic";

export default async function CsvUploadPage() {
  return (
    <Page subtitle="onboarding · tier 1 · upload a csv">
      <CsvUploadForm />
    </Page>
  );
}
