import Link from "next/link";
import { Receipt } from "../../lib/receipts";
import { ProvenanceMarker } from "./ProvenanceMarker";
import { chipStyle, type ChipTone } from "../people/_styles";
import type {
  Classification,
  MaintenanceSignal,
  MaintenanceSignalKind,
  SourceRow as SourceRowModel,
} from "../../lib/ledger-client.types";

/**
 * Color-coded classification chip per PRD §5.5.
 *   public     → green (low risk)
 *   internal   → ink (default)
 *   confidential / restricted → sepia (warning)
 *   pii / regulated → ink + heavy weight (highest sensitivity)
 */
function classificationTone(c: Classification | null | undefined): ChipTone {
  if (!c) return "muted";
  if (c === "public") return "green";
  if (c === "pii" || c === "regulated" || c === "restricted") return "ink";
  if (c === "confidential") return "sepia";
  return "neutral";
}

/**
 * Medallion-cascade dot: bronze / silver / gold per Step 2 of the canonical
 * product arc (`docs/superpowers/specs/2026-04-26-wormbase-product-arc.md`).
 * A solid dot means the corresponding `emit_source_*` entry is on the ledger;
 * a hollow ring means the cascade hasn't reached that layer yet.
 */
function MedallionDot({
  label,
  active,
  color,
  testId,
}: {
  label: string;
  active: boolean;
  color: string;
  testId: string;
}) {
  return (
    <span
      data-testid={testId}
      data-active={active ? "true" : "false"}
      title={`${label}: ${active ? "complete" : "pending"}`}
      className="wb-mono"
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        fontSize: 10,
        textTransform: "uppercase",
        letterSpacing: "0.08em",
        color: active ? color : "var(--wb-color-hash-gray)",
      }}
    >
      <span
        aria-hidden
        style={{
          width: 8,
          height: 8,
          borderRadius: "50%",
          background: active ? color : "transparent",
          border: `1px solid ${active ? color : "var(--wb-color-hash-gray)"}`,
        }}
      />
      {label}
    </span>
  );
}

function MedallionStatus({ row }: { row: SourceRowModel }) {
  return (
    <div
      data-testid={`medallion-status-${row.sourceId}`}
      style={{ display: "flex", gap: 12, alignItems: "center" }}
    >
      <MedallionDot
        label="bronze"
        active={Boolean(row.bronzed)}
        color="#a06a2a"
        testId={`medallion-bronze-${row.sourceId}`}
      />
      <MedallionDot
        label="silver"
        active={Boolean(row.silvered)}
        color="#7a7d83"
        testId={`medallion-silver-${row.sourceId}`}
      />
      <MedallionDot
        label="gold"
        active={Boolean(row.golded)}
        color="#b58a1f"
        testId={`medallion-gold-${row.sourceId}`}
      />
    </div>
  );
}

/**
 * D5 — maintainer + classification + connector-kind row, sandwiched between
 * the medallion dots and the provenance marker. Renders dim metadata when
 * fields are absent (a freshly-proposed source has no maintainer yet).
 */
function SourceMetadataRow({ row }: { row: SourceRowModel }) {
  const classification = row.classification ?? row.receipt.classification;
  return (
    <div
      data-testid={`source-metadata-${row.sourceId}`}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        flexWrap: "wrap",
        fontSize: 11,
      }}
    >
      <span
        className="wb-mono"
        data-testid={`source-connector-kind-${row.sourceId}`}
        style={chipStyle("neutral")}
      >
        {row.kind}
      </span>
      <span
        className="wb-mono"
        data-testid={`source-classification-${row.sourceId}`}
        style={chipStyle(classificationTone(classification))}
      >
        {String(classification)}
      </span>
      <span
        className="wb-mono"
        style={{
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--wb-color-hash-gray)",
          fontSize: 10,
        }}
      >
        maintainer
      </span>
      {row.maintainerPersonId ? (
        <Link
          href={`/people/${row.maintainerPersonId}`}
          data-testid={`source-maintainer-${row.sourceId}`}
          className="wb-mono"
          style={{
            fontSize: 11,
            color: "var(--wb-color-aged-ink)",
            textDecoration: "underline",
            textDecorationColor: "var(--wb-color-botanical-green)",
            textUnderlineOffset: 2,
          }}
        >
          {row.maintainerName ?? row.maintainerPersonId}
        </Link>
      ) : (
        <span
          className="wb-mono"
          data-testid={`source-maintainer-${row.sourceId}`}
          style={{
            fontSize: 11,
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          unassigned
        </span>
      )}
      {row.ownerDomain ? (
        <>
          <span
            className="wb-mono"
            style={{
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray)",
              fontSize: 10,
            }}
          >
            domain
          </span>
          <Link
            href={`/domains#${row.ownerDomain}`}
            data-testid={`source-domain-${row.sourceId}`}
            className="wb-mono"
            style={{
              fontSize: 11,
              color: "var(--wb-color-aged-ink)",
              textDecoration: "underline",
              textDecorationColor: "var(--wb-color-botanical-green)",
              textUnderlineOffset: 2,
            }}
          >
            {row.ownerDomain}
          </Link>
        </>
      ) : null}
    </div>
  );
}

/**
 * Phase 3 Task 3D — lake-freshness chip surfaced on every source row.
 *
 * Reads `lastSeen` from `projection_sources.last_seen` (Wave G's v003
 * migration; populated by the lake-maintainer Reactivities). When the
 * field is null we render an honest "never seen" empty-state — the
 * worm hasn't fired against this source yet. When the field is
 * undefined (back-compat with pre-Wave-G fixtures and pre-3D ledger
 * folds) we fall back to `lastProfileTs` so existing rows stay
 * meaningful.
 */
function FreshnessChip({ row }: { row: SourceRowModel }) {
  const lastSeen = row.lastSeen;
  let label: string;
  let displayTs: string | null;
  let tone: ChipTone;
  if (lastSeen === null) {
    // Honest empty state: the maintainer hasn't fired against this
    // source yet. Don't synthesize a fake timestamp.
    label = "never seen";
    displayTs = null;
    tone = "muted";
  } else if (lastSeen === undefined) {
    // Pre-Wave-G fold: lastSeen wasn't surfaced. Fall back to
    // lastProfileTs so the row still carries a meaningful freshness
    // signal.
    label = "last seen";
    displayTs = row.lastProfileTs;
    tone = displayTs ? "neutral" : "muted";
  } else {
    label = "last seen";
    displayTs = lastSeen;
    tone = "neutral";
  }
  return (
    <span
      data-testid={`source-freshness-${row.sourceId}`}
      data-last-seen={lastSeen ?? ""}
      className="wb-mono"
      style={{
        ...chipStyle(tone),
        fontSize: 11,
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
      }}
      title={displayTs ?? "lake-maintainer has not fired against this source yet"}
    >
      <span
        style={{
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          fontSize: 10,
          color: "var(--wb-color-hash-gray)",
        }}
      >
        {label}
      </span>
      <span style={{ fontSize: 11 }}>
        {displayTs ?? (lastSeen === null ? "not yet" : "—")}
      </span>
    </span>
  );
}

/**
 * Phase 3 Task 3D — drift indicator. Reads `driftDetected` /
 * `driftReason` from the latest `emit_source_drift_detected` ledger
 * entry for this source.
 */
function DriftBadge({ row }: { row: SourceRowModel }) {
  if (!row.driftDetected) return null;
  const reason = row.driftReason ?? "schema or hash drift detected";
  return (
    <span
      data-testid={`source-drift-${row.sourceId}`}
      data-drift="true"
      className="wb-mono"
      title={reason}
      style={{
        ...chipStyle("sepia"),
        fontSize: 11,
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        fontWeight: 600,
      }}
    >
      <span aria-hidden style={{ fontSize: 12 }}>!</span>
      drift
    </span>
  );
}

const SIGNAL_LABELS: Record<MaintenanceSignalKind, string> = {
  staleness: "staleness",
  drift: "drift",
  classification_refresh: "classification",
  lineage_break: "lineage break",
};

const SIGNAL_TONES: Record<MaintenanceSignalKind, ChipTone> = {
  staleness: "muted",
  drift: "sepia",
  classification_refresh: "neutral",
  lineage_break: "ink",
};

/**
 * Phase 3 Task 3D — 30-day maintenance signal timeline. Each entry maps
 * to one `emit_source_*` ledger row written by the lake-maintainer.
 * Newest-first; we trim the visual to 6 most-recent so a chatty source
 * doesn't dominate the row.
 */
function MaintenanceTimeline({ row }: { row: SourceRowModel }) {
  const signals = row.maintenanceSignals;
  if (signals === undefined) return null;
  const visible = signals.slice(0, 6);
  return (
    <div
      data-testid={`source-maintenance-timeline-${row.sourceId}`}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        flexWrap: "wrap",
        fontSize: 11,
      }}
    >
      <span
        className="wb-mono"
        style={{
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          fontSize: 10,
          color: "var(--wb-color-hash-gray)",
        }}
      >
        maintenance · last 30d
      </span>
      {visible.length === 0 ? (
        <span
          className="wb-mono"
          style={{
            fontSize: 11,
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          no maintenance signals yet
        </span>
      ) : (
        visible.map((sig, i) => (
          <MaintenanceSignalChip
            key={`${sig.tool}-${sig.ts}-${i}`}
            row={row}
            signal={sig}
            index={i}
          />
        ))
      )}
      {signals.length > visible.length ? (
        <span
          className="wb-mono"
          style={{ fontSize: 10, color: "var(--wb-color-hash-gray)" }}
        >
          +{signals.length - visible.length} more
        </span>
      ) : null}
    </div>
  );
}

function MaintenanceSignalChip({
  row,
  signal,
  index,
}: {
  row: SourceRowModel;
  signal: MaintenanceSignal;
  index: number;
}) {
  return (
    <span
      data-testid={`source-maintenance-signal-${row.sourceId}-${index}`}
      data-kind={signal.kind}
      data-ts={signal.ts}
      className="wb-mono"
      title={`${signal.tool} · ${signal.ts}${
        signal.reason ? ` · ${signal.reason}` : ""
      }`}
      style={{
        ...chipStyle(SIGNAL_TONES[signal.kind]),
        fontSize: 10,
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
      }}
    >
      {SIGNAL_LABELS[signal.kind]}
    </span>
  );
}

/**
 * Identify the default local-lake row — the source the worm provisions
 * automatically at install (Block I2; provision_local_lake in
 * worm-core/write_actions.py). Distinguished by both connector kind and
 * provenance flow so a custom row labelled "local_lake" via
 * dashboard_form (a power-user case) does NOT pick up the banner styling.
 */
function isDefaultLocalLake(row: SourceRowModel): boolean {
  return (
    row.kind === "local_lake" &&
    row.addedViaFlow === "provisioned_at_install"
  );
}

export function SourceRow({ row }: { row: SourceRowModel }) {
  const isDefault = isDefaultLocalLake(row);
  return (
    <article
      data-testid={`source-${row.sourceId}`}
      data-default-local-lake={isDefault ? "true" : undefined}
      style={{
        border: "1px solid var(--wb-color-paper-edge)",
        borderLeft: isDefault
          ? "3px solid var(--wb-color-aged-ink)"
          : "1px solid var(--wb-color-paper-edge)",
        padding: 16,
        display: "flex",
        flexDirection: "column",
        gap: 10,
        background: "var(--wb-color-paper)",
      }}
    >
      {isDefault ? (
        <div
          data-testid={`source-default-banner-${row.sourceId}`}
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: "var(--wb-color-aged-ink)",
            fontStyle: "italic",
            paddingBottom: 4,
            borderBottom: "1px dashed var(--wb-color-paper-edge)",
          }}
        >
          default — yours from minute zero. bronze + silver + gold backed by
          your ledger.
        </div>
      ) : null}
      <header style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 13,
            color: "var(--wb-color-aged-ink)",
            wordBreak: "break-all",
          }}
        >
          {row.uri}
        </span>
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
            border: "1px solid var(--wb-color-hash-gray)",
            padding: "1px 6px",
          }}
        >
          {row.kind}
        </span>
        <DriftBadge row={row} />
        <span
          className="wb-mono"
          style={{
            marginLeft: "auto",
            fontSize: 11,
            color: "var(--wb-color-hash-gray)",
          }}
        >
          {row.rowCount.toLocaleString()} rows · profiled {row.lastProfileTs ?? "—"}
        </span>
      </header>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <MedallionStatus row={row} />
        <FreshnessChip row={row} />
      </div>

      <SourceMetadataRow row={row} />

      <MaintenanceTimeline row={row} />

      <ProvenanceMarker
        addedByPerson={row.addedByPerson}
        addedAt={row.addedAt}
        addedViaFlow={row.addedViaFlow}
        addedInResponseTo={row.addedInResponseTo}
      />

      <Receipt
        hash={row.receipt.hash}
        source={row.receipt.source}
        owner={row.receipt.owner}
        classification={row.receipt.classification}
        compact
      />
    </article>
  );
}
