// brand-plates.jsx — all brand-book plates in one file

const BK = {
  paper: '#FAF7F0', paperDeep: '#F2ECDE', paperEdge: '#E8E0CC',
  ink: '#2A2A2A', inkSoft: '#4A4842', inkMute: '#7A7A7A', inkFaint: '#A8A49A',
  green: '#2C5F3E', greenDeep: '#1F4A2E', greenSoft: '#E6EDE4',
  sepia: '#B8603C', sepiaSoft: '#F3E4DA',
  serif: 'ui-serif, "Source Serif 4", Georgia, serif',
  mono: '"JetBrains Mono", ui-monospace, Menlo, monospace',
};
window.BK = BK;

// ─── plate shell ───
function Plate({ children, n, chapter, title, paper = BK.paper }) {
  return (
    <div style={{
      position: 'absolute', inset: 0, background: paper, color: BK.ink,
      fontFamily: BK.serif, padding: '60px 88px 52px', boxSizing: 'border-box',
      display: 'flex', flexDirection: 'column',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <span style={{ fontFamily: BK.mono, fontSize: 12, letterSpacing: 1.6, color: BK.inkMute, textTransform: 'uppercase' }}>
          — {chapter}
        </span>
        <span style={{ fontFamily: BK.mono, fontSize: 12, letterSpacing: 1.6, color: BK.inkFaint }}>
          PL. {n}
        </span>
      </div>
      <div style={{ borderTop: `1px solid ${BK.ink}`, margin: '10px 0 0' }} />
      {title && (
        <h1 style={{ fontFamily: BK.serif, fontWeight: 400, fontSize: 52, lineHeight: 1.02, letterSpacing: -0.8, margin: '16px 0 28px', color: BK.ink }}>
          {title}
        </h1>
      )}
      <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>{children}</div>
      <div style={{ borderTop: `1px solid ${BK.paperEdge}`, paddingTop: 10, marginTop: 20, display: 'flex', justifyContent: 'space-between', fontFamily: BK.mono, fontSize: 10, color: BK.inkFaint, letterSpacing: 1 }}>
        <span>WORMBASE · BRAND BOOK · VOL. I</span>
        <span>PRIVATE · FOR INTERNAL REVIEW</span>
      </div>
    </div>
  );
}
const Meta = ({ children, style }) => (
  <div style={{ fontFamily: BK.mono, fontSize: 10, letterSpacing: 1, textTransform: 'uppercase', color: BK.inkMute, ...style }}>{children}</div>
);
const Italic = ({ children, style }) => (
  <div style={{ fontFamily: BK.serif, fontStyle: 'italic', fontSize: 16, lineHeight: 1.55, color: BK.inkSoft, ...style }}>{children}</div>
);

// ─── 00 COVER ───
function CoverPlate() {
  return (
    <div style={{
      position: 'absolute', inset: 0, background: BK.paper, color: BK.ink,
      fontFamily: BK.serif, padding: 88, boxSizing: 'border-box',
      display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: 60,
    }}>
      <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
        <div>
          <Meta>— VOLUME I · FIELD NOTEBOOK</Meta>
          <div style={{ borderTop: `3px double ${BK.ink}`, margin: '12px 0 40px' }} />
          <Italic style={{ fontSize: 18, color: BK.inkSoft }}>A treatise on the identity of</Italic>
          <h1 style={{ fontFamily: BK.serif, fontWeight: 400, fontSize: 128, lineHeight: 0.92, letterSpacing: -3, margin: '20px 0 6px' }}>
            WORMBASE
          </h1>
          <div style={{ fontFamily: BK.serif, fontStyle: 'italic', fontSize: 28, color: BK.green, letterSpacing: -0.4 }}>
            institutional data agent
          </div>
          <div style={{ marginTop: 44, maxWidth: 500, fontFamily: BK.serif, fontSize: 18, color: BK.inkSoft, lineHeight: 1.55 }}>
            Comprising the mark, the wordmark and their lockups; the color &amp; letterforms;
            the voice at rest and at work; the motion of live data; and the rules of their use &amp; misuse.
          </div>
        </div>
        <div style={{ fontFamily: BK.mono, fontSize: 11, letterSpacing: 1, color: BK.inkMute, display: 'flex', gap: 32 }}>
          <span>Edition I · April 2026</span>
          <span>Pl. 00 – XV</span>
          <span>Private circulation</span>
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', position: 'relative' }}>
        <div style={{ background: BK.paperDeep, padding: 28, boxShadow: '4px 4px 0 ' + BK.paperEdge, border: `1px solid ${BK.paperEdge}` }}>
          <div style={{ background: BK.paper, padding: 32, border: `1px solid ${BK.ink}` }}>
            <WMonogram size={260} ink={BK.ink} paper={BK.paper} />
          </div>
          <div style={{ marginTop: 16, textAlign: 'center', fontFamily: BK.serif, fontStyle: 'italic', fontSize: 13, color: BK.inkMute }}>
            Fig. I · <span style={{ fontFamily: BK.mono, fontStyle: 'normal', fontSize: 10, letterSpacing: 0.8 }}>THE SEAL</span>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── 01 CONTENTS ───
function ContentsPlate() {
  const rows = [
    ['I',    'The Seal',              'Monogram construction'],
    ['II',   'The Wordmark',          'Letterforms, tracking, rule'],
    ['III',  'Lockups',               'Horizontal, stacked, isolated'],
    ['IV',   'Clear Space & Scale',   'Invariants'],
    ['V',    'Misuse',                'What never to do'],
    ['VI',   'Color on Color',        'Ground + mark pairings'],
    ['VII',  'Palette',               'Paper, ink, botanical'],
    ['VIII', 'Letterforms',           'Serif voice · semantic mono'],
    ['IX',   'Voice & Tone',          'How WormBase speaks'],
    ['X',    'Imagery',               'Plates, not photos'],
    ['XI',   'Motion',                'Breathing; ±0.5% / 3s'],
    ['XII',  'Stationery',            'Letterhead, calling card'],
    ['XIII', 'Slack & App Icons',     'At 16, 32, 128'],
    ['XIV',  'The Receipt in the wild', 'Seals, pins, reply-affix'],
    ['XV',   'Colophon',              'Credits & reference'],
  ];
  return (
    <Plate n="01" chapter="Contents" title="Plates I – XV">
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 64px', alignSelf: 'stretch' }}>
        {rows.map((r) => (
          <div key={r[0]} style={{ display: 'grid', gridTemplateColumns: '44px 1fr auto', padding: '10px 0', borderBottom: `1px dashed ${BK.paperEdge}`, alignItems: 'baseline' }}>
            <span style={{ fontFamily: BK.mono, fontSize: 11, color: BK.inkFaint, letterSpacing: 1 }}>{r[0]}</span>
            <span style={{ fontFamily: BK.serif, fontSize: 20 }}>{r[1]}</span>
            <span style={{ fontFamily: BK.serif, fontStyle: 'italic', fontSize: 13, color: BK.inkMute }}>{r[2]}</span>
          </div>
        ))}
      </div>
    </Plate>
  );
}

// ─── I · SEAL ───
function SealPlate() {
  return (
    <Plate n="I" chapter="The Seal" title="A sealed W, hashed at the valley.">
      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: 60, flex: 1, alignItems: 'center' }}>
        <div style={{ position: 'relative', display: 'flex', justifyContent: 'center' }}>
          <div style={{ position: 'relative' }}>
            <ConstructionGrid size={380} />
            <div style={{ position: 'absolute', inset: 0 }}>
              <WMonogram size={380} ink={BK.ink} paper={BK.paper} />
            </div>
          </div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          <Italic>
            The monogram is built on a <b style={{ fontStyle: 'normal' }}>10-unit grid</b>, its diameter equal to
            10u. Four diagonals form the W; a tied loop in the valley stands in for the worm —
            the hash, the link, the bound record.
          </Italic>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 14px' }}>
            {[
              ['Outer ring', '5u r · 1.3px stroke'],
              ['Inner ring', '4.2u r · 0.8px stroke'],
              ['W leg slope', '20° from vertical'],
              ['Leg width', '0.8u outer · 0.6u inner'],
              ['Valley loop', '1u diameter, centered'],
              ['Compass notches', '4 × at N/E/S/W'],
            ].map(([k, v]) => (
              <div key={k} style={{ fontFamily: BK.mono, fontSize: 11, letterSpacing: 0.6, color: BK.inkSoft, borderBottom: `1px dashed ${BK.paperEdge}`, padding: '4px 0', display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: BK.inkMute }}>— {k}</span>
                <span>{v}</span>
              </div>
            ))}
          </div>
          <Italic style={{ fontSize: 13, color: BK.inkMute }}>
            The seal is a stamp pressed into paper, not an icon rendered on a screen. Draw it sharp, not soft.
          </Italic>
        </div>
      </div>
    </Plate>
  );
}
function ConstructionGrid({ size }) {
  const n = 10;
  const step = size / n;
  return (
    <svg width={size} height={size} style={{ position: 'absolute' }}>
      {Array.from({ length: n + 1 }).map((_, i) => (
        <g key={i}>
          <line x1={i * step} y1="0" x2={i * step} y2={size} stroke={BK.paperEdge} strokeWidth={i === n / 2 ? 0.6 : 0.3} />
          <line x1="0" y1={i * step} x2={size} y2={i * step} stroke={BK.paperEdge} strokeWidth={i === n / 2 ? 0.6 : 0.3} />
        </g>
      ))}
      <circle cx={size / 2} cy={size / 2} r={size / 2 - 4} fill="none" stroke={BK.paperEdge} strokeDasharray="2 3" />
    </svg>
  );
}

// ─── II · WORDMARK ───
function WordmarkPlate() {
  return (
    <Plate n="II" chapter="The Wordmark" title="WORMBASE, set as plate.">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 32, flex: 1, justifyContent: 'center' }}>
        <div style={{ borderTop: `1px solid ${BK.ink}`, borderBottom: `1px solid ${BK.ink}`, padding: '36px 0', textAlign: 'center' }}>
          <Wordmark height={88} rule={false} color={BK.ink} />
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 28 }}>
          {[
            ['Typeface', 'Source Serif 4', 'opsz 60 · wght 500'],
            ['Tracking', '+80 units', '≈ 0.08em, all caps'],
            ['The "B"', 'weight 400', 'one step lighter for rhythm'],
            ['Rule', '1px ink', 'optional; sits 0.25em below'],
            ['Minimum size', '72px / 22mm', 'print & screen'],
            ['Never', 'slant · stretch · colorize', 'use lockups instead'],
          ].map(([k, v, n]) => (
            <div key={k} style={{ borderTop: `1px solid ${BK.paperEdge}`, padding: '8px 0' }}>
              <Meta>— {k}</Meta>
              <div style={{ fontFamily: BK.serif, fontSize: 18, color: BK.ink, marginTop: 2 }}>{v}</div>
              <div style={{ fontFamily: BK.serif, fontStyle: 'italic', fontSize: 12, color: BK.inkMute }}>{n}</div>
            </div>
          ))}
        </div>
      </div>
    </Plate>
  );
}

// ─── III · LOCKUPS ───
function LockupPlate() {
  return (
    <Plate n="III" chapter="Lockups" title="Three arrangements, three uses.">
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 28, flex: 1 }}>
        {[
          { title: 'Horizontal · primary', sub: 'Signatures, headers, letterhead',
            el: <Lockup orientation="horizontal" scale={1.1} color={BK.ink} paper={BK.paper} /> },
          { title: 'Stacked · formal',     sub: 'Covers, seals, frontispieces',
            el: <Lockup orientation="stacked" scale={1.1} color={BK.ink} paper={BK.paper} /> },
          { title: 'Mark alone',           sub: 'Avatars, favicons, stamps',
            el: <WMonogram size={180} ink={BK.ink} paper={BK.paper} /> },
        ].map((c) => (
          <div key={c.title} style={{ border: `1px solid ${BK.paperEdge}`, background: BK.paper, padding: 20, display: 'flex', flexDirection: 'column' }}>
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px 0', minHeight: 280 }}>{c.el}</div>
            <div style={{ borderTop: `1px solid ${BK.ink}`, paddingTop: 10 }}>
              <Meta>— {c.title}</Meta>
              <Italic style={{ fontSize: 13, marginTop: 4 }}>{c.sub}</Italic>
            </div>
          </div>
        ))}
      </div>
    </Plate>
  );
}

// ─── IV · CLEAR SPACE ───
function ClearspacePlate() {
  return (
    <Plate n="IV" chapter="Clear Space · Scale" title="Room to breathe.">
      <div style={{ display: 'grid', gridTemplateColumns: '1.3fr 1fr', gap: 48, flex: 1 }}>
        <div>
          <Meta style={{ marginBottom: 10 }}>— CLEAR SPACE ≥ 1X (THE SEAL DIAMETER)</Meta>
          <div style={{ position: 'relative', border: `1px dashed ${BK.inkMute}`, padding: 80, background: BK.paperDeep }}>
            <div style={{ background: BK.paper, padding: 30, border: `1px solid ${BK.paperEdge}`, display: 'flex', justifyContent: 'center' }}>
              <Lockup orientation="horizontal" scale={1.1} color={BK.ink} paper={BK.paper} />
            </div>
            {['top', 'bottom'].map((s) => (
              <div key={s} style={{ position: 'absolute', [s]: 10, left: '50%', transform: 'translateX(-50%)', fontFamily: BK.mono, fontSize: 10, color: BK.inkMute, letterSpacing: 1 }}>1x</div>
            ))}
            {['left', 'right'].map((s) => (
              <div key={s} style={{ position: 'absolute', [s]: 10, top: '50%', transform: 'translateY(-50%)', fontFamily: BK.mono, fontSize: 10, color: BK.inkMute, letterSpacing: 1 }}>1x</div>
            ))}
          </div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          <Meta>— MIN SIZES</Meta>
          <div style={{ border: `1px solid ${BK.paperEdge}`, padding: '20px 24px', background: BK.paper }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 18, paddingBottom: 14, borderBottom: `1px dashed ${BK.paperEdge}` }}>
              <WMonogram size={16} ink={BK.ink} paper={BK.paper} />
              <div><Meta>16 PX · FAVICON</Meta><Italic style={{ fontSize: 12 }}>Drop outer ring at ≤ 16px</Italic></div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 18, padding: '14px 0', borderBottom: `1px dashed ${BK.paperEdge}` }}>
              <WMonogram size={32} ink={BK.ink} paper={BK.paper} />
              <div><Meta>32 PX · SLACK</Meta><Italic style={{ fontSize: 12 }}>Full monogram preserved</Italic></div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 18, paddingTop: 14 }}>
              <WMonogram size={64} ink={BK.ink} paper={BK.paper} />
              <div><Meta>64 PX+ · EVERYWHERE ELSE</Meta><Italic style={{ fontSize: 12 }}>Lockups become available above 128px</Italic></div>
            </div>
          </div>
          <Italic style={{ fontSize: 13, color: BK.inkMute }}>
            Below 16px, the W becomes illegible. Use the green-field initial <b style={{ fontStyle: 'normal' }}>w.</b> instead.
          </Italic>
        </div>
      </div>
    </Plate>
  );
}

// ─── V · MISUSE ───
function MisusePlate() {
  const bad = [
    { label: 'Do not recolor', el: <WMonogram size={96} ink={'#7A3DB8'} paper={BK.paper} /> },
    { label: 'Do not rotate',  el: <div style={{ transform: 'rotate(18deg)' }}><WMonogram size={96} ink={BK.ink} paper={BK.paper} /></div> },
    { label: 'Do not stretch', el: <div style={{ transform: 'scale(1.5, 0.8)' }}><WMonogram size={96} ink={BK.ink} paper={BK.paper} /></div> },
    { label: 'Do not glow',    el: <div style={{ filter: 'drop-shadow(0 0 14px #2C5F3E)' }}><WMonogram size={96} ink={BK.ink} paper={BK.paper} /></div> },
    { label: 'Do not gradient', el: <div style={{ background: 'linear-gradient(135deg, #2C5F3E, #B8603C)', WebkitBackgroundClip: 'text', borderRadius: 48 }}>
        <svg width="96" height="96" viewBox="0 0 120 120">
          <defs><linearGradient id="gbad" x1="0" x2="1"><stop offset="0" stopColor="#2C5F3E"/><stop offset="1" stopColor="#B8603C"/></linearGradient></defs>
          <circle cx="60" cy="60" r="56" fill="url(#gbad)"/>
          <path d="M28 36h9l12 40h-9zm16 0h8l8 28-4 12h-6zm24 0h8l-6 40h-6l-4-12zm15 0h9l-12 40h-9z" fill="#FAF7F0"/>
        </svg>
      </div>
    },
    { label: 'Do not outline-and-fill', el: <WMonogram size={96} ink={BK.sepia} paper={BK.paper} mode="outline" /> },
  ];
  return (
    <Plate n="V" chapter="Misuse" title="Everything below — never.">
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 28, flex: 1 }}>
        {bad.map((b, i) => (
          <div key={i} style={{ border: `1px solid ${BK.paperEdge}`, background: BK.paper, display: 'flex', flexDirection: 'column' }}>
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 180, padding: 20, position: 'relative' }}>
              {b.el}
              <svg width="140" height="140" viewBox="0 0 100 100" style={{ position: 'absolute', opacity: 0.55 }}>
                <circle cx="50" cy="50" r="46" fill="none" stroke={BK.sepia} strokeWidth="2" />
                <line x1="18" y1="18" x2="82" y2="82" stroke={BK.sepia} strokeWidth="2" />
              </svg>
            </div>
            <div style={{ borderTop: `1px solid ${BK.ink}`, padding: '10px 14px', display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
              <Meta style={{ color: BK.sepia }}>— NEVER</Meta>
              <Italic style={{ fontSize: 13 }}>{b.label}</Italic>
            </div>
          </div>
        ))}
      </div>
    </Plate>
  );
}

// ─── VI · COLOR ON COLOR ───
function ColorPairsPlate() {
  const pairs = [
    { ground: BK.paper,     ink: BK.ink,   label: 'Paper · Ink',         ok: true  },
    { ground: BK.paperDeep, ink: BK.ink,   label: 'Paper-deep · Ink',    ok: true  },
    { ground: BK.ink,       ink: BK.paper, label: 'Ink · Paper',         ok: true  },
    { ground: BK.green,     ink: BK.paper, label: 'Green · Paper',       ok: true  },
    { ground: BK.greenSoft, ink: BK.greenDeep, label: 'Green-soft · Green-deep', ok: true },
    { ground: BK.sepia,     ink: BK.paper, label: 'Sepia · Paper',       ok: false, note: 'Warning field only' },
  ];
  return (
    <Plate n="VI" chapter="Color on Color" title="Permitted pairings.">
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 20, flex: 1 }}>
        {pairs.map((p) => (
          <div key={p.label} style={{ border: `1px solid ${BK.ink}` }}>
            <div style={{ background: p.ground, padding: 40, display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: 200 }}>
              <Lockup orientation="stacked" scale={0.75} color={p.ink} paper={p.ground} withReceipt={false} />
            </div>
            <div style={{ borderTop: `1px solid ${BK.ink}`, padding: '10px 14px', background: BK.paper, display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
              <Italic style={{ fontSize: 13 }}>{p.label}</Italic>
              <Meta style={{ color: p.ok ? BK.green : BK.sepia }}>— {p.ok ? 'OK' : (p.note || 'RESTRICTED')}</Meta>
            </div>
          </div>
        ))}
      </div>
    </Plate>
  );
}

// ─── VII · PALETTE ───
function PalettePlate() {
  const rows = [
    ['paper',      '#FAF7F0', 'Ground · 70% of surface', BK.paper,     BK.ink],
    ['paper-deep', '#F2ECDE', 'Section fills, hover',    BK.paperDeep, BK.ink],
    ['paper-edge', '#E8E0CC', 'Thin rules, borders',     BK.paperEdge, BK.ink],
    ['ink',        '#2A2A2A', 'Primary text & rules',    BK.ink,       BK.paper],
    ['ink-soft',   '#4A4842', 'Secondary text',          BK.inkSoft,   BK.paper],
    ['ink-mute',   '#7A7A7A', 'Metadata, mono labels',   BK.inkMute,   BK.paper],
    ['green',      '#2C5F3E', 'Verified · Seal · Field', BK.green,     BK.paper],
    ['green-deep', '#1F4A2E', 'Pressed, confirmed',      BK.greenDeep, BK.paper],
    ['green-soft', '#E6EDE4', 'Class. wash',             BK.greenSoft, BK.ink],
    ['sepia',      '#B8603C', 'WARNING ONLY',            BK.sepia,     BK.paper],
    ['sepia-soft', '#F3E4DA', 'Warning wash',            BK.sepiaSoft, BK.ink],
  ];
  return (
    <Plate n="VII" chapter="Palette" title="Paper, ink, botanical.">
      <div style={{ border: `1px solid ${BK.ink}`, flex: 1, display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)' }}>
        {rows.map((r, i) => (
          <div key={r[0]} style={{
            background: r[3], color: r[4], padding: '18px 18px 16px',
            borderRight: (i + 1) % 4 === 0 ? 'none' : `1px solid ${BK.ink}`,
            borderBottom: i < 8 ? `1px solid ${BK.ink}` : 'none',
            minHeight: 130, display: 'flex', flexDirection: 'column', justifyContent: 'space-between',
          }}>
            <div style={{ fontFamily: BK.serif, fontStyle: 'italic', fontSize: 15, lineHeight: 1.3 }}>{r[2]}</div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: BK.mono, fontSize: 10, letterSpacing: 0.6 }}>
              <span>—{r[0]}</span><span style={{ opacity: 0.85 }}>{r[1]}</span>
            </div>
          </div>
        ))}
      </div>
    </Plate>
  );
}

// ─── VIII · LETTERFORMS ───
function LetterformsPlate() {
  return (
    <Plate n="VIII" chapter="Letterforms" title="Serif voice, mono receipt.">
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 48, flex: 1 }}>
        <div style={{ borderRight: `1px dashed ${BK.paperEdge}`, paddingRight: 40 }}>
          <Meta>— SERIF · SOURCE SERIF 4</Meta>
          <div style={{ fontFamily: BK.serif, fontSize: 220, lineHeight: 0.9, letterSpacing: -6, marginTop: 14, color: BK.ink }}>Wg</div>
          <div style={{ fontFamily: BK.serif, fontSize: 30, color: BK.ink, marginTop: 10 }}>The living subject under glass.</div>
          <Italic style={{ fontSize: 15, marginTop: 12 }}>
            Optical size 60 for display, 14 for body. Small caps and old-style figures by default in body text.
          </Italic>
        </div>
        <div style={{ paddingLeft: 20 }}>
          <Meta>— MONO · JETBRAINS MONO</Meta>
          <div style={{ fontFamily: BK.mono, fontSize: 220, lineHeight: 0.9, marginTop: 14, color: BK.ink }}>a1</div>
          <div style={{ fontFamily: BK.mono, fontSize: 24, color: BK.ink, marginTop: 10, letterSpacing: -0.3 }}>sha256:a7f3c9e4…</div>
          <Italic style={{ fontSize: 15, marginTop: 12 }}>
            Mono is ledger-native. Never decorative — never used for marketing headlines or pull quotes.
            Reserved for hashes, IDs, schema, SQL, metadata labels.
          </Italic>
        </div>
      </div>
    </Plate>
  );
}

// ─── IX · VOICE ───
function VoicePlate() {
  const voice = [
    ['Exact',     'A 2.1% variance in NE revenue, 09:14 UTC Tuesday.',           'Rough rumors vs the precise figure.'],
    ['Receipted', 'I checked the ledger. The number comes from fct_orders, sealed at 09:14 by @data-platform.', 'Every claim has a provable origin.'],
    ['Dry',       'The table was renamed on Monday. The rename was not announced.', 'Understatement over alarm.'],
    ['Warm',      'You can see the chain — two joins, one rename, one Tuesday. Want me to open the ledger entry?', 'Honest, never chilly.'],
  ];
  const sayDont = [
    ['SAY', '"Sealed 09:14 UTC, hash a7f3c9e4."'],
    ['SAY', '"The column was renamed on Monday; the join is from v4.1."'],
    ['SAY', '"I can walk you through the proof if you want."'],
    ['AVOID', '"Roughly 2% or so — in the neighborhood."'],
    ['AVOID', '"Pretty sure the revenue dipped!"'],
    ['AVOID', '"As your AI friend, I would love to help! ✨"'],
  ];
  return (
    <Plate n="IX" chapter="Voice & Tone" title="How WormBase speaks.">
      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: 44, flex: 1 }}>
        <div>
          <Meta style={{ marginBottom: 10 }}>— FOUR QUALITIES</Meta>
          {voice.map(([k, v, n]) => (
            <div key={k} style={{ borderTop: `1px solid ${BK.paperEdge}`, padding: '14px 0' }}>
              <div style={{ fontFamily: BK.serif, fontSize: 13, fontStyle: 'italic', color: BK.green, textTransform: 'uppercase', letterSpacing: 1.4 }}>{k}</div>
              <div style={{ fontFamily: BK.serif, fontSize: 18, color: BK.ink, marginTop: 4, lineHeight: 1.45 }}>{v}</div>
              <Italic style={{ fontSize: 13, marginTop: 4 }}>{n}</Italic>
            </div>
          ))}
        </div>
        <div>
          <Meta style={{ marginBottom: 10 }}>— SAY · AVOID</Meta>
          <div style={{ border: `1px solid ${BK.paperEdge}` }}>
            {sayDont.map(([k, v], i) => (
              <div key={i} style={{ padding: '12px 14px', borderBottom: i < sayDont.length - 1 ? `1px dashed ${BK.paperEdge}` : 'none', background: BK.paper }}>
                <Meta style={{ color: k === 'SAY' ? BK.green : BK.sepia, marginBottom: 4 }}>— {k}</Meta>
                <div style={{ fontFamily: BK.serif, fontSize: 15, color: BK.ink, lineHeight: 1.4 }}>{v}</div>
              </div>
            ))}
          </div>
          <Italic style={{ fontSize: 13, marginTop: 16 }}>
            No emoji. No exclamation marks. No "as an AI". WormBase is a senior research librarian, not a chatbot.
          </Italic>
        </div>
      </div>
    </Plate>
  );
}

// ─── X · IMAGERY ───
function ImageryPlate() {
  return (
    <Plate n="X" chapter="Imagery" title="Plates, not photographs.">
      <div style={{ display: 'grid', gridTemplateColumns: '1.1fr 1fr', gap: 40, flex: 1 }}>
        <div style={{ background: BK.paperDeep, padding: 28, border: `1px solid ${BK.paperEdge}` }}>
          <div style={{ background: BK.paper, border: `1px solid ${BK.paperEdge}`, padding: 24 }}>
            <div style={{ borderTop: `1px solid ${BK.ink}`, borderBottom: `1px solid ${BK.ink}`, padding: '6px 0', display: 'flex', justifyContent: 'space-between' }}>
              <Meta>— PL. II</Meta>
              <div style={{ fontFamily: BK.serif, fontStyle: 'italic', fontSize: 12, color: BK.inkSoft }}>Lumbricus terrestris, var. instrumentalis</div>
            </div>
            <div style={{ margin: '20px auto', width: '85%' }}>
              <NaturalistWorm />
            </div>
            <div style={{ borderTop: `1px dashed ${BK.paperEdge}`, paddingTop: 8, fontFamily: BK.mono, fontSize: 10, letterSpacing: 0.6, color: BK.inkMute }}>
              a. prostomium · b. clitellum · c. setal rows · d. hash seal
            </div>
          </div>
          <Italic style={{ textAlign: 'center', marginTop: 14, fontSize: 12 }}>
            Commissioned plate · appears only on landing & onboarding-complete.
          </Italic>
        </div>
        <div>
          <Meta>— IMAGERY RULES</Meta>
          <ol style={{ fontFamily: BK.serif, fontSize: 16, color: BK.inkSoft, lineHeight: 1.6, paddingLeft: 22 }}>
            <li>Imagery is <b style={{ fontStyle: 'normal' }}>drawn</b>, not photographed. Ink on paper; one tone, two at most.</li>
            <li>Every image is a <b style={{ fontStyle: 'normal' }}>plate</b>: it sits inside a double-rule frame, is numbered, named, and captioned.</li>
            <li>Subjects are <b style={{ fontStyle: 'normal' }}>specimens</b>: tables, joins, anomalies — rendered as natural-history figures.</li>
            <li>No stock photography. No AI-generated mascots. No 3D render.</li>
            <li>The naturalist worm is <b style={{ fontStyle: 'normal' }}>one asset, used twice</b>. Do not extend it into an illustration system.</li>
          </ol>
          <div style={{ marginTop: 18, borderTop: `1px dashed ${BK.paperEdge}`, paddingTop: 12 }}>
            <Meta>— PERMITTED TEXTURES</Meta>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10, marginTop: 10 }}>
              {[
                `repeating-linear-gradient(0deg, ${BK.paper} 0 14px, ${BK.paperDeep} 14px 15px)`,
                `repeating-linear-gradient(45deg, ${BK.paper} 0 8px, ${BK.paperDeep} 8px 9px)`,
                `radial-gradient(${BK.paperDeep} 1px, ${BK.paper} 1px) 0 0 / 8px 8px`,
              ].map((bg, i) => (
                <div key={i} style={{ height: 70, background: bg, border: `1px solid ${BK.paperEdge}` }} />
              ))}
            </div>
            <Italic style={{ fontSize: 12, marginTop: 10 }}>Lined leaf · cross-hatch · stipple. All printable in one-color.</Italic>
          </div>
        </div>
      </div>
    </Plate>
  );
}
function NaturalistWorm() {
  return (
    <svg viewBox="0 0 420 180" width="100%" style={{ display: 'block', color: BK.ink }}>
      <defs>
        <pattern id="bh" patternUnits="userSpaceOnUse" width="3" height="3" patternTransform="rotate(35)">
          <line x1="0" y1="0" x2="0" y2="3" stroke="currentColor" strokeWidth="0.3" />
        </pattern>
      </defs>
      <path d="M 30 96 C 42 66, 78 58, 118 74 C 170 96, 210 52, 262 62 C 316 72, 346 112, 380 96 C 386 100, 386 108, 382 114 C 350 134, 316 90, 262 84 C 216 78, 176 122, 118 104 C 82 94, 50 112, 36 114 C 30 112, 26 104, 30 96 Z" fill="url(#bh)" stroke="currentColor" strokeWidth="0.8" />
      {Array.from({ length: 42 }).map((_, i) => {
        const t = i / 41;
        const x = 40 + t * 330;
        const cy = 96 + Math.sin(t * Math.PI * 2.4) * 14;
        const h = 8 - Math.abs(Math.sin(t * Math.PI)) * 3;
        return <line key={i} x1={x} y1={cy - h} x2={x} y2={cy + h} stroke="currentColor" strokeWidth="0.45" opacity="0.7" />;
      })}
      <path d="M 204 64 C 234 60, 254 60, 280 66 C 280 78, 258 88, 230 86 C 212 84, 204 76, 204 64 Z" fill="currentColor" opacity="0.12" stroke="currentColor" strokeWidth="0.5" />
    </svg>
  );
}

// ─── XI · MOTION ───
function MotionPlate() {
  const [t, setT] = React.useState(0);
  React.useEffect(() => {
    let raf; const start = performance.now();
    const tick = (now) => { setT((now - start) / 1000); raf = requestAnimationFrame(tick); };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);
  const phase = (t % 3) / 3;
  const pulse = Math.sin(phase * Math.PI * 2) * 0.005;
  const value = 87.4 * (1 + pulse);
  return (
    <Plate n="XI" chapter="Motion" title="Breathing. Nothing else moves.">
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 48, flex: 1, alignItems: 'center' }}>
        <div>
          <div style={{ border: `1px solid ${BK.paperEdge}`, padding: 36, background: BK.paper }}>
            <Meta>— FRESHNESS</Meta>
            <div style={{ fontFamily: BK.mono, fontSize: 72, lineHeight: 1, letterSpacing: -2, color: BK.ink, marginTop: 10, fontVariantNumeric: 'tabular-nums' }}>
              {value.toFixed(2)}<span style={{ fontSize: 28, color: BK.inkMute, marginLeft: 6 }}>%</span>
            </div>
            <div style={{ marginTop: 16, position: 'relative', height: 14, borderTop: `1px solid ${BK.ink}`, borderBottom: `1px solid ${BK.ink}` }}>
              <div style={{ position: 'absolute', inset: 0, width: value + '%', background: BK.green }} />
            </div>
            <Italic style={{ fontSize: 12, marginTop: 14 }}>
              Live, and you can see it living — the number drifts ±0.5% on a 3-second sine.
            </Italic>
          </div>
        </div>
        <div>
          <Meta style={{ marginBottom: 10 }}>— THE BREATH · SPEC</Meta>
          <div style={{ border: `1px solid ${BK.paperEdge}`, padding: 20, background: BK.paper, fontFamily: BK.mono, fontSize: 13, lineHeight: 1.9, color: BK.ink }}>
            <div><span style={{ color: BK.inkMute }}>amplitude</span> ±0.005 (0.5%)</div>
            <div><span style={{ color: BK.inkMute }}>period</span>     3000 ms</div>
            <div><span style={{ color: BK.inkMute }}>waveform</span>   sin, synchronous</div>
            <div><span style={{ color: BK.inkMute }}>applies-to</span>  Gauge only</div>
            <div><span style={{ color: BK.inkMute }}>frame-rate</span>  60 fps, raf-driven</div>
          </div>
          <Italic style={{ fontSize: 14, marginTop: 18 }}>
            The page is otherwise still. No fade-ins, no parallax, no skeleton shimmer.
            A page that breathes once is a page that reads as alive; a page that breathes everywhere reads as anxious.
          </Italic>
        </div>
      </div>
    </Plate>
  );
}

// ─── XII · STATIONERY ───
function StationeryPlate() {
  return (
    <Plate n="XII" chapter="Stationery" title="Paper goods.">
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 40, flex: 1, alignItems: 'start' }}>
        <div>
          <Meta style={{ marginBottom: 8 }}>— LETTERHEAD · A4</Meta>
          <div style={{ aspectRatio: '1 / 1.414', background: BK.paper, border: `1px solid ${BK.paperEdge}`, boxShadow: '3px 3px 0 ' + BK.paperEdge, padding: '36px 40px', display: 'flex', flexDirection: 'column' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <Lockup orientation="horizontal" scale={0.75} color={BK.ink} paper={BK.paper} withReceipt={false} />
              <div style={{ textAlign: 'right', fontFamily: BK.mono, fontSize: 9, color: BK.inkMute, letterSpacing: 0.6, lineHeight: 1.5 }}>
                WORMBASE, INC.<br />1 LEDGER COURT<br />SAN FRANCISCO CA
              </div>
            </div>
            <div style={{ borderTop: `1px solid ${BK.ink}`, margin: '18px 0 22px' }} />
            <div style={{ fontFamily: BK.serif, fontSize: 14, lineHeight: 1.6, color: BK.inkSoft, flex: 1 }}>
              <p style={{ margin: '0 0 10px' }}>22 April 2026</p>
              <p style={{ margin: '0 0 10px' }}>Dear Sir —</p>
              <p style={{ margin: 0 }}>
                Enclosed find the monthly attestation, ledger tip <span style={{ fontFamily: BK.mono, fontSize: 12, color: BK.ink }}>d94e32b7…</span>, and the
                quarter's reconciliations. All entries are sealed and hash-chained to the prior volume.
              </p>
            </div>
            <div style={{ borderTop: `1px dashed ${BK.paperEdge}`, paddingTop: 8, fontFamily: BK.mono, fontSize: 8, color: BK.inkFaint, letterSpacing: 0.8, display: 'flex', justifyContent: 'space-between' }}>
              <span>⟐ SHA256:D94E32B7A1F08C…</span><span>FOLIO I · PAGE 1 / 3</span>
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          <div>
            <Meta style={{ marginBottom: 8 }}>— CALLING CARD · 85 × 55 MM</Meta>
            <div style={{ aspectRatio: '85 / 55', maxWidth: 360, background: BK.paper, border: `1px solid ${BK.paperEdge}`, boxShadow: '3px 3px 0 ' + BK.paperEdge, padding: 18, display: 'grid', gridTemplateColumns: 'auto 1fr', gap: 18, alignItems: 'center' }}>
              <WMonogram size={60} ink={BK.ink} paper={BK.paper} />
              <div>
                <div style={{ fontFamily: BK.serif, fontSize: 18, color: BK.ink }}>Dr. P. Liu</div>
                <Italic style={{ fontSize: 12, marginTop: 0 }}>Keeper of the Ledger</Italic>
                <div style={{ borderTop: `1px dashed ${BK.paperEdge}`, margin: '8px 0' }} />
                <div style={{ fontFamily: BK.mono, fontSize: 9, color: BK.inkMute, letterSpacing: 0.6, lineHeight: 1.5 }}>
                  P.LIU@WORMBASE.IO<br />WORMBASE.IO · SF
                </div>
              </div>
            </div>
          </div>

          <div>
            <Meta style={{ marginBottom: 8 }}>— ENVELOPE SEAL</Meta>
            <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
              <div style={{ width: 110, height: 110, background: BK.green, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '2px 2px 0 ' + BK.paperEdge }}>
                <WMonogram size={80} ink={BK.paper} paper={BK.green} />
              </div>
              <Italic style={{ fontSize: 13 }}>
                Wax-stamp equivalent. Green seal marks a sealed envelope;
                sepia marks "opened / broken chain."
              </Italic>
            </div>
          </div>
        </div>
      </div>
    </Plate>
  );
}

// ─── XIII · SLACK & ICON ───
function IconsPlate() {
  return (
    <Plate n="XIII" chapter="Slack & App Icons" title="The mark, at every size.">
      <div style={{ display: 'grid', gridTemplateColumns: '1.1fr 1fr', gap: 48, flex: 1 }}>
        <div>
          <Meta style={{ marginBottom: 10 }}>— SLACK · AT 128PX</Meta>
          <div style={{ background: '#1A1D21', padding: 28, border: `1px solid ${BK.ink}` }}>
            <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}>
              <div style={{ width: 44, height: 44, background: BK.paper, border: `1px solid ${BK.ink}`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                <WMonogram size={36} ink={BK.ink} paper={BK.paper} />
              </div>
              <div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}>
                  <span style={{ color: '#D1D2D3', fontFamily: 'Lato, sans-serif', fontWeight: 700, fontSize: 15 }}>WormBase</span>
                  <span style={{ background: '#696969', color: '#fff', fontSize: 10, padding: '1px 4px', letterSpacing: 0.5, fontFamily: 'Lato, sans-serif' }}>APP</span>
                  <span style={{ color: '#9A9B9E', fontSize: 12, fontFamily: 'Lato, sans-serif' }}>09:14</span>
                </div>
                <div style={{ color: '#D1D2D3', fontSize: 14, marginTop: 4, fontFamily: 'Lato, sans-serif', lineHeight: 1.45 }}>
                  Sealed your query against <span style={{ fontFamily: BK.mono, color: '#B4D5B4' }}>fct_orders</span> — 
                  the 2.1% dip traces to a rename on Monday. <span style={{ color: '#9A9B9E' }}>Chain of proof below.</span>
                </div>
                <div style={{ marginTop: 8, padding: '6px 10px', background: '#232529', fontFamily: BK.mono, fontSize: 11, color: '#B4D5B4', letterSpacing: 0.4, display: 'inline-block' }}>
                  ⟐ sha256:a7f3c9e4d2b1 · sealed 09:14:07Z
                </div>
              </div>
            </div>
          </div>
        </div>

        <div>
          <Meta style={{ marginBottom: 10 }}>— APP ICON · PROGRESSIVE FIDELITY</Meta>
          <div style={{ display: 'flex', gap: 24, alignItems: 'flex-end' }}>
            {[16, 32, 64, 128].map((s) => (
              <div key={s} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
                <div style={{ width: s, height: s, background: BK.paper, border: `1px solid ${BK.ink}`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <WMonogram size={Math.round(s * 0.85)} ink={BK.ink} paper={BK.paper} />
                </div>
                <Meta>{s}px</Meta>
              </div>
            ))}
          </div>

          <div style={{ marginTop: 30 }}>
            <Meta style={{ marginBottom: 10 }}>— ON COLORED GROUNDS</Meta>
            <div style={{ display: 'flex', gap: 16 }}>
              {[BK.green, BK.ink, BK.sepia].map((c) => (
                <div key={c} style={{ width: 72, height: 72, background: c, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <WMonogram size={58} ink={BK.paper} paper={c} />
                </div>
              ))}
            </div>
            <Italic style={{ fontSize: 13, marginTop: 14 }}>
              Rounded-square iOS masking is inherited from the OS — the mark stays flush, no fill to the edge.
            </Italic>
          </div>
        </div>
      </div>
    </Plate>
  );
}

// ─── XIV · RECEIPT IN THE WILD ───
function ReceiptsWildPlate() {
  return (
    <Plate n="XIV" chapter="The Receipt · in the wild" title="Where the mark becomes the seal.">
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 20, flex: 1 }}>
        {/* Reply badge */}
        <div style={{ border: `1px solid ${BK.paperEdge}`, background: BK.paper, padding: 20, display: 'flex', flexDirection: 'column' }}>
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, border: `1px solid ${BK.ink}`, padding: '6px 10px', background: BK.paper }}>
              <WMonogram size={20} ink={BK.green} paper={BK.paper} />
              <span style={{ fontFamily: BK.mono, fontSize: 11, color: BK.ink, letterSpacing: 0.4 }}>SEALED · a7f3c9e4</span>
            </div>
          </div>
          <div style={{ borderTop: `1px solid ${BK.ink}`, paddingTop: 10 }}>
            <Meta>— REPLY AFFIX</Meta>
            <Italic style={{ fontSize: 13 }}>Under every answered question in Slack.</Italic>
          </div>
        </div>

        {/* Doc stamp */}
        <div style={{ border: `1px solid ${BK.paperEdge}`, background: BK.paper, padding: 20, display: 'flex', flexDirection: 'column' }}>
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16, background: `repeating-linear-gradient(0deg, ${BK.paper} 0 12px, ${BK.paperDeep} 12px 13px)` }}>
            <div style={{ transform: 'rotate(-6deg)', border: `2px solid ${BK.green}`, padding: '8px 14px', background: BK.paper }}>
              <div style={{ fontFamily: BK.mono, fontSize: 10, color: BK.green, letterSpacing: 2, textAlign: 'center' }}>WORMBASE</div>
              <div style={{ fontFamily: BK.serif, fontSize: 20, fontWeight: 500, color: BK.green, textAlign: 'center', lineHeight: 1 }}>SEALED</div>
              <div style={{ fontFamily: BK.mono, fontSize: 8, color: BK.green, letterSpacing: 1, textAlign: 'center', marginTop: 2 }}>22·IV·26</div>
            </div>
          </div>
          <div style={{ borderTop: `1px solid ${BK.ink}`, paddingTop: 10 }}>
            <Meta>— DOCUMENT STAMP</Meta>
            <Italic style={{ fontSize: 13 }}>For exported reports &amp; PDFs.</Italic>
          </div>
        </div>

        {/* Enamel pin */}
        <div style={{ border: `1px solid ${BK.paperEdge}`, background: BK.paper, padding: 20, display: 'flex', flexDirection: 'column' }}>
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16, background: BK.paperDeep }}>
            <div style={{ width: 96, height: 96, borderRadius: '50%', background: BK.paper, border: `2px solid ${BK.ink}`, display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: 'inset 2px 2px 4px rgba(0,0,0,0.1), 3px 3px 0 ' + BK.paperEdge }}>
              <WMonogram size={76} ink={BK.ink} paper={BK.paper} />
            </div>
          </div>
          <div style={{ borderTop: `1px solid ${BK.ink}`, paddingTop: 10 }}>
            <Meta>— ENAMEL PIN · 28 MM</Meta>
            <Italic style={{ fontSize: 13 }}>Given at the 1,000-seal anniversary.</Italic>
          </div>
        </div>

        {/* Browser favicon */}
        <div style={{ border: `1px solid ${BK.paperEdge}`, background: BK.paper, padding: 20, display: 'flex', flexDirection: 'column' }}>
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
            <div style={{ background: '#F5F5F5', border: `1px solid #E0E0E0`, borderRadius: 12, padding: '6px 10px', display: 'inline-flex', alignItems: 'center', gap: 8, fontFamily: 'system-ui, sans-serif', fontSize: 12, color: '#444' }}>
              <WMonogram size={16} ink={BK.ink} paper={BK.paper} />
              <span>WormBase — the ledger</span>
              <span style={{ color: '#999', marginLeft: 6 }}>×</span>
            </div>
          </div>
          <div style={{ borderTop: `1px solid ${BK.ink}`, paddingTop: 10 }}>
            <Meta>— BROWSER TAB</Meta>
            <Italic style={{ fontSize: 13 }}>Favicon &amp; tab title. Ring dropped ≤ 16px.</Italic>
          </div>
        </div>

        {/* Email signature */}
        <div style={{ border: `1px solid ${BK.paperEdge}`, background: BK.paper, padding: 20, display: 'flex', flexDirection: 'column' }}>
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'flex-start', padding: 16 }}>
            <div style={{ fontFamily: BK.serif, fontSize: 13, lineHeight: 1.5, color: BK.inkSoft }}>
              <div style={{ color: BK.ink }}>Priya Liu</div>
              <Italic style={{ fontSize: 12, lineHeight: 1.4 }}>Keeper of the Ledger</Italic>
              <div style={{ borderTop: `1px solid ${BK.paperEdge}`, margin: '6px 0', width: 160 }} />
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontFamily: BK.mono, fontSize: 10, color: BK.inkMute, letterSpacing: 0.4 }}>
                <WMonogram size={20} ink={BK.ink} paper={BK.paper} />
                <span>WORMBASE · ⟐ p.liu@wormbase.io</span>
              </div>
            </div>
          </div>
          <div style={{ borderTop: `1px solid ${BK.ink}`, paddingTop: 10 }}>
            <Meta>— EMAIL SIGNATURE</Meta>
            <Italic style={{ fontSize: 13 }}>Mono last line, always.</Italic>
          </div>
        </div>

        {/* Status pip */}
        <div style={{ border: `1px solid ${BK.paperEdge}`, background: BK.paper, padding: 20, display: 'flex', flexDirection: 'column' }}>
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16, gap: 10, flexDirection: 'column' }}>
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '3px 7px', background: BK.greenSoft, color: BK.greenDeep, border: '1px solid currentColor', fontFamily: BK.mono, fontSize: 10, letterSpacing: 1 }}>
              <span style={{ width: 4, height: 4, background: 'currentColor' }} /> INTERNAL
            </div>
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '3px 7px', background: BK.sepiaSoft, color: BK.sepia, border: '1px solid currentColor', fontFamily: BK.mono, fontSize: 10, letterSpacing: 1 }}>
              <span style={{ width: 4, height: 4, background: 'currentColor' }} /> RESTRICTED
            </div>
          </div>
          <div style={{ borderTop: `1px solid ${BK.ink}`, paddingTop: 10 }}>
            <Meta>— CLASSIFICATION PIP</Meta>
            <Italic style={{ fontSize: 13 }}>On every datum that leaves the ledger.</Italic>
          </div>
        </div>
      </div>
    </Plate>
  );
}

// ─── XV · COLOPHON ───
function ColophonPlate() {
  return (
    <Plate n="XV" chapter="Colophon" title="This volume.">
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 64, flex: 1, alignItems: 'center' }}>
        <div>
          <Italic style={{ fontSize: 17 }}>
            Set in <b style={{ fontStyle: 'normal' }}>Source Serif 4</b> (Frank Grießhammer, Adobe, 2014–), optical
            size 8–60, and <b style={{ fontStyle: 'normal' }}>JetBrains Mono</b> (Philipp Nurullin, 2020).
          </Italic>
          <div style={{ borderTop: `1px solid ${BK.paperEdge}`, margin: '20px 0' }} />
          <Italic style={{ fontSize: 14 }}>
            Drawn to the <b style={{ fontStyle: 'normal' }}>Field Notebook</b> direction: institutional-organic,
            paper-ground, botanical green for verified claims, sepia reserved for refusal and warning.
            References: Audubon's Birds of America; Ernst Haeckel's Kunstformen; the ledgers of the Royal Society of London;
            Otto Neurath's Isotype tables; Massimo Vignelli's 1972 MTA map.
          </Italic>
          <div style={{ borderTop: `1px solid ${BK.paperEdge}`, margin: '20px 0' }} />
          <div style={{ fontFamily: BK.mono, fontSize: 11, color: BK.inkMute, letterSpacing: 0.5, lineHeight: 2 }}>
            <div>— Volume I · Edition I · April 2026</div>
            <div>— Chain tip · sha256:d94e32b7a1f08c…</div>
            <div>— Private circulation · do not reproduce without seal</div>
          </div>
        </div>
        <div style={{ display: 'flex', justifyContent: 'center' }}>
          <div style={{ background: BK.paperDeep, padding: 32, border: `1px solid ${BK.paperEdge}`, boxShadow: '4px 4px 0 ' + BK.paperEdge }}>
            <div style={{ background: BK.paper, padding: 40, border: `1px solid ${BK.ink}` }}>
              <WMonogram size={220} ink={BK.ink} paper={BK.paper} />
            </div>
            <div style={{ marginTop: 14, textAlign: 'center', fontFamily: BK.mono, fontSize: 9, color: BK.inkMute, letterSpacing: 1 }}>
              FINIS · WORMBASE BRAND BOOK I
            </div>
          </div>
        </div>
      </div>
    </Plate>
  );
}

// Expose all
Object.assign(window, {
  CoverPlate, ContentsPlate, SealPlate, WordmarkPlate, LockupPlate, ClearspacePlate,
  MisusePlate, ColorPairsPlate, PalettePlate, LetterformsPlate, VoicePlate,
  ImageryPlate, MotionPlate, StationeryPlate, IconsPlate, ReceiptsWildPlate, ColophonPlate,
});
