import { type HTMLAttributes, forwardRef } from "react";

export interface ReceiptProps extends HTMLAttributes<HTMLDivElement> {
  /** 6–12 char hex hash (ledger entry identifier). */
  hash: string;
  /** The resource / table / model that sourced the answer. */
  source: string;
  /** Person (role or id) who owns the source. */
  owner: string;
  /** Classification: e.g. "internal", "pii-masked", "public". */
  classification: string;
  /** Optional timestamp (ISO, rendered right-aligned). */
  timestamp?: string;
  /** When compact, the receipt renders as a single inline line. */
  compact?: boolean;
}

/**
 * Field Notebook Receipt — the *signature* primitive.
 *
 * Every worm answer carries one. Mono font marks "this is ledger."
 * Hash = the anchor; source + owner + classification = the provenance.
 * Dense, thin rules, no color decoration — information is the aesthetic.
 */
export const Receipt = forwardRef<HTMLDivElement, ReceiptProps>(
  (
    { hash, source, owner, classification, timestamp, compact = false, style, ...rest },
    ref
  ) => {
    const sev = severityForClassification(classification);
    if (compact) {
      return (
        <div
          ref={ref}
          {...rest}
          className="wb-mono"
          data-receipt
          data-classification={classification}
          data-sev={sev}
          data-full-hash={hash}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "10px",
            fontSize: "var(--wb-text-xs)",
            color: "var(--wb-color-hash-gray)",
            borderTop: "1px solid var(--wb-color-rule-line)",
            borderBottom: "1px solid var(--wb-color-rule-line)",
            padding: "4px 0",
            letterSpacing: "0.02em",
            ...style,
          }}
        >
          <span aria-label="hash" style={{ color: "var(--wb-color-aged-ink)" }}>
            #{hash}
          </span>
          <span aria-hidden="true">·</span>
          <span aria-label="source">{source}</span>
          <span aria-hidden="true">·</span>
          <span aria-label="owner">@{owner}</span>
          <span aria-hidden="true">·</span>
          <span aria-label="classification">{classification}</span>
          {timestamp ? (
            <>
              <span aria-hidden="true">·</span>
              <span aria-label="timestamp">{timestamp}</span>
            </>
          ) : null}
        </div>
      );
    }

    return (
      <div
        ref={ref}
        {...rest}
        className="wb-mono"
        data-receipt
        data-classification={classification}
        data-sev={sev}
        data-full-hash={hash}
        style={{
          display: "grid",
          gridTemplateColumns: "80px 1fr",
          columnGap: "14px",
          rowGap: "4px",
          fontSize: "var(--wb-text-xs)",
          color: "var(--wb-color-aged-ink)",
          borderTop: "1px solid var(--wb-color-aged-ink)",
          borderBottom: "1px solid var(--wb-color-rule-line)",
          padding: "10px 0 12px",
          ...style,
        }}
      >
        <ReceiptRow ariaLabel="hash" label="hash" value={`#${hash}`} emphasize />
        <ReceiptRow ariaLabel="source" label="source" value={source} />
        <ReceiptRow ariaLabel="owner" label="owner" value={`@${owner}`} />
        <ReceiptRow
          ariaLabel="classification"
          label="class"
          value={classification}
        />
        {timestamp ? (
          <ReceiptRow ariaLabel="timestamp" label="ts" value={timestamp} />
        ) : null}
      </div>
    );
  }
);
Receipt.displayName = "Receipt";

/**
 * severityForClassification — maps a classification token into a visual severity
 * tier consumed by data-sev. The classification overlay (Task 4.12) reads
 * data-sev to render the colored band.
 */
function severityForClassification(c: string): "warn" | "ok" | "neutral" {
  const lc = c.toLowerCase();
  if (lc === "pii" || lc.startsWith("pii") || lc === "restricted") return "warn";
  if (lc === "public") return "ok";
  return "neutral";
}

function ReceiptRow({
  label,
  value,
  ariaLabel,
  emphasize = false,
}: {
  label: string;
  value: string;
  ariaLabel: string;
  emphasize?: boolean;
}) {
  return (
    <>
      <span
        style={{
          color: "var(--wb-color-hash-gray)",
          textTransform: "uppercase",
          letterSpacing: "0.1em",
          fontSize: "10px",
          alignSelf: "baseline",
          paddingTop: "2px",
        }}
      >
        {label}
      </span>
      <span
        aria-label={ariaLabel}
        style={{
          color: emphasize
            ? "var(--wb-color-aged-ink)"
            : "var(--wb-color-aged-ink-soft)",
          fontWeight: emphasize ? 600 : 400,
          wordBreak: "break-all",
        }}
      >
        {value}
      </span>
    </>
  );
}
