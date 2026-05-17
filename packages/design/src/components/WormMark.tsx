/**
 * WormMark — the WormBase monogram.
 *
 * A serpentine worm whose body forms the W, encircled by a double-ruled seal
 * with the WORMBASE wordmark arched along the top and segmentation ticks
 * down the worm's body.
 *
 * Faithful TS port of `apps/dashboard/design-exports/1b/brand-logo.jsx`. The
 * geometry is identical so the brand renders 1:1 with the design source.
 * Construction:
 *   - viewBox 300x300, center (150, 150)
 *   - Seal outer r=142, inner r=130
 *   - W anchors: peaks (xL=84, xR=216) at y=156, valleys at y=224, apex at
 *     (xC=150, y=184)
 *   - Tail: curled loop at (xTail=68, yTailCenter=216), r=9 — enters left peak
 *   - Head: raised tip at (xHead=238, yHead=138) with eye
 *   - Stroke 5px, linecap/linejoin round
 */

export type WormMarkMode = "solid" | "outline" | "negative";

export interface WormMarkProps {
  /** Pixel size (square). Defaults to 96. */
  size?: number;
  /** Mode: solid (paper fill, ink stroke), outline (transparent fill), negative (ink fill, paper stroke). */
  mode?: WormMarkMode;
  /** Ink color — primary stroke. Defaults to botanical green. */
  ink?: string;
  /** Paper color — fill. Defaults to paper token. */
  paper?: string;
  /** Show the arched WORMBASE wordmark + chord-rule. Defaults to true. */
  showArc?: boolean;
  /** Show segmentation ticks along the worm body. Defaults to true. */
  ticks?: boolean;
  /** Worm stroke width. Defaults to 5. */
  strokeWidth?: number;
  /** Optional aria-label. */
  title?: string;
}

function smooth(ax: number, ay: number, bx: number, by: number, t = 0.55): string {
  const dx = (bx - ax) * t;
  return `C ${ax + dx} ${ay} ${bx - dx} ${by} ${bx} ${by}`;
}

function buildWorm() {
  const xL = 84,
    xR = 216,
    xVL = 122,
    xVR = 178,
    xC = 150,
    yPeak = 156,
    yValley = 224,
    yApex = 184,
    xTail = 68,
    yTailCenter = 216,
    tailR = 9,
    xHead = 238,
    yHead = 138,
    t = 0.55;

  const cx = xTail,
    cy = yTailCenter,
    r = tailR;
  const parts: string[] = [];
  // Tail — closed curl
  parts.push(`M ${cx + r} ${cy}`);
  parts.push(`C ${cx + r} ${cy + r * 1.1}  ${cx - r} ${cy + r * 1.1}  ${cx - r} ${cy}`);
  parts.push(`C ${cx - r} ${cy - r * 1.1}  ${cx + r * 0.7} ${cy - r * 1.1}  ${cx + r * 0.7} ${cy - 1}`);
  parts.push(smooth(cx + r * 0.7, cy - 1, xL, yPeak, 0.5));
  // The W
  parts.push(smooth(xL, yPeak, xVL, yValley, t));
  parts.push(smooth(xVL, yValley, xC, yApex, t));
  parts.push(smooth(xC, yApex, xVR, yValley, t));
  parts.push(smooth(xVR, yValley, xR, yPeak, t));
  // Head — lifted up-right
  parts.push(smooth(xR, yPeak, xHead, yHead, 0.5));

  return {
    d: parts.join(" "),
    anchors: { xL, xR, xVL, xVR, xC, yPeak, yValley, yApex, xHead, yHead },
  };
}

function buildTicks(a: ReturnType<typeof buildWorm>["anchors"]): Array<[number, number, number]> {
  const { xL, xVL, xC, yPeak, yValley, yApex } = a;
  const left: Array<[number, number, number]> = [];
  for (const t of [0.22, 0.5, 0.78]) {
    const x = xL + (xVL - xL) * t;
    const y = yPeak + (yValley - yPeak) * (0.5 - 0.5 * Math.cos(Math.PI * t));
    left.push([x, y, 60 + t * 25]);
  }
  for (const t of [0.22, 0.5, 0.78]) {
    const x = xVL + (xC - xVL) * t;
    const y = yValley + (yApex - yValley) * (0.5 - 0.5 * Math.cos(Math.PI * t));
    left.push([x, y, 85 - t * 10]);
  }
  // Mirror across x=xC
  const right: Array<[number, number, number]> = left.map(([x, y, ang]) => [2 * xC - x, y, -ang]);
  return [...left, ...right];
}

const WORM = buildWorm();
const TICKS = buildTicks(WORM.anchors);

function Tick({
  cx,
  cy,
  angle,
  stroke,
  len = 3.2,
  w = 0.9,
}: {
  cx: number;
  cy: number;
  angle: number;
  stroke: string;
  len?: number;
  w?: number;
}) {
  return (
    <g
      transform={`translate(${cx} ${cy}) rotate(${angle})`}
      stroke={stroke}
      strokeWidth={w}
      strokeLinecap="round"
      opacity={0.85}
    >
      <line x1={-len} y1={0} x2={len} y2={0} />
      <line x1={0} y1={-len} x2={0} y2={len} />
    </g>
  );
}

export function WormMark({
  size = 96,
  mode = "solid",
  ink = "var(--wb-color-botanical-green, #2C5F3E)",
  paper = "var(--wb-color-paper, #FAF7F0)",
  showArc = true,
  ticks = true,
  strokeWidth = 5,
  title = "WormBase",
}: WormMarkProps) {
  const stroke = mode === "negative" ? paper : ink;
  const fill = mode === "negative" ? ink : mode === "outline" ? "none" : paper;
  const textColor = mode === "negative" ? paper : ink;
  const a = WORM.anchors;
  const arcId = `wb-arc-${size}`;

  return (
    <svg
      role="img"
      aria-label={title}
      width={size}
      height={size}
      viewBox="0 0 300 300"
      style={{ display: "block" }}
      data-wormmark
      data-mode={mode}
    >
      <defs>
        <path id={arcId} d="M 46 150 A 104 104 0 0 1 254 150" fill="none" />
      </defs>

      {/* Double-ruled seal */}
      <circle cx={150} cy={150} r={142} fill={fill} stroke={stroke} strokeWidth={3.2} />
      <circle cx={150} cy={150} r={130} fill="none" stroke={stroke} strokeWidth={1.2} />

      {/* Arched wordmark */}
      {showArc && (
        <text
          fill={textColor}
          fontFamily='"Source Serif 4", Georgia, serif'
          fontSize={22}
          fontWeight={500}
          letterSpacing={4.5}
          textAnchor="middle"
        >
          <textPath href={`#${arcId}`} startOffset="50%">
            WORMBASE
          </textPath>
        </text>
      )}

      {/* Chord-rule under wordmark */}
      {showArc && <line x1={56} y1={110} x2={244} y2={110} stroke={stroke} strokeWidth={1.2} />}

      {/* The worm itself */}
      <path
        d={WORM.d}
        fill="none"
        stroke={stroke}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {/* Head bulge + eye */}
      <circle cx={a.xHead} cy={a.yHead} r={strokeWidth * 0.9} fill={stroke} />
      <circle
        cx={a.xHead - 1}
        cy={a.yHead - 1.5}
        r={strokeWidth * 0.22}
        fill={mode === "outline" ? paper : fill}
      />

      {/* Segmentation ticks */}
      {ticks && (
        <g data-ticks>
          {TICKS.map(([cx, cy, ang], i) => (
            <Tick key={i} cx={cx} cy={cy} angle={ang} stroke={stroke} />
          ))}
        </g>
      )}
    </svg>
  );
}

WormMark.displayName = "WormMark";
