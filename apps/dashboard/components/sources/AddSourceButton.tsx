/**
 * AddSourceButton — header CTA on /sources.
 *
 * W2.A5 of `docs/superpowers/plans/2026-04-28-production-hardening.md`.
 *
 * Routes to /sources/new where the connector picker renders the
 * production / preview / coming_soon catalog from worm-core. Server
 * component — uses Next's `<Link>` for prefetching.
 */
import Link from "next/link";

export function AddSourceButton({
  testId = "add-source-button",
}: {
  testId?: string;
}) {
  return (
    <Link
      href="/sources/new"
      data-testid={testId}
      className="wb-mono"
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        fontSize: 11,
        letterSpacing: "0.08em",
        textTransform: "uppercase",
        padding: "8px 14px",
        border: "1px solid var(--wb-color-aged-ink)",
        background: "var(--wb-color-botanical-green-soft)",
        color: "var(--wb-color-aged-ink)",
        textDecoration: "none",
        borderRadius: 0,
        cursor: "pointer",
        whiteSpace: "nowrap",
      }}
    >
      <span aria-hidden style={{ fontSize: 13, lineHeight: 1 }}>
        +
      </span>
      Add source
    </Link>
  );
}
