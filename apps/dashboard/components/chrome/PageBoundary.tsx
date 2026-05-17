/**
 * PageBoundary — combines PageErrorBoundary + PageSuspenseBoundary into one
 * wrapper so a tab page can opt-in with a single component (W3.A14).
 *
 * Usage:
 *
 *     return (
 *       <PageBoundary surface="sources">
 *         <header>…</header>
 *         <SourceListInteractive rows={rows} />
 *       </PageBoundary>
 *     );
 *
 * Equivalent to writing both manually:
 *
 *     <PageErrorBoundary surface="sources">
 *       <PageSuspenseBoundary>
 *         …
 *       </PageSuspenseBoundary>
 *     </PageErrorBoundary>
 *
 * The error boundary is outermost so a render error inside Suspense gets
 * caught and surfaced as the editorial "we couldn't load this" panel rather
 * than escaping into the Next.js dev overlay or a blank white pane in
 * production.
 */
import type { ReactNode } from "react";
import { PageErrorBoundary } from "./PageErrorBoundary";
import {
  PageSuspenseBoundary,
  type PageSuspenseBoundaryProps,
} from "./PageSuspenseBoundary";

export interface PageBoundaryProps {
  children: ReactNode;
  /** Surface label for the error headline ("we couldn't load <surface>"). */
  surface?: string;
  /** Deep-link query forwarded to the error boundary's /trace CTA. */
  traceQuery?: string;
  /** Forwarded to the suspense boundary; controls the loading copy. */
  skeletonProps?: PageSuspenseBoundaryProps["skeletonProps"];
  /** Custom Suspense fallback; overrides the editorial PageSkeleton default. */
  fallback?: PageSuspenseBoundaryProps["fallback"];
  /** If true, retry preserves uncontrolled form state. Defaults to false. */
  preserveFormState?: boolean;
  /** data-testid forwarded to the rendered error surface (when it fires). */
  errorTestId?: string;
}

export function PageBoundary({
  children,
  surface,
  traceQuery,
  skeletonProps,
  fallback,
  preserveFormState,
  errorTestId,
}: PageBoundaryProps) {
  return (
    <PageErrorBoundary
      surface={surface}
      traceQuery={traceQuery}
      preserveFormState={preserveFormState}
      testId={errorTestId}
    >
      <PageSuspenseBoundary
        fallback={fallback}
        skeletonProps={skeletonProps}
      >
        {children}
      </PageSuspenseBoundary>
    </PageErrorBoundary>
  );
}
