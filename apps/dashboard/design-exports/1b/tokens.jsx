// tokens.jsx — WormBase design tokens + token artboards
// Field Notebook: institutional-organic. Paper + botanical green + aged ink.

const T = {
  // Palette
  paper:       '#FAF7F0',
  paperDeep:   '#F2ECDE',   // section dividers, subtle fills
  paperEdge:   '#E8E0CC',   // thin rules
  ink:         '#2A2A2A',   // primary text
  inkSoft:     '#4A4842',   // secondary text
  inkMute:     '#7A7A7A',   // hash-gray, metadata
  inkFaint:    '#A8A49A',   // tertiary, timestamps
  green:       '#2C5F3E',   // botanical primary
  greenDeep:   '#1F4A2E',
  greenSoft:   '#E6EDE4',   // tinted washes
  sepia:       '#B8603C',   // warning ONLY
  sepiaSoft:   '#F3E4DA',

  // Type
  serif: 'ui-serif, "Source Serif 4", "Source Serif Pro", "Iowan Old Style", "Apple Garamond", Georgia, serif',
  mono:  '"JetBrains Mono", "IBM Plex Mono", ui-monospace, Menlo, Consolas, monospace',

  // Scale
  s: {
    xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32, xxxl: 48, xxxxl: 72,
  },
  // Rules
  rule: '1px solid #E8E0CC',
  ruleStrong: '1px solid #2A2A2A',
  ruleDouble: '3px double #2A2A2A',
};
window.T = T;

// Shared small atoms used in artboards
function Rule({ style }) {
  return <div style={{ height: 1, background: T.paperEdge, ...style }} />;
}
function Meta({ children, style }) {
  return (
    <div style={{
      fontFamily: T.mono, fontSize: 10, letterSpacing: 0.8,
      textTransform: 'uppercase', color: T.inkMute, ...style,
    }}>{children}</div>
  );
}
function Caption({ children, style }) {
  return (
    <div style={{
      fontFamily: T.serif, fontStyle: 'italic', fontSize: 13,
      color: T.inkSoft, lineHeight: 1.5, ...style,
    }}>{children}</div>
  );
}
window.Rule = Rule; window.Meta = Meta; window.Caption = Caption;

// ─────────────────── Artboards ───────────────────

function ArtboardFrame({ children, padding = 40, width, height }) {
  return (
    <div style={{
      width, height, background: T.paper, padding,
      fontFamily: T.serif, color: T.ink, boxSizing: 'border-box',
      overflow: 'hidden', position: 'relative',
    }}>{children}</div>
  );
}
window.ArtboardFrame = ArtboardFrame;

function ArtboardHeader({ index, title, kicker }) {
  return (
    <div style={{ marginBottom: 28 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 16 }}>
        <Meta>{kicker}</Meta>
        <Meta style={{ color: T.inkFaint }}>{index}</Meta>
      </div>
      <Rule style={{ margin: '10px 0 14px', background: T.ink, height: 1 }} />
      <h1 style={{
        fontFamily: T.serif, fontWeight: 400, fontSize: 34, lineHeight: 1.05,
        letterSpacing: -0.5, margin: 0, color: T.ink,
      }}>{title}</h1>
    </div>
  );
}
window.ArtboardHeader = ArtboardHeader;

// COLORS ARTBOARD
function ColorsArtboard() {
  const swatches = [
    { name: 'paper',      hex: '#FAF7F0', role: 'Canvas / background',       fg: T.ink },
    { name: 'paper-deep', hex: '#F2ECDE', role: 'Section fill, hover',       fg: T.ink },
    { name: 'paper-edge', hex: '#E8E0CC', role: 'Thin rules, borders',       fg: T.ink },
    { name: 'ink',        hex: '#2A2A2A', role: 'Primary text, strong rule', fg: T.paper },
    { name: 'ink-soft',   hex: '#4A4842', role: 'Secondary text',            fg: T.paper },
    { name: 'ink-mute',   hex: '#7A7A7A', role: 'Hash gray, metadata',       fg: T.paper },
    { name: 'green',      hex: '#2C5F3E', role: 'Botanical primary',         fg: T.paper },
    { name: 'green-deep', hex: '#1F4A2E', role: 'Pressed / confirmed',       fg: T.paper },
    { name: 'green-soft', hex: '#E6EDE4', role: 'Classification wash',       fg: T.ink },
    { name: 'sepia',      hex: '#B8603C', role: 'WARNING ONLY · sparingly',  fg: T.paper },
    { name: 'sepia-soft', hex: '#F3E4DA', role: 'Warning wash',              fg: T.ink },
  ];
  return (
    <ArtboardFrame>
      <ArtboardHeader index="01" kicker="Pl. I · Palette" title="Color · Paper, ink, botanical" />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0, border: `1px solid ${T.ink}` }}>
        {swatches.map((s, i) => (
          <div key={s.name} style={{
            background: s.hex, color: s.fg, padding: '16px 16px 14px',
            borderRight: i % 2 === 0 ? `1px solid ${T.ink}` : 'none',
            borderBottom: i < swatches.length - 2 ? `1px solid ${T.ink}` : 'none',
            minHeight: 88, display: 'flex', flexDirection: 'column', justifyContent: 'space-between',
          }}>
            <div style={{ fontFamily: T.serif, fontSize: 17, fontStyle: 'italic' }}>{s.role}</div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', fontFamily: T.mono, fontSize: 11, letterSpacing: 0.5 }}>
              <span>—{s.name}</span>
              <span style={{ opacity: 0.85 }}>{s.hex}</span>
            </div>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 24, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 32 }}>
        <Caption>Paper and aged ink carry 95% of the surface. Botanical green marks verified, living data — the living subject under glass.</Caption>
        <Caption>Sepia is warning only. Never decorative. If you reach for sepia to “add warmth,” reach for paper-deep instead.</Caption>
      </div>
    </ArtboardFrame>
  );
}
window.ColorsArtboard = ColorsArtboard;

// TYPE ARTBOARD
function TypeArtboard() {
  const scale = [
    { name: 'display', px: 48, sample: 'Institutional data agent', stack: 'serif', tracking: -0.6, weight: 400 },
    { name: 'h1',      px: 34, sample: 'Provenance ledger',          stack: 'serif', tracking: -0.4, weight: 400 },
    { name: 'h2',      px: 24, sample: 'Source attribution',         stack: 'serif', tracking: -0.2, weight: 500 },
    { name: 'h3',      px: 18, sample: 'Classification',             stack: 'serif', tracking: 0,    weight: 600 },
    { name: 'body',    px: 16, sample: 'Every answer is receipted and hashed. The ledger is append-only and auditable.', stack: 'serif', tracking: 0, weight: 400 },
    { name: 'small',   px: 13, sample: 'Secondary prose, footnotes.', stack: 'serif', tracking: 0, weight: 400 },
    { name: 'mono-lg', px: 14, sample: 'SELECT hash, owner FROM ledger', stack: 'mono', tracking: 0, weight: 500 },
    { name: 'mono',    px: 12, sample: 'sha256:a7f3c9e4d2b1…',      stack: 'mono', tracking: 0, weight: 500 },
    { name: 'meta',    px: 10, sample: 'HASH · OWNER · CLASSIFICATION', stack: 'mono', tracking: 0.8, weight: 500 },
  ];
  return (
    <ArtboardFrame>
      <ArtboardHeader index="02" kicker="Pl. II · Typography" title="Type · Editorial serif, semantic mono" />
      <div style={{ display: 'grid', gridTemplateColumns: '110px 70px 1fr', gap: 0, borderTop: `1px solid ${T.ink}` }}>
        {scale.map((s) => (
          <React.Fragment key={s.name}>
            <div style={{ padding: '14px 12px 14px 0', borderBottom: T.rule, fontFamily: T.mono, fontSize: 11, color: T.inkMute, letterSpacing: 0.5 }}>
              <div>—{s.name}</div>
              <div style={{ color: T.inkFaint, marginTop: 2 }}>{s.stack}</div>
            </div>
            <div style={{ padding: '14px 12px', borderBottom: T.rule, fontFamily: T.mono, fontSize: 11, color: T.inkMute, letterSpacing: 0.5 }}>
              {s.px}px
            </div>
            <div style={{ padding: '12px 0 14px', borderBottom: T.rule }}>
              <div style={{
                fontFamily: s.stack === 'mono' ? T.mono : T.serif,
                fontSize: s.px, fontWeight: s.weight,
                letterSpacing: s.stack === 'mono' ? 0 : s.tracking,
                lineHeight: s.px > 30 ? 1.05 : 1.35,
                color: T.ink,
              }}>{s.sample}</div>
            </div>
          </React.Fragment>
        ))}
      </div>
      <div style={{ marginTop: 22 }}>
        <Caption>
          Serif is voice. Mono is <span style={{ fontFamily: T.mono, fontStyle: 'normal', fontSize: 12 }}>ledger-native</span> — it marks
          anything the system can prove: hashes, IDs, SQL, schema names, owners. Never decorative.
        </Caption>
      </div>
    </ArtboardFrame>
  );
}
window.TypeArtboard = TypeArtboard;

// SPACING ARTBOARD
function SpacingArtboard() {
  const spaces = [
    { name: 'xs',    px: 4 },
    { name: 'sm',    px: 8 },
    { name: 'md',    px: 12 },
    { name: 'lg',    px: 16 },
    { name: 'xl',    px: 24 },
    { name: 'xxl',   px: 32 },
    { name: 'xxxl',  px: 48 },
    { name: 'xxxxl', px: 72 },
  ];
  return (
    <ArtboardFrame>
      <ArtboardHeader index="03" kicker="Pl. III · Measure" title="Spacing · Vertical rhythm" />
      <div style={{ borderTop: `1px solid ${T.ink}` }}>
        {spaces.map((s) => (
          <div key={s.name} style={{ display: 'grid', gridTemplateColumns: '80px 60px 1fr', alignItems: 'center', borderBottom: T.rule, padding: '10px 0' }}>
            <div style={{ fontFamily: T.mono, fontSize: 12, color: T.inkMute }}>—{s.name}</div>
            <div style={{ fontFamily: T.mono, fontSize: 12, color: T.inkMute }}>{s.px}px</div>
            <div style={{ height: 14, width: s.px, background: T.green }} />
          </div>
        ))}
      </div>
      <div style={{ marginTop: 28 }}>
        <Meta style={{ marginBottom: 10 }}>— Rules & thresholds</Meta>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
          <div>
            <div style={{ height: 1, background: T.paperEdge, marginBottom: 10 }} />
            <Caption>Thin · 1px ink-10%. Section separation.</Caption>
          </div>
          <div>
            <div style={{ height: 1, background: T.ink, marginBottom: 10 }} />
            <Caption>Strong · 1px ink. Primary boundary.</Caption>
          </div>
          <div>
            <div style={{ borderTop: `3px double ${T.ink}`, marginBottom: 10, height: 0 }} />
            <Caption>Double · 3px. Heading divider; Royal Society.</Caption>
          </div>
          <div>
            <div style={{ borderTop: `1px dashed ${T.inkMute}`, marginBottom: 10 }} />
            <Caption>Dashed · Provisional / pending ledger.</Caption>
          </div>
        </div>
      </div>
      <div style={{ marginTop: 24 }}>
        <Caption>Generous vertical rhythm between sections, tight density within. The page breathes between thoughts, not inside them.</Caption>
      </div>
    </ArtboardFrame>
  );
}
window.SpacingArtboard = SpacingArtboard;
