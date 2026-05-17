"use client";
/**
 * Client-side tenant context.
 *
 * Most dashboard reads happen in RSCs and resolve the tenant from cookies on
 * the server (see `tenant-cookies.ts`). The context here exists for client
 * components — primarily the tenant switcher in the dashboard chrome — that
 * need to read the current tenant and trigger a switch.
 *
 * `setCurrentTenant` writes the cookie via the `/api/tenant` endpoint and
 * then forces a router refresh so RSCs re-read with the new company_id.
 */
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useTransition,
  type ReactNode,
} from "react";
import { useRouter } from "next/navigation";
import {
  findTenantBySlug,
  getDefaultTenant,
  listKnownTenantsSync,
  type Tenant,
} from "./tenants";

interface TenantContextValue {
  currentTenant: Tenant;
  knownTenants: Tenant[];
  setCurrentTenant: (slug: string) => Promise<void>;
  isPending: boolean;
}

const TenantContext = createContext<TenantContextValue | null>(null);

export function TenantProvider({
  initialSlug,
  children,
}: {
  initialSlug: string;
  children: ReactNode;
}) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const knownTenants = useMemo(() => listKnownTenantsSync(), []);

  const currentTenant = useMemo<Tenant>(
    () => findTenantBySlug(initialSlug) ?? getDefaultTenant(),
    [initialSlug]
  );

  const setCurrentTenant = useCallback(
    async (slug: string): Promise<void> => {
      // Persist via API route so the cookie is HttpOnly-friendly and shared
      // with server components on the next request.
      await fetch("/api/tenant", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ slug }),
      });
      // Refresh the router so RSCs re-render with the new tenant.
      startTransition(() => {
        router.refresh();
      });
    },
    [router]
  );

  const value = useMemo<TenantContextValue>(
    () => ({ currentTenant, knownTenants, setCurrentTenant, isPending }),
    [currentTenant, knownTenants, setCurrentTenant, isPending]
  );

  return (
    <TenantContext.Provider value={value}>{children}</TenantContext.Provider>
  );
}

export function useCurrentTenant(): TenantContextValue {
  const ctx = useContext(TenantContext);
  if (!ctx) {
    throw new Error("useCurrentTenant must be used inside TenantProvider");
  }
  return ctx;
}
