/**
 * Wordmark — straight WORMBASE wordmark for lockups.
 *
 * Serif weight 500, letter-spacing tied to height (10%). Optional 1px
 * underline rule. Use stand-alone in headers, or composed via <Lockup/>.
 */

export interface WordmarkProps {
  /** Height in px — sets fontSize directly. Defaults to 24. */
  height?: number;
  /** Color (CSS color or var()). Defaults to aged ink. */
  color?: string;
  /** Optional underline rule (1px, color matches text). Defaults to true. */
  rule?: boolean;
  /** Override family. */
  family?: string;
  /** Optional aria-label. Defaults to "WormBase". */
  title?: string;
}

export function Wordmark({
  height = 24,
  color = "var(--wb-color-aged-ink, #2A2A2A)",
  rule = true,
  family,
  title = "WormBase",
}: WordmarkProps) {
  const fam =
    family ||
    'var(--wb-font-serif, "Source Serif 4", "Source Serif Pro", Georgia, serif)';
  return (
    <span
      role="img"
      aria-label={title}
      data-wordmark
      style={{ display: "inline-flex", flexDirection: "column", gap: 4, color }}
    >
      <span
        style={{
          fontFamily: fam,
          fontWeight: 500,
          fontSize: height,
          letterSpacing: height * 0.1,
          lineHeight: 1,
        }}
      >
        WORMBASE
      </span>
      {rule ? (
        <span
          aria-hidden="true"
          style={{
            display: "block",
            height: 1,
            background: color,
            width: "100%",
          }}
        />
      ) : null}
    </span>
  );
}

Wordmark.displayName = "Wordmark";
