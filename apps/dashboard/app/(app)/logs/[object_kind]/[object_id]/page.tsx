/**
 * /logs/[object_kind]/[object_id] — universal logs surface
 * (Onboarding Sub-wave B, 2026-05-30).
 *
 * Filters the ledger by id-match against payload args and renders a
 * paginated table. Same shape as v2.A's subscription audit panel; no
 * new projection table required.
 */
import { notFound } from "next/navigation";

import { PageBoundary } from "../../../../../components/chrome/PageBoundary";
import { ObjectLogsView } from "../../../../../components/onboard/ObjectLogsView";
import {
  getObjectLogs,
  isStatusKind,
} from "../../../../../lib/onboard";
import { getCurrentCompanyId } from "../../../../../lib/tenant-cookies";

export const metadata = { title: "WormBase · Object logs" };

export const dynamic = "force-dynamic";

interface RouteParams {
  params: Promise<{ object_kind: string; object_id: string }>;
  searchParams: Promise<{ offset?: string; limit?: string }>;
}

function parseInt32(value: string | undefined, fallback: number): number {
  if (!value) return fallback;
  const n = parseInt(value, 10);
  return Number.isFinite(n) && n >= 0 ? n : fallback;
}

export default async function ObjectLogsPage({
  params,
  searchParams,
}: RouteParams): Promise<JSX.Element> {
  const { object_kind, object_id } = await params;
  const sp = (await searchParams) ?? {};
  if (!isStatusKind(object_kind)) {
    notFound();
  }
  const limit = Math.min(parseInt32(sp.limit, 25), 100);
  const offset = parseInt32(sp.offset, 0);
  const companyId = await getCurrentCompanyId();
  const page = await getObjectLogs(companyId, object_kind, object_id, {
    limit,
    offset,
  });

  return (
    <PageBoundary
      surface="object logs"
      traceQuery={`?surface=logs.${object_kind}`}
    >
      <ObjectLogsView
        kind={object_kind}
        objectId={object_id}
        page={page}
        offset={offset}
        limit={limit}
      />
    </PageBoundary>
  );
}
