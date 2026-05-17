/**
 * PageSuspenseBoundary — wraps a tab's primary render in `<Suspense>` with the
 * editorial PageSkeleton fallback (W3.A14).
 *
 * Why a wrapper instead of inlining `<Suspense>` per tab:
 *   1. A `fallback={null}` Suspense is a silent loading seam — the panel
 *      renders empty for a fraction of a second and the operator can't tell
 *      whether they're seeing "loading" or "no data". The N2 gate forbids
 *      this. Centralizing the boundary makes the rule enforceable.
 *   2. The skeleton chrome should match the field-notebook visual language;
 *      inlined `<Suspense>` calls drift over time. One component, one truth.
 *   3. Sister agents touching individual tabs can wrap-and-forget; this
 *      component owns the editorial defaults.
 *
 * Pairs with PageErrorBoundary — every tab uses both, additively, around the
 * existing primary render. The ordering used in tabs is:
 *
 *     <PageErrorBoundary>
 *       <PageSuspenseBoundary>
 *         {existing tab render}
 *       </PageSuspenseBoundary>
 *     </PageErrorBoundary>
 *
 * The error boundary is outermost so a render error inside `<Suspense>` is
 * caught and surfaced honestly.
 */
import { Suspense, type ReactNode } from "react";
import { PageSkeleton, type PageSkeletonProps } from "./PageSkeleton";

export interface PageSuspenseBoundaryProps {
  children: ReactNode;
  /**
   * Override the loading copy. Leave unset to use the chrome default
   * ("loading" / "Reading the ledger…").
   */
  fallback?: ReactNode;
  /** Forwarded to the skeleton when no custom fallback is given. */
  skeletonProps?: PageSkeletonProps;
}

export function PageSuspenseBoundary({
  children,
  fallback,
  skeletonProps,
}: PageSuspenseBoundaryProps) {
  return (
    <Suspense fallback={fallback ?? <PageSkeleton {...skeletonProps} />}>
      {children}
    </Suspense>
  );
}
