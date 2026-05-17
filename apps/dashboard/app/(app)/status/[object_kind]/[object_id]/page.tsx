/**
 * /status/[object_kind]/[object_id] — universal status surface
 * (Onboarding Sub-wave B, 2026-05-30).
 *
 * One URL covers every institutional object kind. Real probes for
 * connectors land in Sub-wave D; until then state is derived from
 * existing ledger projections.
 */
import { notFound } from "next/navigation";

import { PageBoundary } from "../../../../../components/chrome/PageBoundary";
import { ObjectStatusView } from "../../../../../components/onboard/ObjectStatusView";
import {
  getObjectStatus,
  isStatusKind,
} from "../../../../../lib/onboard";
import { getCurrentCompanyId } from "../../../../../lib/tenant-cookies";

export const metadata = { title: "WormBase · Object status" };

export const dynamic = "force-dynamic";

interface RouteParams {
  params: Promise<{ object_kind: string; object_id: string }>;
}

export default async function ObjectStatusPage({
  params,
}: RouteParams): Promise<JSX.Element> {
  const { object_kind, object_id } = await params;
  if (!isStatusKind(object_kind)) {
    notFound();
  }
  const companyId = await getCurrentCompanyId();
  const status = await getObjectStatus(companyId, object_kind, object_id);

  return (
    <PageBoundary
      surface="object status"
      traceQuery={`?surface=status.${object_kind}`}
    >
      <ObjectStatusView status={status} />
    </PageBoundary>
  );
}
