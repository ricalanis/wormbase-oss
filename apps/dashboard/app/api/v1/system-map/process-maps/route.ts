/**
 * GET /api/v1/system-map/process-maps — list process_map data products.
 *
 * P10 of `docs/superpowers/specs/2026-04-29-demo-day-prd.md` §7. Powers
 * /system-map's "Conversation Process Maps" lens by projecting the
 * subset of data products whose ``kind === 'process_map'`` (the gold
 * artifact emitted by ``RecurringQuestionProcessMapperReactivity``).
 *
 * Reads ledger projections via ``getProcessMapDataProducts``; the route adds no
 * write surface — process maps are proposed by the worm and confirmed
 * via the existing /data-products dashboard. Confirmation moves a
 * row from ``status: "proposed"`` to ``status: "generated"`` (admin
 * publishes) or ``"archived"`` (admin discards).
 *
 * Role-aware filtering: the lens is admin-/observer-visible. Members
 * see only the process maps in their domain access set. Implemented
 * server-side via ``getDomainAccessSet`` + ``filterByDomainAccess`` —
 * the same filter the /data-products surface uses.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { getProcessMapDataProducts } from "../../../../../lib/ledger-client";
import { getCurrentPerson } from "../../../../../lib/server/identity";
import {
  filterByDomainAccess,
  getDomainAccessSet,
} from "../../../../../lib/server/role-filter";
import { getTenantFromCookies } from "../../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";

export async function GET(_req: NextRequest) {
  const tenant = await getTenantFromCookies();
  const me = await getCurrentPerson(tenant.companyId);
  const access = await getDomainAccessSet(tenant.companyId, me);
  const all = await getProcessMapDataProducts(tenant.companyId);
  const visible = filterByDomainAccess(all, me, access);
  return NextResponse.json({ processMaps: visible });
}
