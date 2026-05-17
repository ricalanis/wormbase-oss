/**
 * /data-products — production surface (F3).
 *
 * Lists every data product in the tenant with role-aware domain filtering
 * (D8). Filters (kind / status / domain / person) are URL-driven so views
 * are shareable.
 */
import { listDataProducts } from "../../../lib/server/data-products";
import { getCurrentCompanyId } from "../../../lib/tenant-cookies";
import { getCurrentPerson } from "../../../lib/server/identity";
import {
  filterByDomainAccess,
  getDomainAccessSet,
  memberHasNoAccess,
} from "../../../lib/server/role-filter";
import { DataProductsTable } from "../../../components/data-products/DataProductsTable";
import { Filters } from "../../../components/data-products/Filters";
import { PageBoundary } from "../../../components/chrome/PageBoundary";

export const metadata = { title: "WormBase · Data products" };
export const dynamic = "force-dynamic";

export default async function DataProductsPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const params = await searchParams;
  const companyId = await getCurrentCompanyId();
  const me = await getCurrentPerson(companyId);
  const access = await getDomainAccessSet(companyId, me);

  const filters = {
    requestedBy: typeof params.requested_by === "string" ? params.requested_by : undefined,
    domainId: typeof params.domain_id === "string" ? params.domain_id : undefined,
    kind: typeof params.kind === "string" ? params.kind : undefined,
    status: typeof params.status === "string" ? params.status : undefined,
  };
  const all = await listDataProducts(companyId, filters);
  const visible = filterByDomainAccess(all, me, access);

  return (
    <PageBoundary surface="data products" traceQuery="?surface=data-products">
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
            Pl. VI · Data product roster
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
            Data products
          </h1>
          <p
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            {visible.length} artifact{visible.length === 1 ? "" : "s"}. Each is
            replayable from pinned source hashes.
          </p>
        </div>
        <Filters />
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
          You don&rsquo;t have any domain access yet — ask an admin to grant
          you a domain role.
        </p>
      ) : (
        <DataProductsTable dataProducts={visible} />
      )}
    </PageBoundary>
  );
}
