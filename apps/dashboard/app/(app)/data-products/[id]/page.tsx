/**
 * /data-products/{id} — drill-in view for one data product.
 *
 * F3 of docs/superpowers/plans/2026-04-26-production-dashboard.md +
 * W2.A8 of docs/superpowers/plans/2026-04-28-production-hardening.md.
 *
 * Hydrates a server-side fetch of the product + its runs + consumption,
 * then renders the DataProductDrawer client component which records a
 * dashboard consumption event on mount.
 *
 * W2.A8 adds the strict-replay primary action: the `<ReplayButton />`
 * posts to the new POST /api/v1/data-products/{id}/replay endpoint and
 * surfaces the "✓ bit-identical content_hash" badge on success — the
 * audit-grade affordance that proves replay determinism is real.
 */
import { notFound } from "next/navigation";
import {
  getDataProduct,
  listDataProductRuns,
  listDataProductConsumption,
} from "../../../../lib/server/data-products";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";
import { DataProductDrawer } from "../../../../components/data-products/DataProductDrawer";
import { ReplayButton } from "../../../../components/data-products/ReplayButton";
import { PageBoundary } from "../../../../components/chrome/PageBoundary";

export const dynamic = "force-dynamic";

export default async function DataProductDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const companyId = await getCurrentCompanyId();
  const dp = await getDataProduct(companyId, id);
  if (!dp) {
    notFound();
  }
  const [runs, consumption] = await Promise.all([
    listDataProductRuns(companyId, id),
    listDataProductConsumption(companyId, { dataProductId: id }),
  ]);
  return (
    <PageBoundary surface="data product" traceQuery={`?surface=data-product&id=${id}`}>
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <DataProductDrawer
        dataProduct={dp}
        runs={runs}
        consumption={consumption}
      />
      <section
        data-testid="strict-replay-section"
        style={{
          borderTop: "1px solid var(--wb-color-paper-edge)",
          paddingTop: 16,
        }}
      >
        <h2
          style={{
            margin: "0 0 8px 0",
            fontFamily: "var(--wb-font-serif)",
            fontSize: 16,
            fontWeight: 500,
            textTransform: "uppercase",
            letterSpacing: "0.08em",
          }}
        >
          Strict replay
        </h2>
        <p
          style={{
            margin: "0 0 12px",
            fontFamily: "var(--wb-font-serif)",
            fontSize: 13,
            color: "var(--wb-color-hash-gray)",
            maxWidth: 640,
          }}
        >
          Re-run this artifact against its pinned source-hashes. A passing
          replay surfaces the bit-identical content_hash badge — the
          audit-grade evidence that the autoresearch reproducibility
          guarantee is intact.
        </p>
        <ReplayButton dataProductId={id} />
      </section>
    </div>
    </PageBoundary>
  );
}
