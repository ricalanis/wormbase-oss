import { WormMark } from "./WormMark";
import { Wordmark } from "./Wordmark";

/**
 * Lockup — combination mark of WormMark + Wordmark.
 *
 * Two orientations:
 *   - horizontal — monogram on the left, separator rule, wordmark + receipt
 *     tagline on the right (used in header chrome).
 *   - stacked — monogram above, mono receipt tagline below (used on splash /
 *     onboarding masthead).
 *
 * The receipt tagline ("INSTITUTIONAL DATA AGENT") is mono — this is the
 * brand's own embedded receipt. Keeping it on the lockup means every place
 * the brand appears, the *idea* of "this is a ledger product" travels with it.
 */

export type LockupOrientation = "horizontal" | "stacked";

export interface LockupProps {
  orientation?: LockupOrientation;
  /** Multiplier on all internal sizes. Defaults to 1. */
  scale?: number;
  /** Ink color (worm + rule). Defaults to botanical green. */
  color?: string;
  /** Paper color (seal fill). Defaults to paper. */
  paper?: string;
  /** Show the receipt tagline. Defaults to true. */
  withReceipt?: boolean;
  /** Override the receipt tagline copy. */
  tagline?: string;
}

export function Lockup({
  orientation = "horizontal",
  scale = 1,
  color = "var(--wb-color-botanical-green, #2C5F3E)",
  paper = "var(--wb-color-paper, #FAF7F0)",
  withReceipt = true,
  tagline,
}: LockupProps) {
  const s = scale;
  const taglineDefault =
    orientation === "stacked"
      ? "INSTITUTIONAL DATA AGENT"
      : "INSTITUTIONAL DATA AGENT · VOL. I";
  const tag = tagline ?? taglineDefault;

  if (orientation === "stacked") {
    return (
      <div
        data-lockup
        data-orientation="stacked"
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 14 * s,
        }}
      >
        <WormMark size={180 * s} ink={color} paper={paper} showArc />
        {withReceipt ? (
          <span
            className="wb-mono"
            style={{
              fontSize: 9 * s,
              letterSpacing: 1.2,
              color: "var(--wb-color-hash-gray, #7A7A7A)",
            }}
          >
            {tag}
          </span>
        ) : null}
      </div>
    );
  }

  return (
    <div
      data-lockup
      data-orientation="horizontal"
      style={{ display: "inline-flex", alignItems: "center", gap: 18 * s }}
    >
      <WormMark size={120 * s} ink={color} paper={paper} showArc />
      <span
        aria-hidden="true"
        style={{
          width: 1,
          height: 90 * s,
          background: color,
          opacity: 0.4,
        }}
      />
      <span style={{ display: "inline-flex", flexDirection: "column", gap: 4 * s }}>
        <Wordmark height={28 * s} color={color} rule={false} />
        {withReceipt ? (
          <span
            className="wb-mono"
            style={{
              fontSize: 9 * s,
              letterSpacing: 1.2,
              color: "var(--wb-color-hash-gray, #7A7A7A)",
            }}
          >
            {tag}
          </span>
        ) : null}
      </span>
    </div>
  );
}

Lockup.displayName = "Lockup";
