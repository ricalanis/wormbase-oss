// brand-logo.jsx — WormBase logo, final
// A serpentine worm whose body IS the W. Symmetric. Sober.
// Constructed on a grid:
//   Seal outer r=142, inner r=128 (viewBox 300×300, center 150,150)
//   W anchors: outer-peaks (72,148) & (228,148); valleys (118,230) & (182,230);
//              center apex (150,182) — classic W where the center peak is lower
//   Tail: curled loop at (54,222), r=10 — enters the left peak from below
//   Head: raised tip at (252,128) with eye — exits the right peak up-and-right
//   Stroke 5px, linecap/linejoin round
//   Wordmark arched along top of seal, with a chord-rule beneath

// Cubic bezier between two anchors with HORIZONTAL tangents — rounds peaks smoothly.
function _smooth(ax, ay, bx, by, t = 0.55) {
  const dx = (bx - ax) * t;
  return `C ${ax + dx} ${ay} ${bx - dx} ${by} ${bx} ${by}`;
}

function _buildWorm(opts = {}) {
  const {
    // Pulled inward ~16px from seal ring for breathing room.
    xL = 84, xR = 216,
    xVL = 122, xVR = 178,
    xC = 150,
    yPeak = 156, yValley = 224, yApex = 184,
    xTail = 68, yTailCenter = 216, tailR = 9,
    xHead = 238, yHead = 138,
    t = 0.55,
  } = opts;

  const parts = [];
  // Tail — closed curl
  const cx = xTail, cy = yTailCenter, r = tailR;
  parts.push(`M ${cx + r} ${cy}`);
  parts.push(`C ${cx + r} ${cy + r * 1.1}  ${cx - r} ${cy + r * 1.1}  ${cx - r} ${cy}`);
  parts.push(`C ${cx - r} ${cy - r * 1.1}  ${cx + r * 0.7} ${cy - r * 1.1}  ${cx + r * 0.7} ${cy - 1}`);
  parts.push(_smooth(cx + r * 0.7, cy - 1, xL, yPeak, 0.5));
  // The W
  parts.push(_smooth(xL, yPeak, xVL, yValley, t));
  parts.push(_smooth(xVL, yValley, xC, yApex, t));
  parts.push(_smooth(xC, yApex, xVR, yValley, t));
  parts.push(_smooth(xVR, yValley, xR, yPeak, t));
  // Head — lifted up-right
  parts.push(_smooth(xR, yPeak, xHead, yHead, 0.5));

  return { d: parts.join(' '), anchors: { xL, xR, xVL, xVR, xC, yPeak, yValley, yApex, xHead, yHead } };
}

// Symmetric segmentation ticks (left half + mirror)
function _buildTicks(a) {
  const { xL, xR, xVL, xVR, xC, yPeak, yValley, yApex } = a;
  const left = [];
  // Left downstroke sample points
  for (const t of [0.22, 0.5, 0.78]) {
    const x = xL + (xVL - xL) * t;
    const y = yPeak + (yValley - yPeak) * (0.5 - 0.5 * Math.cos(Math.PI * t));
    left.push([x, y, 60 + t * 25]);
  }
  // Left upstroke sample points
  for (const t of [0.22, 0.5, 0.78]) {
    const x = xVL + (xC - xVL) * t;
    const y = yValley + (yApex - yValley) * (0.5 - 0.5 * Math.cos(Math.PI * t));
    left.push([x, y, 85 - t * 10]);
  }
  // Mirror across x=xC
  const right = left.map(([x, y, ang]) => [2 * xC - x, y, -ang]);
  return [...left, ...right];
}

const _WORM = _buildWorm();
const _TICKS = _buildTicks(_WORM.anchors);

function _Tick({ cx, cy, angle, stroke, len = 3.2, w = 0.9 }) {
  return (
    <g transform={`translate(${cx} ${cy}) rotate(${angle})`} stroke={stroke} strokeWidth={w} strokeLinecap="round" opacity="0.85">
      <line x1={-len} y1="0" x2={len} y2="0" />
      <line x1="0" y1={-len} x2="0" y2={len} />
    </g>
  );
}

function WMonogram({
  size = 260,
  mode = 'solid',      // solid | outline | negative
  ink = '#2C5F3E',
  paper = '#FAF7F0',
  showArc = true,      // show arched WORMBASE wordmark
  family,
  ticks = true,
  strokeWidth = 5,
}) {
  const fam = family || '"Source Serif 4", Georgia, serif';
  const stroke = mode === 'negative' ? paper : ink;
  const fill = mode === 'negative' ? ink : paper;
  const textColor = mode === 'negative' ? paper : ink;
  const a = _WORM.anchors;

  return (
    <svg width={size} height={size} viewBox="0 0 300 300" style={{ display: 'block' }}>
      <defs>
        <path id={`wb-arc-${size}`} d="M 46 150 A 104 104 0 0 1 254 150" fill="none" />
      </defs>

      {/* Double-ruled seal */}
      <circle cx="150" cy="150" r="142" fill={fill} stroke={stroke} strokeWidth="3.2" />
      <circle cx="150" cy="150" r="130" fill="none" stroke={stroke} strokeWidth="1.2" />

      {/* Arched wordmark */}
      {showArc && (
        <text fill={textColor} fontFamily={fam} fontSize="22" fontWeight="500"
          letterSpacing="4.5" textAnchor="middle">
          <textPath href={`#wb-arc-${size}`} startOffset="50%">WORMBASE</textPath>
        </text>
      )}

      {/* Chord-rule under wordmark */}
      {showArc && (
        <line x1="56" y1="110" x2="244" y2="110" stroke={stroke} strokeWidth="1.2" />
      )}

      {/* The worm */}
      <path d={_WORM.d} fill="none" stroke={stroke} strokeWidth={strokeWidth}
        strokeLinecap="round" strokeLinejoin="round" />

      {/* Head bulge + eye */}
      <circle cx={a.xHead} cy={a.yHead} r={strokeWidth * 0.9} fill={stroke} />
      <circle cx={a.xHead - 1} cy={a.yHead - 1.5} r={strokeWidth * 0.22} fill={fill} />

      {/* Segmentation ticks */}
      {ticks && (
        <g>
          {_TICKS.map(([cx, cy, ang], i) => (
            <_Tick key={i} cx={cx} cy={cy} angle={ang} stroke={stroke} />
          ))}
        </g>
      )}
    </svg>
  );
}
window.WMonogram = WMonogram;

// Wordmark — straight, for lockups
function Wordmark({ height = 32, color = '#2A2A2A', family, rule = true }) {
  const fam = family || '"Source Serif 4", Georgia, serif';
  return (
    <div style={{ display: 'inline-flex', flexDirection: 'column', gap: 4, color }}>
      <div style={{
        fontFamily: fam, fontWeight: 500, fontSize: height,
        letterSpacing: height * 0.1, lineHeight: 1,
      }}>WORMBASE</div>
      {rule && <div style={{ height: 1, background: color, width: '100%' }} />}
    </div>
  );
}
window.Wordmark = Wordmark;

// Combination lockup
function Lockup({ orientation = 'horizontal', scale = 1, color = '#2C5F3E', paper = '#FAF7F0', withReceipt = true }) {
  const s = scale;
  if (orientation === 'stacked') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 14 * s }}>
        <WMonogram size={180 * s} ink={color} paper={paper} showArc={true} />
        {withReceipt && (
          <div style={{ fontFamily: '"JetBrains Mono", monospace', fontSize: 9 * s, letterSpacing: 1.2, color: '#7A7A7A' }}>
            INSTITUTIONAL DATA AGENT
          </div>
        )}
      </div>
    );
  }
  return (
    <div style={{ display: 'inline-flex', alignItems: 'center', gap: 18 * s }}>
      <WMonogram size={120 * s} ink={color} paper={paper} showArc={true} />
      <div style={{ width: 1, height: 90 * s, background: color, opacity: 0.4 }} />
      <div>
        <Wordmark height={28 * s} color={color} rule={false} />
        {withReceipt && (
          <div style={{
            fontFamily: '"JetBrains Mono", monospace', fontSize: 9 * s, letterSpacing: 1.2,
            color: '#7A7A7A', marginTop: 4 * s,
          }}>
            INSTITUTIONAL DATA AGENT · VOL. I
          </div>
        )}
      </div>
    </div>
  );
}
window.Lockup = Lockup;
