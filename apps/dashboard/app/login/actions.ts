/**
 * Server actions for the `/login` tenant picker (W1.A3).
 *
 * `selectTenant` reads the submitted `slug` form field, validates it
 * against the known tenant registry, sets the `wormbase-tenant-slug`
 * cookie, and redirects to `/`. The `(app)` layout's redirect guard then
 * routes the user to either the dashboard (when an active install is
 * present) or `/onboarding` (when it isn't).
 *
 * No side-effects beyond the cookie set and the redirect — the picker
 * is a pure session-binding surface.
 */
"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { TENANT_COOKIE_NAME } from "../../lib/tenant-cookies";
import { findTenantBySlug } from "../../lib/tenants";

const TENANT_COOKIE_MAX_AGE = 60 * 60 * 24 * 30; // 30 days

export async function selectTenant(formData: FormData): Promise<void> {
  const raw = formData.get("slug");
  const slug = typeof raw === "string" ? raw.trim() : "";
  if (!slug) {
    redirect("/login?error=missing_slug");
  }
  const tenant = findTenantBySlug(slug);
  if (!tenant) {
    redirect(`/login?error=unknown_tenant&slug=${encodeURIComponent(slug)}`);
  }
  const store = await cookies();
  store.set(TENANT_COOKIE_NAME, tenant.slug, {
    httpOnly: false,
    sameSite: "lax",
    path: "/",
    maxAge: TENANT_COOKIE_MAX_AGE,
  });
  redirect("/");
}
