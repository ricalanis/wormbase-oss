/**
 * SecurityPosture — Phase 4 Task 4E.
 *
 * Public unauthenticated security/trust panel composed onto the standalone
 * `/security` route. Surfaces the architectural proof points that already
 * exist as contract tests + doctrine — they are not marketing claims, they
 * are paths a reviewer can audit:
 *
 *   - Multi-tenant isolation     → tests/multitenant/test_cross_tenant_data_leak_python.py
 *   - Replay determinism         → hash-stability tests + worked example
 *   - Hash-chained ledger        → schema-evolution doctrine (PEVR cycle)
 *   - PII handling               → packages/governance/.../gates.py (PIIGate)
 *   - SOC-2 (in progress)        → honest "in progress" badge — never "certified"
 *   - Data export / right-to-delete → ledger-replay path; export tooling roadmap
 *   - Encryption                 → TLS in transit, Postgres at-rest
 *   - Inference data flow        → Kimi remote / cache locality (router source)
 *
 * Honesty rule (per task brief): "in progress" beats "certified"; "we use TLS"
 * beats "encrypted everything." Every claim names the artifact a reviewer can
 * open to verify it themselves.
 *
 * Field Notebook design: paper background, serif headlines, mono kickers,
 * receipt-style coda lines, hash-gray meta lines. Mirrors the language the
 * landing page already established.
 */
import type { CSSProperties, ReactNode } from "react";

interface ProofPoint {
  /** Slug for testid + DOM anchor. */
  slug: string;
  /** Roman numeral for the field-notebook plate effect. */
  numeral: string;
  /** Headline (serif). */
  title: string;
  /** Subhead (italic serif). */
  subtitle: string;
  /** Body — the honest claim. May contain JSX for inline citations. */
  body: ReactNode;
  /** Hash-receipt mono coda — what the reader can audit themselves. */
  receipt: string;
}

const PROOF_POINTS: ProofPoint[] = [
  {
    slug: "multi-tenant-isolation",
    numeral: "i",
    title: "Multi-tenant isolation",
    subtitle:
      "A tenant_a request never returns a tenant_b row. The contract is tested at every accessor.",
    body: (
      <>
        Every read accessor in worm-core takes a <code>company_id</code> filter
        and folds only that tenant&rsquo;s rows. A dynamic sweep discovers every
        GET route on the HTTP API and every Python module accessor that names{" "}
        <code>(ledger, company_id)</code>; each is driven with tenant A&rsquo;s
        auth and asserted not to leak any tenant B marker. The substrate
        primitive (
        <code>InmemoryLedger.fetch(company_id)</code>) is independently swept.
        The sweep is <strong>passing</strong> at HEAD and runs on every commit.
      </>
    ),
    receipt:
      "tests/multitenant/test_cross_tenant_data_leak_python.py · sweep · passing",
  },
  {
    slug: "replay-determinism",
    numeral: "ii",
    title: "Replay determinism",
    subtitle:
      "Replay the ledger to timestamp T and you get the same hashes, byte-for-byte.",
    body: (
      <>
        Every entry carries a SHA-256 receipt over its canonical JSON payload;
        the chain is built by feeding the previous receipt into the next
        entry&rsquo;s prefix. Replay from genesis produces the same hash
        sequence on any machine. The landing page&rsquo;s replay viewer renders
        a fixed window of a demo tenant&rsquo;s ledger SSR-side; the hash under
        each row is the byte-for-byte receipt the writer wrote. Worked example:
        a hash like <code className="wb-mono">a8989ece&hellip;</code> on row 47
        of run A equals the hash on row 47 of run B, given identical inputs.
      </>
    ),
    receipt:
      "hash-stability · receipt(N) = sha256(prev || canonical(payload_N)) · replayable from genesis",
  },
  {
    slug: "hash-chained-ledger",
    numeral: "iii",
    title: "Hash-chained ledger",
    subtitle:
      "PEVR cycles are append-only. Kinds are forever; fields are additive only.",
    body: (
      <>
        Every write — inference, source, KPI, decision, gate, message — passes
        through one primitive: <strong>propose &rarr; execute &rarr; verify
        &rarr; resolve</strong>. The cycle is the audit anchor; the chain is
        the evidence trail. The doctrine that governs how kinds evolve is
        public:{" "}
        <a
          href="https://github.com/wormbase/wormbase/blob/main/docs/superpowers/specs/2026-05-03-schema-evolution-doctrine.md"
          target="_blank"
          rel="noopener noreferrer"
          style={{ color: "var(--wb-color-aged-ink)", textUnderlineOffset: 3 }}
        >
          docs/superpowers/specs/2026-05-03-schema-evolution-doctrine.md
        </a>
        . Five rules — kinds are forever, fields are additive only, deprecation
        is retired-not-deleted, replay is graceful for unknown kinds, and the
        registry has a freeze-pause review.
      </>
    ),
    receipt:
      "PEVR · propose → execute → verify → resolve · 76 concrete kinds · chain replays from genesis",
  },
  {
    slug: "pii-handling",
    numeral: "iv",
    title: "PII handling",
    subtitle:
      "Pattern-matched at write time. Redacted before persistence. Match recorded; raw bytes never logged.",
    body: (
      <>
        The <code>PIIGate</code> compiles every ontology pattern (email, SSN,
        credit card with Luhn validation, IBAN, phone, etc.), redacts matches
        in place, and writes a <code>gate_fired</code> ledger entry with the
        SHA-256 of the original substring &mdash; never the substring itself.
        Source:{" "}
        <code className="wb-mono">
          packages/governance/src/wormbase_governance/gates.py
        </code>
        . Three sibling gates compose alongside it: a warmup gate (blocks
        active actions until the worm has enough schema knowledge), an
        interjection gate (≤3 clarifying questions per channel per UTC day), a
        knowledge gate (blocks answers that reference unknown ontology
        concepts).
      </>
    ),
    receipt:
      "PIIGate · regex + Luhn · redact in place · sha256(span) logged · raw never persisted",
  },
  {
    slug: "soc2",
    numeral: "v",
    title: "SOC-2 — in progress",
    subtitle:
      "We are not SOC-2 certified. We are working toward Type I in 2026 H2; Type II to follow.",
    body: (
      <>
        The honest claim: WormBase is in early-stage SOC-2 readiness. The
        substrate already produces the audit primitives a SOC-2 auditor
        expects &mdash; append-only ledger, hash receipts, gate-fire records,
        per-tenant isolation under contract test. The org-side controls
        (background checks, formal incident response, vendor-management
        program) are being built in parallel. We will publish the Type I
        report when issued; until then, anyone claiming WormBase is
        &ldquo;SOC-2 certified&rdquo; is mistaken.
      </>
    ),
    receipt:
      "soc2 · type i · target 2026 h2 · status in progress · no audit report issued",
  },
  {
    slug: "export-delete",
    numeral: "vi",
    title: "Data export & right-to-delete",
    subtitle:
      "The substrate supports both. The export tooling is roadmap; the path is honest.",
    body: (
      <>
        Every tenant&rsquo;s data is the union of their ledger rows plus their
        connected lake. <strong>Export</strong> is a ledger fetch under the
        tenant&rsquo;s <code>company_id</code> followed by a connector-driven
        lake snapshot — the substrate primitives exist; the customer-facing
        export CLI is Phase 4 polish. <strong>Delete</strong> is a tombstone
        write (<code>emit_tenant_deletion_requested</code>) plus a scheduled
        purge of all tenant rows + cache entries; lake deletion is a connector
        call on the customer&rsquo;s store. Receipts of the deletion itself
        survive in a separate audit ledger (the deletion is auditable; the
        deleted data is gone).
      </>
    ),
    receipt:
      "export · ledger fetch + lake snapshot · delete · tombstone + purge · receipts of deletion preserved",
  },
  {
    slug: "encryption",
    numeral: "vii",
    title: "Encryption",
    subtitle:
      "TLS 1.2+ on every wire. At rest is handled by the database (Postgres) and the cache.",
    body: (
      <>
        TLS 1.2+ is enforced on every external request — Stripe, Slack,
        OAuth, OpenClaw, Kimi inference. Internal worm-core / dashboard /
        inference traffic on a SaaS deployment runs inside one VLAN; we treat
        TLS-on-VLAN as a defense-in-depth layer rather than the only barrier.
        At-rest encryption is provided by the storage substrate: Postgres
        (with disk-level encryption supplied by the host) for the ledger and
        projections; the SQLite inference cache lives on encrypted disk on
        the inference host. We do not run a custom envelope-encryption layer;
        we trust the database and the host.
      </>
    ),
    receipt:
      "tls 1.2+ in transit · postgres at-rest · sqlite cache on encrypted disk · no custom envelope",
  },
  {
    slug: "inference-data-flow",
    numeral: "viii",
    title: "Inference data flow",
    subtitle:
      "Where prompts go. What gets cached. What never leaves your VLAN.",
    body: (
      <>
        The router splits inference architecturally. <strong>Kimi</strong>{" "}
        (frontier reasoning) is called via Ollama Cloud; prompts cross the
        public internet under TLS. <strong>Gemma</strong> (commodity
        embeddings, classification, summarization, PII detection) is called
        on a private VLAN inference endpoint; on Enterprise tenants the
        endpoint runs inside the customer&rsquo;s VLAN and prompts never leave
        the customer perimeter. The cache is keyed on canonical request shape
        and lives next to the router; cache hits are tagged{" "}
        <code>served_by=&quot;cache&quot;</code> in the audit row. Source:{" "}
        <code className="wb-mono">
          packages/inference-router/src/wormbase_inference/router.py
        </code>
        . Every call writes one PEVR cycle ending in{" "}
        <code>inference_served</code> &mdash; prompt locality, fallback
        events, and cache hits are all audit-visible.
      </>
    ),
    receipt:
      "kimi · public api · tls · gemma · private vlan · cache local · inference_served · pevr · audit-visible",
  },
];

const SECURITY_CONTACT_MAILTO =
  "mailto:security@wormbase.io" +
  "?subject=" +
  encodeURIComponent("WormBase security disclosure") +
  "&body=" +
  encodeURIComponent(
    "Hi WormBase security team,\n\n" +
      "I'd like to disclose a finding.\n\n" +
      "Affected component:\nReproduction:\nImpact:\n\n" +
      "Thanks for the responsible-disclosure path.",
  );

export function SecurityPosture() {
  return (
    <section
      data-testid="security-section"
      aria-labelledby="security-headline"
      style={sectionStyle}
    >
      <div style={innerStyle}>
        <p className="wb-mono" style={eyebrowStyle}>
          plate vi · trust &amp; security
        </p>
        <h2 id="security-headline" data-testid="security-headline" style={headlineStyle}>
          Trust the receipts, not the marketing.
        </h2>
        <p style={subheadStyle}>
          Every claim below names the contract test, the doctrine, or the
          source file you can open to verify it. Where a control is in
          progress, we say so &mdash; &ldquo;in progress&rdquo; beats
          &ldquo;certified&rdquo; when only one of them is true.
        </p>

        <ul style={proofListStyle}>
          {PROOF_POINTS.map((p) => (
            <li
              key={p.slug}
              data-testid={`proof-${p.slug}`}
              id={`proof-${p.slug}`}
              style={proofCardStyle}
            >
              <header style={proofHeaderStyle}>
                <span className="wb-mono" style={proofNumeralStyle}>
                  plate {p.numeral}
                </span>
                <h3 style={proofTitleStyle}>{p.title}</h3>
                <p style={proofSubtitleStyle}>{p.subtitle}</p>
              </header>
              <p style={proofBodyStyle}>{p.body}</p>
              <p className="wb-mono" style={proofReceiptStyle}>
                {p.receipt}
              </p>
            </li>
          ))}
        </ul>

        <div style={contactBlockStyle}>
          <p className="wb-mono" style={contactKickerStyle}>
            responsible disclosure
          </p>
          <p style={contactBodyStyle}>
            Found a security issue? Email{" "}
            <a
              data-testid="security-contact"
              href={SECURITY_CONTACT_MAILTO}
              rel="noopener external"
              style={{
                color: "var(--wb-color-aged-ink)",
                textUnderlineOffset: 3,
              }}
            >
              security@wormbase.io
            </a>
            . We acknowledge within one business day, triage within three, and
            credit the reporter (with permission) in the post-mortem ledger
            entry.
          </p>
        </div>

        <p className="wb-mono" style={fineprintStyle}>
          this page is the product&rsquo;s honest posture · last reviewed
          2026-05-03 · receipts.wormbase.io
        </p>
      </div>
    </section>
  );
}

const sectionStyle: CSSProperties = {
  width: "100%",
  padding: "96px 24px",
  background: "var(--wb-color-paper)",
  borderTop: "1px solid var(--wb-color-rule-line)",
};

const innerStyle: CSSProperties = {
  maxWidth: 1080,
  margin: "0 auto",
  display: "flex",
  flexDirection: "column",
  gap: 24,
};

const eyebrowStyle: CSSProperties = {
  margin: 0,
  fontSize: 11,
  letterSpacing: "0.24em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
};

const headlineStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: "clamp(28px, 3.4vw, 40px)",
  fontWeight: 600,
  color: "var(--wb-color-aged-ink)",
  letterSpacing: "-0.012em",
  lineHeight: 1.15,
  maxWidth: 820,
};

const subheadStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: "var(--wb-text-md)",
  color: "var(--wb-color-aged-ink-soft)",
  lineHeight: 1.55,
  maxWidth: 720,
};

const proofListStyle: CSSProperties = {
  listStyle: "none",
  margin: "32px 0 0",
  padding: 0,
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
  gap: 16,
  alignItems: "stretch",
};

const proofCardStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 12,
  padding: "24px 22px",
  background: "var(--wb-color-paper)",
  border: "1px solid var(--wb-color-rule-line)",
  borderRadius: 2,
};

const proofHeaderStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 6,
};

const proofNumeralStyle: CSSProperties = {
  fontSize: 10,
  letterSpacing: "0.24em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
};

const proofTitleStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: "var(--wb-text-lg)",
  fontWeight: 600,
  color: "var(--wb-color-aged-ink)",
};

const proofSubtitleStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontStyle: "italic",
  fontSize: "var(--wb-text-sm)",
  color: "var(--wb-color-aged-ink-soft)",
  lineHeight: 1.5,
};

const proofBodyStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: "var(--wb-text-sm)",
  color: "var(--wb-color-aged-ink)",
  lineHeight: 1.55,
  flex: 1,
};

const proofReceiptStyle: CSSProperties = {
  margin: "12px 0 0",
  paddingTop: 12,
  borderTop: "1px solid var(--wb-color-rule-line)",
  fontSize: 10,
  letterSpacing: "0.04em",
  color: "var(--wb-color-hash-gray)",
  lineHeight: 1.55,
  wordBreak: "break-word",
};

const contactBlockStyle: CSSProperties = {
  marginTop: 32,
  padding: "20px 22px",
  background: "var(--wb-color-paper-deep)",
  border: "1px solid var(--wb-color-rule-line)",
  borderRadius: 2,
  display: "flex",
  flexDirection: "column",
  gap: 8,
};

const contactKickerStyle: CSSProperties = {
  margin: 0,
  fontSize: 10,
  letterSpacing: "0.24em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
};

const contactBodyStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: "var(--wb-text-sm)",
  color: "var(--wb-color-aged-ink)",
  lineHeight: 1.55,
};

const fineprintStyle: CSSProperties = {
  margin: "32px 0 0",
  fontSize: 10,
  letterSpacing: "0.06em",
  color: "var(--wb-color-hash-gray)",
  textAlign: "center",
};
