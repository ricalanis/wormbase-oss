# `/sources` — User guide

## What it does

The Sources tab lists every data source connected to the tenant's lake,
with per-source medallion freshness (bronze / silver / gold timestamps and
hashes), maintainer, owner domain, and classification. The default local
lake — auto-provisioned during install — lands at the top of the list with
a "yours from minute zero" banner; user-driven sources land below it,
sorted by recency.

This is the data engineer's daily surface. CFOs and CMOs read it weekly
when something's stale.

## First action

Add a new source via the connector picker:

1. Click **Add source** in the header. The button opens `/sources/new`.
2. The connector grid renders every registered Connector with its status
   badge — **production**, **preview**, or **coming_soon**. The status is
   honest; preview means the connector is wired but not yet
   smoke-tested against a real customer instance.
3. Click a connector card. The form is generated from the connector's
   JSON-schema config — for `postgres` you'll see host, port, database,
   user, password (or secrets reference). For `csv_local` you'll see a
   file picker.
4. Click **Test connection**. The form posts to
   `/api/v1/connectors/{kind}/test`; success displays a hash receipt
   (writes `emit_source_connection_tested`).
5. Click **Connect**. The orchestrator fires the four-stage cascade:
   `emit_source_proposed → emit_source_confirmed → emit_source_connected →
   emit_source_profiled`. Within ~5 seconds the new row appears on
   `/sources` with bronze landed.

## Advanced

- **Change classification** — click any row to open the
  `SourceDetailDrawer`. Edit classification (writes
  `emit_resource_role_assigned` for the new owner if you reassign, or
  `emit_classification_changed` if you only edit the level). Drawer
  closes; row updates without a page refresh.
- **Reprofile** — admin-only. Triggers a re-run of profile only (silver
  re-derives from cached bronze bytes; writes `emit_source_reprofile_requested`).
- **Cascade** — admin-only. Re-runs the full medallion pipeline
  (bronze → silver → gold). Use this after schema changes or when you've
  rotated credentials.
- **Archive** — soft-delete. Writes `emit_source_archived`. The row
  disappears from `/sources` but the bronze bytes and historical
  projections stay in the lake (replayable).
- **MCP-backed sources** — `mcp:notion`, `mcp:atlassian`, `mcp:linear`,
  `mcp:github`, `mcp:google_workspace`, `mcp:hubspot` show up alongside
  the direct-API connectors. Same Connector contract; underlying
  transport is MCP. See
  [MCP integration](../superpowers/specs/2026-04-27-mcp-integration.md).

## Behind the scenes

Each source is a fold of these ledger entries:

```
emit_source_proposed     (any of the six source-building flows)
emit_source_confirmed    (admin or auto-confirmed for trusted flows)
emit_source_connected    (auth handshake completed, AuthHandle stored)
emit_source_profiled     (Connector.profile returned, schema in projection)
emit_source_bronzed      (raw bytes hashed, bronze row written)
emit_source_silvered     (typed, classified, joined)
emit_source_golded       (business-ready aggregate)
emit_source_reprofile_requested  (when reprofile button clicked)
emit_source_archived     (soft delete)
```

The list view reads `projection_sources`. Each row carries
`bronze_hash` / `silver_hash` / `gold_hash` columns folded from the
respective `emit_*` entries; freshness badges (green ≤ 24h, amber ≤ 7d,
red older) are computed at render time.

The `/sources/new` page calls `/api/v1/connectors/list`, which proxies to
worm-core's `GET /api/v1/connectors` — the connector registry exposes
every registered class with its `kind`, `capability`, `status`, and JSON
schema.

## Source-building flows — the six triggers

| Flow | Trigger | Where it fires |
|---|---|---|
| `drop_and_profile` | File dropped in a connected channel | channel-adapter sees `file_shared`, writes `emit_file_received` → source-builder proposes |
| `credential_offered_in_dm` | Token / connection string pasted in worm DM | classifier flags the message → source-builder proposes |
| `mentioned_in_conversation` | "we should pull from X" in chat | relevance gate fires → worm proactively offers |
| `dashboard_form` | Manual add via `/sources/new` | this tab — power-user path |
| `kpi_gap_triggered` | Worm observes a KPI tree gap | autoresearch loop proposes |
| `lake_discovery` | Existing catalog walked at install | scheduled walk |

All six flows funnel into the same `propose → confirm → connect → profile
→ cascade` ledger sequence. The Connector handles per-source specifics;
the flows handle per-trigger specifics.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `/sources/new` empty grid | worm-core `/api/v1/connectors` unreachable | `make worm-restart`; check `WORMBASE_LEDGER_API_TOKEN` matches in both services |
| Test connection times out | Connector can't reach the source (firewall, expired creds) | Inspect `make worm-logs`; rotate creds |
| Cascade stalls at silver | Profiler crashed mid-run | `make worm-restart`; click the row's **Cascade** button |
| Default lake row missing | `provision_local_lake` failed during install | Re-run `wormbase demo seed --reset-first --tenant <id> --domain-pack <pack>` |
| Source disappears after refresh | Archive triggered by mistake | Restore via `wormbase ledger restore --resource <source_id>` (writes `emit_source_unarchived`) |
