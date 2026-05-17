// primitives.jsx — WormBase six primitives
// Button · Input · Card · Receipt · Gauge · LedgerEntry
// Each exposes small visual vocabulary, consistent with tokens.

// ──────────────────────────────────────────────
// Button
// Variants: primary (ink-fill) · field (green) · ghost · danger (sepia)
// Sizes: sm · md · lg
// States: default · hover · pressed · disabled · loading
// ──────────────────────────────────────────────
function Button({ variant = 'primary', size = 'md', state = 'default', children, icon, mono }) {
  const pad = size === 'sm' ? '6px 12px' : size === 'lg' ? '12px 22px' : '9px 18px';
  const fs  = size === 'sm' ? 13 : size === 'lg' ? 17 : 15;

  const base = {
    display: 'inline-flex', alignItems: 'center', gap: 8,
    fontFamily: mono ? T.mono : T.serif,
    fontSize: fs, lineHeight: 1.1, fontWeight: mono ? 500 : 500,
    letterSpacing: mono ? 0.3 : 0,
    padding: pad, border: `1px solid ${T.ink}`, borderRadius: 0,
    cursor: 'pointer', transition: 'none', userSelect: 'none',
    textDecoration: 'none',
  };

  const palettes = {
    primary: { bg: T.ink,       fg: T.paper,     bd: T.ink,       hoverBg: '#000', pressBg: '#000', shadow: '2px 2px 0 ' + T.paperEdge },
    field:   { bg: T.green,     fg: T.paper,     bd: T.greenDeep, hoverBg: T.greenDeep, pressBg: T.greenDeep, shadow: '2px 2px 0 ' + T.paperEdge },
    ghost:   { bg: 'transparent', fg: T.ink,     bd: T.ink,       hoverBg: T.paperDeep,  pressBg: T.paperEdge, shadow: 'none' },
    danger:  { bg: T.paper,     fg: T.sepia,     bd: T.sepia,     hoverBg: T.sepiaSoft,  pressBg: T.sepiaSoft, shadow: 'none' },
  };
  const p = palettes[variant];

  let bg = p.bg, fg = p.fg, bd = p.bd, shadow = p.shadow, transform = 'none';
  if (state === 'hover')    { bg = p.hoverBg; }
  if (state === 'pressed')  { bg = p.pressBg; transform = 'translate(2px, 2px)'; shadow = 'none'; }
  if (state === 'disabled') { bg = T.paperDeep; fg = T.inkFaint; bd = T.paperEdge; shadow = 'none'; }

  return (
    <button disabled={state === 'disabled'} style={{
      ...base, background: bg, color: fg, borderColor: bd,
      boxShadow: shadow, transform,
      opacity: state === 'disabled' ? 1 : 1,
    }}>
      {state === 'loading' && <Spinner color={fg} />}
      {icon && state !== 'loading' && <span style={{ display: 'inline-flex' }}>{icon}</span>}
      <span>{children}</span>
    </button>
  );
}
function Spinner({ color }) {
  return (
    <span style={{
      display: 'inline-block', width: 12, height: 12,
      border: `1.5px solid ${color}`, borderRightColor: 'transparent',
      borderRadius: '50%', animation: 'wb-spin 0.9s linear infinite',
    }} />
  );
}
window.Button = Button;

// ──────────────────────────────────────────────
// Input
// Variants: default · with label · with suffix · mono (for SQL/hash)
// States: default · focus · filled · error · disabled
// ──────────────────────────────────────────────
function Input({ label, value, placeholder, state = 'default', prefix, suffix, hint, error, mono, size = 'md' }) {
  const pad = size === 'sm' ? '6px 10px' : '10px 12px';
  const fs  = size === 'sm' ? 13 : 15;

  let borderColor = T.paperEdge;
  let borderBottom = `1px solid ${T.ink}`;
  if (state === 'focus')    borderBottom = `2px solid ${T.green}`;
  if (state === 'error')    borderBottom = `2px solid ${T.sepia}`;
  if (state === 'disabled') { borderBottom = `1px solid ${T.paperEdge}`; }

  return (
    <div style={{ width: '100%' }}>
      {label && (
        <div style={{
          fontFamily: T.mono, fontSize: 10, letterSpacing: 0.8, textTransform: 'uppercase',
          color: state === 'error' ? T.sepia : T.inkMute, marginBottom: 6,
        }}>— {label}</div>
      )}
      <div style={{
        display: 'flex', alignItems: 'center',
        background: state === 'disabled' ? T.paperDeep : 'transparent',
        borderTop: `1px solid ${borderColor}`,
        borderLeft: `1px solid ${borderColor}`,
        borderRight: `1px solid ${borderColor}`,
        borderBottom: borderBottom,
        padding: pad, gap: 8,
      }}>
        {prefix && <span style={{ fontFamily: T.mono, fontSize: 12, color: T.inkMute }}>{prefix}</span>}
        <div style={{
          flex: 1, fontFamily: mono ? T.mono : T.serif, fontSize: fs,
          color: state === 'disabled' ? T.inkFaint : (value ? T.ink : T.inkFaint),
          lineHeight: 1.3,
        }}>{value || placeholder}</div>
        {suffix && <span style={{ fontFamily: T.mono, fontSize: 12, color: T.inkMute }}>{suffix}</span>}
      </div>
      {(hint || error) && (
        <div style={{
          marginTop: 6, fontFamily: T.serif, fontStyle: 'italic', fontSize: 12,
          color: state === 'error' ? T.sepia : T.inkMute,
        }}>{state === 'error' ? error : hint}</div>
      )}
    </div>
  );
}
window.Input = Input;

// ──────────────────────────────────────────────
// Card
// Variants: plate (default paper panel) · bound (double-rule heading) · specimen (image + caption)
// ──────────────────────────────────────────────
function Card({ variant = 'plate', kicker, title, index, children, footer }) {
  const headerRule = variant === 'bound'
    ? { borderBottom: `3px double ${T.ink}`, paddingBottom: 10, marginBottom: 14 }
    : { borderBottom: `1px solid ${T.ink}`,  paddingBottom: 8,  marginBottom: 12 };

  return (
    <div style={{
      background: T.paper,
      border: `1px solid ${T.paperEdge}`,
      padding: 20,
      boxShadow: variant === 'bound' ? '2px 2px 0 ' + T.paperEdge : 'none',
    }}>
      {(kicker || title) && (
        <div style={headerRule}>
          {kicker && (
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
              <Meta>{kicker}</Meta>
              {index && <Meta style={{ color: T.inkFaint }}>{index}</Meta>}
            </div>
          )}
          {title && (
            <div style={{ fontFamily: T.serif, fontSize: 20, fontWeight: 500, letterSpacing: -0.2, color: T.ink, lineHeight: 1.15 }}>
              {title}
            </div>
          )}
        </div>
      )}
      {children}
      {footer && (
        <div style={{ marginTop: 14, paddingTop: 10, borderTop: T.rule }}>
          {footer}
        </div>
      )}
    </div>
  );
}
window.Card = Card;

// ──────────────────────────────────────────────
// Receipt — hash + source + owner + classification
// Three densities:
//   footer   — compact mono strip, attached beneath data
//   expand   — collapsed summary, click to expand chain
//   margin   — annotation in the gutter (like a footnote)
// ──────────────────────────────────────────────
function ClassificationPip({ level = 'internal' }) {
  const cfg = {
    public:     { label: 'PUBLIC',     bg: T.paperDeep, fg: T.ink },
    internal:   { label: 'INTERNAL',   bg: T.greenSoft, fg: T.greenDeep },
    restricted: { label: 'RESTRICTED', bg: T.sepiaSoft, fg: T.sepia },
  }[level];
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      fontFamily: T.mono, fontSize: 9.5, letterSpacing: 0.9, fontWeight: 500,
      padding: '2px 6px', background: cfg.bg, color: cfg.fg,
      border: `1px solid currentColor`,
    }}>
      <span style={{ width: 4, height: 4, background: 'currentColor' }} />
      {cfg.label}
    </span>
  );
}
window.ClassificationPip = ClassificationPip;

function Receipt({ density = 'footer', hash, source, owner, classification = 'internal', timestamp, expanded }) {
  hash = hash || 'sha256:a7f3c9e4d2b10f82c6a5…9d47e2b1';
  source = source || 'snowflake://analytics.fct_orders';
  owner = owner || 'data-platform';
  timestamp = timestamp || '2026-04-22T09:14:07Z';

  if (density === 'footer') {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap',
        padding: '7px 10px', background: T.paper,
        borderTop: `1px dashed ${T.paperEdge}`,
        fontFamily: T.mono, fontSize: 10.5, color: T.inkMute, lineHeight: 1.2,
      }}>
        <span title="hash"><span style={{ color: T.inkFaint }}>⟐</span> {hash.slice(0, 22)}…</span>
        <span title="source"><span style={{ color: T.inkFaint }}>src</span> {source}</span>
        <span title="owner"><span style={{ color: T.inkFaint }}>by</span> {owner}</span>
        <span style={{ marginLeft: 'auto' }}><ClassificationPip level={classification} /></span>
      </div>
    );
  }

  if (density === 'margin') {
    return (
      <div style={{
        borderLeft: `1px solid ${T.inkMute}`, paddingLeft: 12,
        fontFamily: T.serif, fontStyle: 'italic', fontSize: 12.5,
        color: T.inkMute, lineHeight: 1.55, maxWidth: 220,
      }}>
        <div style={{ fontFamily: T.mono, fontStyle: 'normal', fontSize: 10, letterSpacing: 0.6, color: T.ink, marginBottom: 6 }}>
          — Provenance
        </div>
        <div>Proved from <span style={{ fontFamily: T.mono, fontStyle: 'normal', color: T.ink }}>{source}</span></div>
        <div style={{ marginTop: 4 }}>Owned by <span style={{ fontFamily: T.mono, fontStyle: 'normal', color: T.ink }}>{owner}</span></div>
        <div style={{ marginTop: 4 }}>Classified <ClassificationPip level={classification} /></div>
        <div style={{ marginTop: 8, fontFamily: T.mono, fontStyle: 'normal', fontSize: 9.5, color: T.inkFaint }}>
          {hash.slice(0, 20)}…
        </div>
      </div>
    );
  }

  // expand
  return (
    <div style={{ border: `1px solid ${T.paperEdge}`, background: T.paper }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px',
        fontFamily: T.mono, fontSize: 11, color: T.ink,
        borderBottom: expanded ? T.rule : 'none', cursor: 'pointer',
      }}>
        <span style={{ color: T.inkFaint }}>▸</span>
        <span>Receipt</span>
        <span style={{ color: T.inkFaint }}>{hash.slice(0, 18)}…</span>
        <span style={{ marginLeft: 'auto' }}><ClassificationPip level={classification} /></span>
      </div>
      {expanded && (
        <div style={{ padding: '10px 12px 12px', fontFamily: T.mono, fontSize: 11, lineHeight: 1.7 }}>
          <ReceiptRow k="hash"   v={hash} />
          <ReceiptRow k="source" v={source} />
          <ReceiptRow k="owner"  v={owner} />
          <ReceiptRow k="sealed" v={timestamp} />
        </div>
      )}
    </div>
  );
}
function ReceiptRow({ k, v }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '70px 1fr', gap: 10, padding: '2px 0', borderBottom: `1px dashed ${T.paperEdge}` }}>
      <span style={{ color: T.inkMute }}>— {k}</span>
      <span style={{ color: T.ink, wordBreak: 'break-all' }}>{v}</span>
    </div>
  );
}
window.Receipt = Receipt;

// ──────────────────────────────────────────────
// Gauge — breathing live data (±0.5% pulse every 3s)
// Two variants:
//   bar — horizontal scientific-instrument bar w/ tick marks
//   ring — circular ring with concentric threshold rings
// ──────────────────────────────────────────────
function useBreathe(initial, amplitude = 0.005, period = 3000) {
  const [v, setV] = React.useState(initial);
  React.useEffect(() => {
    let raf, t0 = performance.now();
    const tick = (t) => {
      const phase = ((t - t0) % period) / period;
      const pulse = Math.sin(phase * Math.PI * 2) * amplitude;
      setV(initial * (1 + pulse));
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [initial, amplitude, period]);
  return v;
}

function GaugeBar({ label, value, unit = '', min = 0, max = 100, thresholds = [], kicker }) {
  const live = useBreathe(value);
  const pct = Math.max(0, Math.min(1, (live - min) / (max - min)));
  const ticks = 10;

  return (
    <div style={{ fontFamily: T.serif }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
        <div>
          {kicker && <Meta style={{ marginBottom: 2 }}>{kicker}</Meta>}
          <div style={{ fontFamily: T.serif, fontSize: 16, fontStyle: 'italic', color: T.inkSoft }}>{label}</div>
        </div>
        <div style={{ fontFamily: T.mono, fontSize: 22, fontWeight: 500, color: T.ink, fontVariantNumeric: 'tabular-nums', letterSpacing: -0.3 }}>
          {live.toFixed(1)}<span style={{ fontSize: 12, color: T.inkMute, marginLeft: 4 }}>{unit}</span>
        </div>
      </div>

      {/* tick strip */}
      <div style={{ position: 'relative', height: 26, borderTop: `1px solid ${T.ink}`, borderBottom: `1px solid ${T.ink}` }}>
        {/* bar fill */}
        <div style={{
          position: 'absolute', left: 0, top: 0, bottom: 0,
          width: `${pct * 100}%`, background: T.green,
        }} />
        {/* threshold marks */}
        {thresholds.map((t) => (
          <div key={t} style={{
            position: 'absolute', top: -3, bottom: -3, left: `${((t - min) / (max - min)) * 100}%`,
            width: 1, background: T.ink,
          }} />
        ))}
        {/* ticks */}
        {Array.from({ length: ticks + 1 }).map((_, i) => (
          <div key={i} style={{
            position: 'absolute', top: 0, bottom: 0, left: `${(i / ticks) * 100}%`,
            width: 1, background: i % 5 === 0 ? T.ink : T.paperEdge,
            height: i % 5 === 0 ? '100%' : '40%',
          }} />
        ))}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4, fontFamily: T.mono, fontSize: 10, color: T.inkFaint, letterSpacing: 0.5 }}>
        <span>{min}</span>
        <span>{max}{unit}</span>
      </div>
    </div>
  );
}

function GaugeRing({ label, value, unit = '', min = 0, max = 100, size = 160, kicker, thresholds = [0.5, 0.8] }) {
  const live = useBreathe(value);
  const pct = Math.max(0, Math.min(1, (live - min) / (max - min)));
  const cx = size / 2, cy = size / 2;
  const r = size / 2 - 14;
  const C = 2 * Math.PI * r;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', fontFamily: T.serif, gap: 8 }}>
      {kicker && <Meta>{kicker}</Meta>}
      <div style={{ position: 'relative', width: size, height: size }}>
        <svg width={size} height={size} style={{ display: 'block' }}>
          {/* outer hairline */}
          <circle cx={cx} cy={cy} r={r + 6} fill="none" stroke={T.paperEdge} strokeWidth="1" />
          {/* threshold rings */}
          {thresholds.map((t, i) => (
            <circle key={i} cx={cx} cy={cy} r={r - 7 - i * 5} fill="none" stroke={T.paperEdge} strokeWidth="1" strokeDasharray="2 3" />
          ))}
          {/* track */}
          <circle cx={cx} cy={cy} r={r} fill="none" stroke={T.paperEdge} strokeWidth="6" />
          {/* value arc */}
          <circle cx={cx} cy={cy} r={r} fill="none"
            stroke={T.green} strokeWidth="6"
            strokeDasharray={`${C * pct} ${C}`}
            strokeLinecap="butt"
            transform={`rotate(-90 ${cx} ${cy})`} />
          {/* tick marks every 10% */}
          {Array.from({ length: 12 }).map((_, i) => {
            const a = (i / 12) * Math.PI * 2 - Math.PI / 2;
            const x1 = cx + Math.cos(a) * (r + 6);
            const y1 = cy + Math.sin(a) * (r + 6);
            const x2 = cx + Math.cos(a) * (r + 10);
            const y2 = cy + Math.sin(a) * (r + 10);
            return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke={T.ink} strokeWidth={i % 3 === 0 ? 1.3 : 0.8} />;
          })}
        </svg>
        <div style={{
          position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center',
        }}>
          <div style={{ fontFamily: T.mono, fontSize: 26, fontWeight: 500, color: T.ink, fontVariantNumeric: 'tabular-nums', letterSpacing: -0.5 }}>
            {live.toFixed(1)}
          </div>
          <div style={{ fontFamily: T.mono, fontSize: 10, color: T.inkMute, letterSpacing: 0.8, marginTop: -2 }}>{unit}</div>
        </div>
      </div>
      <div style={{ fontFamily: T.serif, fontStyle: 'italic', fontSize: 14, color: T.inkSoft, textAlign: 'center' }}>{label}</div>
    </div>
  );
}
window.GaugeBar = GaugeBar; window.GaugeRing = GaugeRing;

// ──────────────────────────────────────────────
// LedgerEntry — mono-styled data row
// Fields: id · op · subject · at · owner · classification
// States: default · pending (dashed) · verified (green rule) · contested (sepia)
// ──────────────────────────────────────────────
function LedgerEntry({ id, op, subject, at, owner, classification = 'internal', state = 'verified', hash, size = 'md' }) {
  const borderLeft = {
    verified:  `3px solid ${T.green}`,
    pending:   `3px dashed ${T.inkMute}`,
    contested: `3px solid ${T.sepia}`,
  }[state];
  const pad = size === 'sm' ? '8px 12px 8px 14px' : '12px 16px 12px 18px';

  return (
    <div style={{
      fontFamily: T.mono, fontSize: 11.5, lineHeight: 1.5,
      background: T.paper, borderBottom: T.rule, borderLeft,
      padding: pad, display: 'grid',
      gridTemplateColumns: '84px 70px 1fr 130px',
      gap: 12, alignItems: 'baseline', color: T.ink,
    }}>
      <span style={{ color: T.inkMute }}>{id}</span>
      <span style={{ color: op === 'DELETE' ? T.sepia : T.greenDeep, fontWeight: 500, letterSpacing: 0.5 }}>{op}</span>
      <span style={{ color: T.ink, wordBreak: 'break-all' }}>
        {subject}
        {hash && <span style={{ color: T.inkFaint, marginLeft: 8, fontSize: 10 }}>⟐ {hash}</span>}
      </span>
      <span style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, alignItems: 'center', color: T.inkMute }}>
        <span style={{ fontSize: 10 }}>{at}</span>
      </span>
      <span style={{ gridColumn: '1 / -1', display: 'flex', gap: 10, marginTop: 4, fontSize: 10, color: T.inkMute, alignItems: 'center' }}>
        <span>by {owner}</span>
        <span style={{ color: T.inkFaint }}>·</span>
        <ClassificationPip level={classification} />
        {state === 'pending' && <><span style={{ color: T.inkFaint }}>·</span><span style={{ color: T.inkMute, fontStyle: 'italic', fontFamily: T.serif }}>awaiting seal</span></>}
        {state === 'contested' && <><span style={{ color: T.inkFaint }}>·</span><span style={{ color: T.sepia, fontFamily: T.serif, fontStyle: 'italic' }}>hash mismatch</span></>}
      </span>
    </div>
  );
}
window.LedgerEntry = LedgerEntry;
