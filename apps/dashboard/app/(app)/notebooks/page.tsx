/**
 * /notebooks — production surface (F4).
 *
 * Lists every notebook in the tenant with role-aware domain filtering.
 */
import { listNotebooks } from "../../../lib/server/notebooks";
import { getCurrentCompanyId } from "../../../lib/tenant-cookies";
import { getCurrentPerson } from "../../../lib/server/identity";
import {
  filterByDomainAccess,
  getDomainAccessSet,
  memberHasNoAccess,
} from "../../../lib/server/role-filter";
import { NotebooksTable } from "../../../components/notebooks/NotebooksTable";
import { PageBoundary } from "../../../components/chrome/PageBoundary";

export const metadata = { title: "WormBase · Notebooks" };
export const dynamic = "force-dynamic";

export default async function NotebooksPage() {
  const companyId = await getCurrentCompanyId();
  const me = await getCurrentPerson(companyId);
  const access = await getDomainAccessSet(companyId, me);
  const all = await listNotebooks(companyId);
  const visible = filterByDomainAccess(all, me, access);

  return (
    <PageBoundary surface="notebooks" traceQuery="?surface=notebooks">
      <header
        style={{
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          gap: 16,
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            Pl. VII · Notebook ledger
          </span>
          <h1
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 34,
              fontWeight: 500,
              letterSpacing: "-0.01em",
            }}
          >
            Notebooks
          </h1>
          <p
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            {visible.length} notebook{visible.length === 1 ? "" : "s"}. Each
            run is a hash-chained ledger entry.
          </p>
        </div>
      </header>

      {memberHasNoAccess(me, access) ? (
        <p
          style={{
            margin: 0,
            padding: 16,
            border: "1px dashed var(--wb-color-aged-ink)",
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          You don&rsquo;t have any domain access yet — ask an admin.
        </p>
      ) : (
        <NotebooksTable notebooks={visible} />
      )}
    </PageBoundary>
  );
}
