"use client";

/**
 * Route-group error boundary — Next.js automatically catches a render error
 * thrown inside the matched server component and renders this client surface
 * (W3.A14).
 *
 * We render the same editorial chrome the inline PageErrorBoundary uses, with
 * a real "try again" button (via Next.js's reset() callback) and a deep link
 * to /trace so the operator can audit the failure.
 *
 * Note: this is the route-group fallback. Individual tabs may also wrap their
 * primary render in `<PageErrorBoundary>` for finer-grained recovery (e.g.
 * forms that want to preserve input on error). When both fire, the inline
 * boundary handles the throw first; this file only catches errors that
 * escape the inline boundary or originate above it.
 */
import Link from "next/link";
import { useEffect } from "react";

export default function AppGroupError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Surface the digest into the dev console — it correlates with the
    // server-side ledger entry so the operator can find the matching
    // /trace row by digest.
    if (typeof window !== "undefined" && console?.error) {
      console.error("[app-group/error]", error.digest, error);
    }
  }, [error]);

  const detail = error.message || "An unexpected render error fired.";
  const tracePath = error.digest
    ? `/trace?digest=${encodeURIComponent(error.digest)}`
    : "/trace";

  return (
    <section
      data-testid="app-group-error"
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
        We couldn&apos;t load this page.
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
        data-testid="app-group-error-detail"
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
        {error.digest ? `\n\ndigest: ${error.digest}` : ""}
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
          data-testid="app-group-error-retry"
          onClick={() => reset()}
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
          data-testid="app-group-error-trace-link"
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
