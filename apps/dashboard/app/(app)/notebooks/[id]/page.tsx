/**
 * /notebooks/{id} — drill-in view for one notebook.
 *
 * F4 of docs/superpowers/plans/2026-04-26-production-dashboard.md +
 * W2.A8 of docs/superpowers/plans/2026-04-28-production-hardening.md.
 *
 * The viewer renders the notebook's metadata + run-history. W2.A8 layers
 * on the cell-by-cell view (markdown + code) and the Sign action: an
 * admin Person attests the latest run is canonical, and the dashboard
 * surfaces the per-Person signature receipt as the audit-grade
 * attestation badge.
 */
import { notFound } from "next/navigation";
import {
  getNotebook,
  listNotebookRuns,
} from "../../../../lib/server/notebooks";
import {
  getCurrentCompanyId,
  getTenantFromCookies,
} from "../../../../lib/tenant-cookies";
import { getCurrentPerson } from "../../../../lib/server/identity";
import { NotebookViewer } from "../../../../components/notebooks/NotebookViewer";
import { CellByCellView } from "../../../../components/notebooks/CellByCellView";
import { SignNotebookButton } from "../../../../components/notebooks/SignNotebookButton";
import { PageBoundary } from "../../../../components/chrome/PageBoundary";

export const dynamic = "force-dynamic";

export default async function NotebookDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const companyId = await getCurrentCompanyId();
  const tenant = await getTenantFromCookies();
  const nb = await getNotebook(companyId, id);
  if (!nb) {
    notFound();
  }
  const runs = await listNotebookRuns(companyId, id);
  const me = await getCurrentPerson(tenant.companyId);
  const latestRun = runs.length > 0 ? runs[runs.length - 1] : null;
  const alreadySigned =
    nb.status === "published" && nb.latestPublishedRunId !== null;

  return (
    <PageBoundary surface="notebook" traceQuery={`?surface=notebook&id=${id}`}>
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <NotebookViewer notebook={nb} runs={runs} />

      <section
        data-testid="cell-by-cell-section"
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
          Cell-by-cell
        </h2>
        <CellByCellView cells={nb.cells} latestRun={latestRun} />
      </section>

      <section
        data-testid="sign-section"
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
          Sign as canonical
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
          Sign the latest run as canonical. The signature receipt is a
          deterministic hash of (notebook · run · owner · version · signer)
          — the same admin signing the same run produces the same
          receipt, so the attestation survives a ledger replay.
        </p>
        <SignNotebookButton
          notebookId={id}
          runId={latestRun?.runId ?? null}
          version={nb.version ?? "1"}
          ownerPersonId={nb.ownerPersonId ?? me?.personId ?? null}
          alreadySigned={alreadySigned}
        />
      </section>
    </div>
    </PageBoundary>
  );
}
