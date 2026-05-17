import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { TENANT_COOKIE_NAME } from "../../../lib/tenant-cookies";
import { findTenantBySlug } from "../../../lib/tenants";

/**
 * POST /api/tenant — switch the current tenant.
 *
 * Body: `{ slug: string }`. Returns the resolved tenant. Unknown slugs are
 * rejected with 400 so the client can recover.
 */
export async function POST(req: Request) {
  const body = (await req.json().catch(() => null)) as
    | { slug?: unknown }
    | null;
  const slug = typeof body?.slug === "string" ? body.slug : "";
  const tenant = findTenantBySlug(slug);
  if (!tenant) {
    return NextResponse.json(
      { ok: false, error: `unknown tenant: ${slug}` },
      { status: 400 }
    );
  }
  const store = await cookies();
  store.set(TENANT_COOKIE_NAME, tenant.slug, {
    path: "/",
    sameSite: "lax",
    httpOnly: false,
    // 30 days — demo-friendly, no auth involved.
    maxAge: 60 * 60 * 24 * 30,
  });
  return NextResponse.json({ ok: true, tenant });
}
