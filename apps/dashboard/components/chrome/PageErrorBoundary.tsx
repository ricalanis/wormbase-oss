"use client";

/**
 * PageErrorBoundary — catches render errors inside a tab and renders an
 * honest "we couldn't load this — try again" surface (W3.A14).
 *
 * Why every tab gets one:
 *   - A bare server-component render that throws (postgres unreachable, SSE
 *     fetch flake, projection mid-migration) blows up the whole route. The
 *     operator sees the Next.js dev-error overlay or, in production, a blank
 *     page. Both are demo seams disguised as engineering laziness.
 *   - The honest alternative: catch the error at the tab boundary, render an
 *     editorial empty-state-shaped panel that names the failure and offers a
 *     retry that re-mounts the children with a fresh key. The operator stays
 *     oriented; the rest of the app keeps working.
 *
 * Editorial chrome matches EmptyState — sepia dashed border, wb-mono eyebrow,
 * serif title, italic prose, square-cornered CTAs. The /trace deep link is
 * always offered so the operator can audit what fired before the failure.
 *
 * Form preservation: when `preserveFormState` is set, the boundary delays the
 * `key` reset by a microtask, giving any uncontrolled `<form>` children one
 * chance to read their `FormData` before the remount drops it. Most tabs
 * don't need this — only the few that wrap a form-submit error inside the
 * boundary.
 */
import { Component, type ErrorInfo, type ReactNode } from "react";
import Link from "next/link";

export interface PageErrorBoundaryProps {
  children: ReactNode;
  /**
   * Optional human-readable surface label. Used in the headline ("we couldn't
   * load <surface>"). Leave blank for the generic copy.
   */
  surface?: string;
  /**
   * `/trace` deep-link query (e.g. "?kind=error&surface=sources"). Surfaced
   * as a secondary CTA so the operator can audit the failure ledger entry.
   */
  traceQuery?: string;
  /**
   * If true, the retry button waits one microtask before forcing a remount,
   * giving uncontrolled forms one chance to read their input. Defaults to
   * false (immediate remount).
   */
  preserveFormState?: boolean;
  /** data-testid on the rendered error surface. */
  testId?: string;
}

interface State {
  error: Error | null;
  /** Bumped on retry to force a children remount. */
  retryKey: number;
}

export class PageErrorBoundary extends Component<
  PageErrorBoundaryProps,
  State
> {
  state: State = { error: null, retryKey: 0 };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Surface the error to the dev console but don't throw — the boundary's
    // job is to keep the rest of the app alive. In production the
    // server-side ledger has the real audit trail; the console line is a
    // dev convenience.
    if (typeof window !== "undefined" && console?.error) {
      console.error(
        "[PageErrorBoundary]",
        this.props.surface ?? "page",
        error,
        info.componentStack,
      );
    }
  }

  handleRetry = (): void => {
    if (this.props.preserveFormState) {
      // One microtask delay: lets any pending form-submit handler read its
      // FormData before the remount drops the uncontrolled inputs.
      queueMicrotask(() => {
        this.setState((s) => ({ error: null, retryKey: s.retryKey + 1 }));
      });
      return;
    }
    this.setState((s) => ({ error: null, retryKey: s.retryKey + 1 }));
  };

  render() {
    const { error } = this.state;
    const { children, surface, traceQuery, testId } = this.props;
    if (!error) {
      // The retryKey forces a fresh subtree on retry — necessary so a
      // server-component error doesn't replay the cached failure.
      return <div key={this.state.retryKey}>{children}</div>;
    }
    const tracePath = `/trace${traceQuery ?? ""}`;
    const headline = surface
      ? `We couldn't load ${surface}.`
      : "We couldn't load this surface.";
    const detail = error.message || "An unexpected render error fired.";
    return (
      <section
        data-testid={testId ?? "page-error-boundary"}
        role="alert"
        style={{
          border: "1px dashed var(--wb-color-sepia-warning, #b85a3e)",
          background: "var(--wb-color-paper)",
          padding: "32px 28px",
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-sepia-warning-deep, #8a3a25)",
          }}
        >
          something fired wrong
        </span>
        <h2
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 22,
            fontWeight: 500,
            letterSpacing: "-0.005em",
            color: "var(--wb-color-aged-ink)",
          }}
        >
          {headline}
        </h2>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            fontSize: 14,
            lineHeight: 1.55,
            color: "var(--wb-color-hash-gray)",
            maxWidth: 640,
          }}
        >
          The render threw mid-flight. Try again — the failure is captured in
          the ledger, so nothing was silently lost.
        </p>
        <pre
          data-testid="page-error-detail"
          style={{
            margin: 0,
            padding: "8px 10px",
            border: "1px solid var(--wb-color-paper-edge)",
            background: "var(--wb-color-paper-soft, #f7f3ea)",
            fontFamily: "var(--wb-font-mono)",
            fontSize: 11,
            color: "var(--wb-color-hash-gray)",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          {detail}
        </pre>
        <div
          style={{
            display: "flex",
            gap: 10,
            marginTop: 4,
            alignItems: "baseline",
            flexWrap: "wrap",
          }}
        >
          <button
            type="button"
            data-testid="page-error-retry"
            onClick={this.handleRetry}
            style={{
              display: "inline-block",
              padding: "8px 14px",
              borderRadius: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 13,
              border: "1px solid var(--wb-color-botanical-green-deep)",
              background: "var(--wb-color-botanical-green)",
              color: "var(--wb-color-paper)",
              cursor: "pointer",
            }}
          >
            Try again
          </button>
          <Link
            href={tracePath}
            data-testid="page-error-trace-link"
            style={{
              display: "inline-block",
              padding: "8px 14px",
              borderRadius: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 13,
              textDecoration: "none",
              border: "1px solid var(--wb-color-aged-ink)",
              background: "transparent",
              color: "var(--wb-color-aged-ink)",
            }}
          >
            Open /trace
          </Link>
        </div>
      </section>
    );
  }
}
