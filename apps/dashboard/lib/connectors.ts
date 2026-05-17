/**
 * /lake/connectors read-side accessor — L3 Sub-wave D (2026-05-29).
 *
 * Reads two surfaces:
 *
 *   1. The Connector registry (the catalog of kinds the platform knows
 *      how to talk to). Source of truth is the Python registry in
 *      ``packages/connectors/src/wormbase_connectors/`` exposed via
 *      worm-core's ``GET /api/v1/connectors`` endpoint.  We forward via
 *      the dashboard proxy at ``/api/v1/connectors/list``. On worm-core
 *      unreachable we fall back to the static catalog in
 *      ``connectors-catalog.ts`` so the marketplace shell still renders
 *      honestly (with a banner noting "registry unreachable, showing
 *      cached catalog").
 *
 *   2. The per-tenant connection state — which connector kinds have
 *      active sources, which are disconnected. Read from
 *      ``getSources()`` (folded ledger projection of source_proposed →
 *      source_connected).
 *
 * The marketplace shell groups rows by status (PRODUCTION / PREVIEW /
 * COMING SOON). The "Add Source..." button points to the existing
 * ``/sources/new`` connector-picker page where the actual form lives.
 */

import { headers } from "next/headers";
import {
  CONNECTOR_CATALOG,
  type ConnectorCatalogEntry,
} from "./connectors-catalog";
import {
  type ConnectorProbe,
  type ConnectorProbeState,
  probeConnectors,
} from "./connector-probes";
import { getSources } from "./ledger-client";

export type ConnectorStatus = "production" | "preview" | "coming_soon";
export type ConnectionState = "connected" | "disconnected" | "available";
export type { ConnectorProbeState };

/**
 * One row in the /lake/connectors marketplace shell.
 *
 * ``connectionState``:
 *   * ``connected``    — at least one active source of this kind exists
 *     for the tenant.
 *   * ``available``    — connector kind is always available (csv_local,
 *     wire-driven channel adapters); no per-tenant config required.
 *   * ``disconnected`` — connector kind is production-ready but has no
 *     active source for this tenant. Shows an "Add Source" affordance.
 */
export interface ConnectorCatalogRow {
  kind: string;
  label: string;
  description: string;
  status: ConnectorStatus;
  statusNote: string;
  capabilities: string[];
  connectionState: ConnectionState;
  /** How many active sources of this kind exist for the tenant. */
  activeSourceCount: number;
  /**
   * Tenant-side probe result — Sub-wave D. ``null`` when probes were
   * skipped (e.g. registry unreachable + static fallback). The page
   * renders a neutral badge in the ``null`` case.
   */
  probe?: ConnectorProbe | null;
}

export interface ConnectorCatalog {
  /** All rows, grouped by status. */
  production: ConnectorCatalogRow[];
  preview: ConnectorCatalogRow[];
  comingSoon: ConnectorCatalogRow[];
  /** True when the catalog was read from the static fallback. */
  registryUnreachable: boolean;
  /** Error text surfaced in the banner when registryUnreachable. */
  registryError: string | null;
  /** URL of the upstream worm-core registry (for the debug-link). */
  upstreamUrl: string;
}

// ─── Internal types ───────────────────────────────────────────────────────

interface RegistryEntry {
  kind: string;
  label?: string;
  status: ConnectorStatus | string;
  status_note?: string;
  capabilities?: string[];
  classification_hints?: string[];
}

interface RegistryResponse {
  kinds?: RegistryEntry[];
}

// ─── Helpers ──────────────────────────────────────────────────────────────

function normalizeStatus(raw: string): ConnectorStatus {
  if (raw === "production" || raw === "preview" || raw === "coming_soon") {
    return raw;
  }
  return "coming_soon";
}

function staticEntryFor(kind: string): ConnectorCatalogEntry | undefined {
  return CONNECTOR_CATALOG.find((c) => c.kind === kind);
}

function toRow(
  entry: RegistryEntry,
  activeCount: number,
): ConnectorCatalogRow {
  const staticEntry = staticEntryFor(entry.kind);
  const status = normalizeStatus(entry.status);
  const label = entry.label ?? staticEntry?.label ?? entry.kind;
  const statusNote = entry.status_note ?? staticEntry?.statusNote ?? "";
  const description = staticEntry?.description ?? statusNote;
  const capabilities = entry.capabilities ?? staticEntry?.capabilities ?? [];

  // csv_local is always-available — the worm profiles dropped files
  // without a per-tenant config step. Same model for wire-driven
  // channel adapters when they show up in the registry.
  const alwaysAvailable = entry.kind === "csv_local";

  let connectionState: ConnectionState;
  if (status === "coming_soon") {
    connectionState = "disconnected";
  } else if (activeCount > 0) {
    connectionState = "connected";
  } else if (alwaysAvailable) {
    connectionState = "available";
  } else {
    connectionState = "disconnected";
  }

  return {
    kind: entry.kind,
    label,
    description,
    status,
    statusNote,
    capabilities,
    connectionState,
    activeSourceCount: activeCount,
  };
}

function staticToRow(
  entry: ConnectorCatalogEntry,
  activeCount: number,
): ConnectorCatalogRow {
  return toRow(
    {
      kind: entry.kind,
      label: entry.label,
      status: entry.status,
      status_note: entry.statusNote,
      capabilities: entry.capabilities,
    },
    activeCount,
  );
}

const DEFAULT_WORM_CORE_BASE = "http://worm-core:8910";

function wormCoreBaseUrl(): string {
  return (
    process.env.WORMBASE_LEDGER_API_BASE ?? DEFAULT_WORM_CORE_BASE
  ).replace(/\/+$/, "");
}

async function fetchRegistry(): Promise<{
  entries: RegistryEntry[];
  unreachable: boolean;
  error: string | null;
  url: string;
}> {
  let url: string;
  try {
    const h = await headers();
    const host = h.get("host") ?? "localhost:3000";
    const proto = h.get("x-forwarded-proto") ?? "http";
    url = `${proto}://${host}/api/v1/connectors/list`;
  } catch {
    // headers() throws outside RSC; fall back to direct upstream.
    url = `${wormCoreBaseUrl()}/api/v1/connectors`;
  }

  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      return {
        entries: [],
        unreachable: true,
        error: `worm-core returned ${res.status}: ${text.slice(0, 200)}`,
        url,
      };
    }
    const body = (await res.json()) as RegistryResponse;
    return {
      entries: Array.isArray(body.kinds) ? body.kinds : [],
      unreachable: false,
      error: null,
      url,
    };
  } catch (err) {
    return {
      entries: [],
      unreachable: true,
      error: (err as Error).message ?? String(err),
      url,
    };
  }
}

// ─── Public accessor ──────────────────────────────────────────────────────

/**
 * Fetch the marketplace-shell catalog for the given tenant.
 *
 * Strategy:
 *
 *   1. Hit the registry endpoint via the dashboard's
 *      ``/api/v1/connectors/list`` proxy.
 *   2. Fold ``getSources(companyId)`` into a per-kind active-source
 *      count so each row carries its connection state.
 *   3. Group by status: PRODUCTION / PREVIEW / COMING SOON.
 *   4. On registry unreachable, return the static
 *      ``CONNECTOR_CATALOG`` fallback so the page still renders + a
 *      banner explaining the unreachable state.
 */
export async function getConnectorCatalog(
  companyId: string,
): Promise<ConnectorCatalog> {
  const [registry, sources] = await Promise.all([
    fetchRegistry(),
    getSources(companyId).catch(() => []),
  ]);

  // Count active sources per connector kind. A SourceRow exists in
  // ``getSources()`` only after at least an emit_source_proposed has
  // landed; we treat any non-empty kind as "connected enough" to mark
  // the connector row green. The conservative reading would gate on
  // bronzed/silvered/golded flags, but for the marketplace shell the
  // existence of any active source is the right signal.
  const activeBySourceKind = new Map<string, number>();
  for (const s of sources) {
    const kind = (s as { kind?: string }).kind ?? "";
    if (kind) {
      activeBySourceKind.set(kind, (activeBySourceKind.get(kind) ?? 0) + 1);
    }
  }

  const entries = registry.unreachable
    ? CONNECTOR_CATALOG.map((e) =>
        staticToRow(e, activeBySourceKind.get(e.kind) ?? 0),
      )
    : registry.entries.map((e) =>
        toRow(e, activeBySourceKind.get(e.kind) ?? 0),
      );

  // Sub-wave D — per-row tenant-side probe. Skip probes entirely when
  // the registry was unreachable (the static fallback rows have no
  // wire to call against) so we don't double-fail the page. Skip
  // ``coming_soon`` rows (the worm-core probe endpoint already
  // returns ``unknown`` for them, but we save a network round-trip).
  let probeMap: Map<string, ConnectorProbe> = new Map();
  if (!registry.unreachable) {
    const probableKinds = entries
      .filter((e) => e.status !== "coming_soon")
      .map((e) => e.kind);
    if (probableKinds.length > 0) {
      probeMap = await probeConnectors(probableKinds).catch(
        () => new Map<string, ConnectorProbe>(),
      );
    }
  }
  for (const row of entries) {
    row.probe = probeMap.get(row.kind) ?? null;
  }

  const production = entries.filter((e) => e.status === "production");
  const preview = entries.filter((e) => e.status === "preview");
  const comingSoon = entries.filter((e) => e.status === "coming_soon");

  // Within each group sort connected-first, then by label for stable
  // ordering. The connected-first ordering puts what the tenant is
  // actively using at the top so the marketplace shell shows them
  // their own surface area before the catalog.
  const sortRows = (rows: ConnectorCatalogRow[]): ConnectorCatalogRow[] =>
    rows.sort((a, b) => {
      const aConnected = a.connectionState === "connected" ? 0 : 1;
      const bConnected = b.connectionState === "connected" ? 0 : 1;
      if (aConnected !== bConnected) return aConnected - bConnected;
      return a.label.localeCompare(b.label);
    });

  return {
    production: sortRows(production),
    preview: sortRows(preview),
    comingSoon: sortRows(comingSoon),
    registryUnreachable: registry.unreachable,
    registryError: registry.error,
    upstreamUrl: registry.url,
  };
}

// ─── Test hooks ───────────────────────────────────────────────────────────

export const __test__ = {
  toRow,
  staticToRow,
  normalizeStatus,
};
