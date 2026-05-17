// artboards-primitives.jsx — Artboards showing each primitive + variants

function ButtonArtboard() {
  return (
    <ArtboardFrame>
      <ArtboardHeader index="04" kicker="Pl. IV · Primitive" title="Button · Action, verified" />

      <Section label="— Variants">
        <Row>
          <Stack label="primary"><Button variant="primary">Seal ledger</Button></Stack>
          <Stack label="field"><Button variant="field">Run query</Button></Stack>
          <Stack label="ghost"><Button variant="ghost">Cancel</Button></Stack>
          <Stack label="danger"><Button variant="danger">Revoke</Button></Stack>
        </Row>
      </Section>

      <Section label="— States · primary">
        <Row>
          <Stack label="default"><Button>Seal ledger</Button></Stack>
          <Stack label="hover"><Button state="hover">Seal ledger</Button></Stack>
          <Stack label="pressed"><Button state="pressed">Seal ledger</Button></Stack>
          <Stack label="loading"><Button state="loading">Sealing…</Button></Stack>
          <Stack label="disabled"><Button state="disabled">Seal ledger</Button></Stack>
        </Row>
      </Section>

      <Section label="— Sizes">
        <Row>
          <Stack label="sm"><Button size="sm" variant="field">Run query</Button></Stack>
          <Stack label="md"><Button size="md" variant="field">Run query</Button></Stack>
          <Stack label="lg"><Button size="lg" variant="field">Run query</Button></Stack>
        </Row>
      </Section>

      <Section label="— Mono · ledger actions">
        <Row>
          <Stack label="mono primary"><Button mono variant="primary">COMMIT</Button></Stack>
          <Stack label="mono ghost"><Button mono variant="ghost">DIFF</Button></Stack>
          <Stack label="mono danger"><Button mono variant="danger">REVERT</Button></Stack>
        </Row>
      </Section>

      <Caption style={{ marginTop: 18 }}>
        Buttons have sharp corners and a 2px offset block-shadow — a letterpress impression, pressed into paper. No round, no gradient.
      </Caption>
    </ArtboardFrame>
  );
}
window.ButtonArtboard = ButtonArtboard;

function InputArtboard() {
  return (
    <ArtboardFrame>
      <ArtboardHeader index="05" kicker="Pl. V · Primitive" title="Input · Field entry" />

      <Section label="— States">
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 28 }}>
          <Input label="Dataset name" placeholder="e.g. fct_orders" />
          <Input label="Dataset name" value="fct_orders_daily" state="focus" hint="Will be registered in the ledger" />
          <Input label="SQL filter" value="WHERE created_at > NOW() - INTERVAL 7 DAY" mono state="focus" />
          <Input label="Dataset name" value="fct_orders!" state="error" error="Only lowercase, digits, underscore" />
          <Input label="Owner handle" value="@data-platform" state="disabled" hint="Inherited from workspace" />
          <Input label="Hash prefix" placeholder="sha256:…" mono prefix="⟐" hint="At least 8 characters" />
        </div>
      </Section>

      <Section label="— With suffix · threshold">
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 28 }}>
          <Input label="Breathing amplitude" value="0.5" suffix="% / 3s" mono />
          <Input label="Retention" value="90" suffix="days" />
        </div>
      </Section>

      <Caption style={{ marginTop: 18 }}>
        Bottom rule is the active surface: ink when resting, green when focused, sepia when refused. The field is a line on paper, not a box.
      </Caption>
    </ArtboardFrame>
  );
}
window.InputArtboard = InputArtboard;

function CardArtboard() {
  return (
    <ArtboardFrame>
      <ArtboardHeader index="06" kicker="Pl. VI · Primitive" title="Card · Plate, bound, specimen" />

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
        <Card variant="plate" kicker="— PLATE" index="§ 01" title="Active ingestions"
          footer={<Meta>Updated 4s ago · auto-refresh</Meta>}>
          <div style={{ fontFamily: T.serif, fontSize: 14, color: T.inkSoft, lineHeight: 1.55 }}>
            Three warehouses are currently being scanned. The worm has proposed 14 new
            tables for admission to the ledger.
          </div>
        </Card>

        <Card variant="bound" kicker="— BOUND" index="§ 02" title="Schema proposal">
          <div style={{ fontFamily: T.mono, fontSize: 11, color: T.ink, lineHeight: 1.7 }}>
            <div>+ fct_orders.refund_amount  numeric(12,2)</div>
            <div>+ fct_orders.refund_reason  text</div>
            <div style={{ color: T.sepia }}>~ dim_customer.email       encrypted</div>
          </div>
          <div style={{ marginTop: 14, display: 'flex', gap: 8 }}>
            <Button variant="field" size="sm">Admit</Button>
            <Button variant="ghost" size="sm">Diff</Button>
          </div>
        </Card>

        <div style={{ gridColumn: '1 / -1' }}>
          <Card variant="plate" kicker="— SPECIMEN" index="§ 03" title="Observed anomaly · orders.volume">
            <div style={{ display: 'grid', gridTemplateColumns: '1.3fr 1fr', gap: 22, alignItems: 'center' }}>
              <SpecimenPlaceholder label="trend · 14d" />
              <div>
                <div style={{ fontFamily: T.serif, fontSize: 14, color: T.inkSoft, lineHeight: 1.6 }}>
                  Volume deviates −23% from the 30-day running mean beginning
                  <span style={{ fontFamily: T.mono, fontStyle: 'normal' }}> 2026-04-19T08:00Z</span>.
                  Correlates with <span style={{ fontStyle: 'italic' }}>checkout.latency</span>.
                </div>
                <div style={{ marginTop: 12 }}>
                  <Receipt density="footer" classification="internal" />
                </div>
              </div>
            </div>
          </Card>
        </div>
      </div>
    </ArtboardFrame>
  );
}
window.CardArtboard = CardArtboard;

function SpecimenPlaceholder({ label }) {
  return (
    <div style={{
      height: 150, background: `repeating-linear-gradient(45deg, ${T.paper} 0 8px, ${T.paperDeep} 8px 9px)`,
      border: `1px solid ${T.paperEdge}`, position: 'relative',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <div style={{ fontFamily: T.mono, fontSize: 10, letterSpacing: 0.8, color: T.inkMute }}>{label}</div>
    </div>
  );
}

function ReceiptArtboard() {
  return (
    <ArtboardFrame>
      <ArtboardHeader index="07" kicker="Pl. VII · Primitive" title="Receipt · Hash, source, owner, class" />

      <Section label="— Density: footer (default)">
        <div style={{ border: `1px solid ${T.paperEdge}` }}>
          <div style={{ padding: '18px 16px', fontFamily: T.serif, fontSize: 17, color: T.ink }}>
            <span style={{ fontFamily: T.mono, fontSize: 16, color: T.green, fontWeight: 500 }}>$2,483,192.40</span>
            <span style={{ color: T.inkSoft, marginLeft: 10, fontStyle: 'italic' }}>gross revenue · Q1</span>
          </div>
          <Receipt density="footer" classification="internal" />
        </div>
      </Section>

      <Section label="— Density: expandable">
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <Receipt density="expand" classification="internal" />
          <Receipt density="expand" classification="restricted" expanded />
        </div>
      </Section>

      <Section label="— Density: margin annotation">
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 240px', gap: 28, alignItems: 'start' }}>
          <div style={{ fontFamily: T.serif, fontSize: 14.5, color: T.inkSoft, lineHeight: 1.65 }}>
            <p style={{ margin: 0 }}>
              The 14-day rolling churn sits at <span style={{ fontFamily: T.mono, color: T.ink }}>2.31%</span>,
              within the agreed band. No intervention recommended.
            </p>
            <p style={{ marginTop: 10 }}>
              Worm has provisionally bound <span style={{ fontStyle: 'italic' }}>dim_customer.cohort_month</span> to
              the retention view; admission is pending owner seal.
            </p>
          </div>
          <Receipt density="margin" classification="restricted" />
        </div>
      </Section>

      <Caption style={{ marginTop: 18 }}>
        A Receipt is not optional chrome. Every data display renders one — that is the contract. Three densities to match surface: dense tables take footer, annotated prose takes margin, audit lists take expandable.
      </Caption>
    </ArtboardFrame>
  );
}
window.ReceiptArtboard = ReceiptArtboard;

function GaugeArtboard() {
  return (
    <ArtboardFrame>
      <ArtboardHeader index="08" kicker="Pl. VIII · Primitive" title="Gauge · Breathing, ±0.5% / 3s" />

      <Section label="— Horizontal · scientific instrument">
        <div style={{ display: 'grid', gap: 24 }}>
          <GaugeBar kicker="— LEDGER · SEAL LATENCY" label="p95 write-to-seal, past hour" value={82.4} unit="ms" min={0} max={250} thresholds={[100, 200]} />
          <GaugeBar kicker="— QUALITY · FIDELITY" label="hashes reconciled against source" value={99.7} unit="%" min={95} max={100} thresholds={[99, 99.5]} />
          <GaugeBar kicker="— INGEST · THROUGHPUT" label="events sealed per minute" value={14237} unit="" min={0} max={20000} />
        </div>
      </Section>

      <Section label="— Circular · with threshold rings">
        <div style={{ display: 'flex', gap: 48, justifyContent: 'space-around' }}>
          <GaugeRing kicker="— SEAL LATENCY" label="p95, past hour" value={82.4} unit="ms" min={0} max={250} />
          <GaugeRing kicker="— FIDELITY" label="past 24h" value={99.7} unit="%" min={95} max={100} />
          <GaugeRing kicker="— COVERAGE" label="tables sealed" value={86} unit="%" min={0} max={100} />
        </div>
      </Section>

      <Caption style={{ marginTop: 18 }}>
        Every gauge breathes. A still gauge is a dead one — and a dead worm reports nothing. The pulse is small (±0.5%), synchronous across the page, slow enough to read as <span style={{ fontStyle: 'italic' }}>alive</span>, not anxious.
      </Caption>
    </ArtboardFrame>
  );
}
window.GaugeArtboard = GaugeArtboard;

function LedgerArtboard() {
  return (
    <ArtboardFrame>
      <ArtboardHeader index="09" kicker="Pl. IX · Primitive" title="LedgerEntry · Append-only data row" />

      <Section label="— Rolling ledger · recent entries">
        <div style={{ border: `1px solid ${T.ink}`, background: T.paper }}>
          <div style={{ display: 'grid', gridTemplateColumns: '84px 70px 1fr 130px', gap: 12, padding: '8px 16px 8px 18px',
            fontFamily: T.mono, fontSize: 9.5, letterSpacing: 0.8, textTransform: 'uppercase', color: T.inkMute,
            borderBottom: `1px solid ${T.ink}` }}>
            <span>— id</span>
            <span>op</span>
            <span>subject</span>
            <span style={{ textAlign: 'right' }}>at</span>
          </div>
          <LedgerEntry id="LE/0041829" op="SEAL"    subject="analytics.fct_orders_daily"           at="09:14:07Z" owner="data-platform"  hash="a7f3c9e4" state="verified"  classification="internal" />
          <LedgerEntry id="LE/0041830" op="ADMIT"   subject="analytics.dim_customer.cohort_month"  at="09:14:21Z" owner="growth"         hash="b2e81d0a" state="verified"  classification="restricted" />
          <LedgerEntry id="LE/0041831" op="PROPOSE" subject="analytics.fct_refunds"                at="09:14:44Z" owner="worm/agent"     hash="c5a17f93" state="pending"   classification="internal" />
          <LedgerEntry id="LE/0041832" op="SEAL"    subject="analytics.dim_product"                at="09:15:02Z" owner="data-platform"  hash="d94e32b7" state="verified"  classification="public" />
          <LedgerEntry id="LE/0041833" op="DELETE"  subject="staging.tmp_raw_exports"              at="09:15:18Z" owner="data-platform"  hash="e1802cc4" state="contested" classification="restricted" />
        </div>
      </Section>

      <Section label="— States">
        <div style={{ display: 'grid', gap: 0, border: `1px solid ${T.paperEdge}` }}>
          <LedgerEntry id="LE/0041830" op="ADMIT"   subject="analytics.dim_customer"               at="09:14:21Z" owner="growth"        state="verified"  classification="internal" />
          <LedgerEntry id="LE/0041831" op="PROPOSE" subject="analytics.fct_refunds"                at="09:14:44Z" owner="worm/agent"    state="pending"   classification="internal" />
          <LedgerEntry id="LE/0041833" op="DELETE"  subject="staging.tmp_raw_exports"              at="09:15:18Z" owner="data-platform" state="contested" classification="restricted" />
        </div>
      </Section>

      <Caption style={{ marginTop: 18 }}>
        Ledger rows are mono. They are the record itself, rendered unaltered. Left rule encodes state — solid green (sealed), dashed gray (pending), solid sepia (contested). Everything else is metadata, faint and readable.
      </Caption>
    </ArtboardFrame>
  );
}
window.LedgerArtboard = LedgerArtboard;

// ──── Composed example + cover ────

function ComposedArtboard() {
  return (
    <ArtboardFrame>
      <ArtboardHeader index="10" kicker="Pl. X · Composition" title="All six primitives, assembled" />

      <div style={{ display: 'grid', gridTemplateColumns: '1.1fr 1fr', gap: 28 }}>
        <div>
          <Card variant="bound" kicker="— REGISTER" index="§ QUERY" title="New observation">
            <div style={{ display: 'grid', gap: 14, marginTop: 4 }}>
              <Input label="Subject" value="checkout.latency_ms" mono state="focus" />
              <Input label="Window" value="past 7 days" hint="Natural language accepted" />
              <Input label="Classification" value="INTERNAL" mono prefix="▸" />
            </div>
            <div style={{ marginTop: 18, display: 'flex', gap: 10 }}>
              <Button variant="field">Seal observation</Button>
              <Button variant="ghost">Preview</Button>
            </div>
          </Card>

          <div style={{ marginTop: 20 }}>
            <Card kicker="— LIVE" index="§ RATE" title="Worm activity">
              <GaugeBar kicker="— INGEST · THROUGHPUT" label="events sealed per minute" value={14237} unit="" min={0} max={20000} />
              <div style={{ height: 18 }} />
              <GaugeBar kicker="— QUALITY · FIDELITY" label="hashes reconciled" value={99.7} unit="%" min={95} max={100} />
            </Card>
          </div>
        </div>

        <div>
          <Card variant="plate" kicker="— RECENT" index="§ LEDGER" title="Past 4 entries"
            footer={<Meta>Hash-chain verified · sha256 tip d94e32b7…</Meta>}>
            <div style={{ border: `1px solid ${T.paperEdge}`, background: T.paper, marginTop: -4 }}>
              <LedgerEntry id="LE/0041830" op="ADMIT"   subject="analytics.dim_customer"  at="09:14:21Z" owner="growth"        state="verified"  classification="internal"  size="sm" />
              <LedgerEntry id="LE/0041831" op="PROPOSE" subject="analytics.fct_refunds"   at="09:14:44Z" owner="worm/agent"    state="pending"   classification="internal"  size="sm" />
              <LedgerEntry id="LE/0041832" op="SEAL"    subject="analytics.dim_product"   at="09:15:02Z" owner="data-platform" state="verified"  classification="public"    size="sm" />
              <LedgerEntry id="LE/0041833" op="DELETE"  subject="staging.tmp_raw_exports" at="09:15:18Z" owner="data-platform" state="contested" classification="restricted" size="sm" />
            </div>
            <div style={{ marginTop: 14 }}>
              <Receipt density="footer" classification="internal" />
            </div>
          </Card>
        </div>
      </div>
    </ArtboardFrame>
  );
}
window.ComposedArtboard = ComposedArtboard;

function CoverArtboard() {
  return (
    <ArtboardFrame padding={56}>
      <div style={{ display: 'flex', flexDirection: 'column', height: '100%', position: 'relative' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <Meta>— WormBase · Pl. 00 · Cover</Meta>
          <Meta style={{ color: T.inkFaint }}>Vol. I · Field Notebook</Meta>
        </div>
        <div style={{ borderTop: `3px double ${T.ink}`, marginTop: 10 }} />

        <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '1.1fr 1fr', gap: 36, paddingTop: 32 }}>
          <div>
            <div style={{ fontFamily: T.serif, fontSize: 13, fontStyle: 'italic', color: T.inkSoft, marginBottom: 18 }}>
              A treatise on the living subject—
            </div>
            <h1 style={{
              fontFamily: T.serif, fontWeight: 400, fontSize: 72, lineHeight: 0.98,
              letterSpacing: -1.2, margin: 0, color: T.ink,
            }}>
              WORMBASE
            </h1>
            <div style={{ fontFamily: T.serif, fontStyle: 'italic', fontSize: 22, color: T.inkSoft, marginTop: 14, lineHeight: 1.3 }}>
              Institutional AI data agent · resident in Slack · proves every answer with a hash.
            </div>

            <div style={{ marginTop: 40 }}>
              <Meta style={{ marginBottom: 10 }}>— Contents · Pl. I – X</Meta>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 24px', fontFamily: T.serif, fontSize: 14, color: T.inkSoft }}>
                {['I · Palette', 'II · Typography', 'III · Measure', 'IV · Button', 'V · Input', 'VI · Card', 'VII · Receipt', 'VIII · Gauge', 'IX · LedgerEntry', 'X · Composition'].map((x) => (
                  <div key={x} style={{ display: 'flex', justifyContent: 'space-between', borderBottom: `1px dashed ${T.paperEdge}`, padding: '4px 0' }}>
                    <span>{x.split(' · ')[1]}</span>
                    <span style={{ fontFamily: T.mono, color: T.inkFaint }}>Pl. {x.split(' ·')[0]}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
            <WormPlate />
            <div style={{ marginTop: 14, fontFamily: T.serif, fontStyle: 'italic', fontSize: 13, color: T.inkSoft, textAlign: 'center', lineHeight: 1.45 }}>
              Vermis archivi <span style={{ fontStyle: 'normal', color: T.inkMute }}>·</span> the ledger-worm
              <div style={{ fontFamily: T.mono, fontSize: 10, letterSpacing: 0.6, color: T.inkFaint, marginTop: 4, fontStyle: 'normal' }}>
                PLATE FIG. 1 · APPEARS ONLY ON LANDING & ONBOARDING
              </div>
            </div>
          </div>
        </div>

        <div style={{ borderTop: T.rule, paddingTop: 10, marginTop: 20, display: 'flex', justifyContent: 'space-between' }}>
          <Meta>— Published internally · 2026</Meta>
          <Meta style={{ color: T.inkFaint }}>v. 0.1 · FOR REVIEW</Meta>
        </div>
      </div>
    </ArtboardFrame>
  );
}
window.CoverArtboard = CoverArtboard;

// Placeholder for the one taxonomically-precise worm plate.
// Intentionally NOT a hand-drawn SVG "mascot" — this is a reference block
// marked as a commissioned naturalist illustration.
function WormPlate() {
  return (
    <div style={{
      width: 260, height: 280,
      border: `1px solid ${T.ink}`, background: T.paper, position: 'relative',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <div style={{
        position: 'absolute', inset: 12, border: `1px solid ${T.paperEdge}`,
        background: `repeating-linear-gradient(0deg, ${T.paper} 0 14px, ${T.paperDeep} 14px 15px)`,
      }} />
      <div style={{ position: 'relative', textAlign: 'center', fontFamily: T.mono, fontSize: 10, letterSpacing: 0.8, color: T.inkMute, padding: 16 }}>
        <div style={{ fontFamily: T.serif, fontStyle: 'italic', fontSize: 14, color: T.ink, marginBottom: 6 }}>
          [ naturalist plate ]
        </div>
        <div>COMMISSION · INK-ON-PAPER</div>
        <div style={{ marginTop: 4 }}>HAECKEL / AUDUBON REFERENCE</div>
        <div style={{ marginTop: 4, color: T.inkFaint }}>~ 1200×1400 · 2-color</div>
      </div>
      <div style={{ position: 'absolute', bottom: -1, left: 12, right: 12, height: 1, background: T.ink }} />
    </div>
  );
}
window.WormPlate = WormPlate;

// Shared small helpers
function Section({ label, children }) {
  return (
    <div style={{ marginBottom: 26 }}>
      <Meta style={{ marginBottom: 12 }}>{label}</Meta>
      {children}
    </div>
  );
}
function Row({ children }) {
  return <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', alignItems: 'flex-end' }}>{children}</div>;
}
function Stack({ label, children }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div>{children}</div>
      <div style={{ fontFamily: T.mono, fontSize: 9.5, letterSpacing: 0.7, color: T.inkFaint, textTransform: 'uppercase' }}>— {label}</div>
    </div>
  );
}
window.Section = Section; window.Row = Row; window.Stack = Stack;
