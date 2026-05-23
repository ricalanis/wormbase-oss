# Source Connector Cheatsheet

> Operator quick-reference for wiring a new data source under time pressure.
> Read this when a customer says *"we use X"*.
>
> Cross-refs:
> - Spec: `docs/superpowers/specs/2026-05-23-altis-kickoff-readiness-design.md`
> - Kickoff runbook: `docs/superpowers/runbooks/2026-05-25-altis-kickoff-runbook.md`
> - Weekly-report template: `docs/superpowers/runbooks/weekly-report-template.md`

---

## §1 — Catalog (what's already in `packages/lake-surfaces/`)

**Native drivers** — in `packages/lake-surfaces/src/wormbase_lake_surfaces/`.

| `kind` | Status | Vendor / what it pulls | File | Secrets |
|---|---|---|---|---|
| `csv_local` | ✅ real | Local CSV files | `csv_local.py` | none |
| `http_csv` | ✅ real | CSV via HTTP URL | `http_csv.py` | none (or basic auth) |
| `s3_csv` | ✅ real | CSV in S3 | `s3_csv.py` | AWS credentials |
| `postgres` | ✅ real | Postgres table | `postgres.py` | DSN |
| `local_lake` | ✅ real | WormBase's own lake (self-loop) | `local_lake.py` | none |
| `snowflake` | ✅ real | Snowflake table | `snowflake.py` | account + creds |
| `bigquery` | ⚠️ skeletal | Google BigQuery | `bigquery.py` | service-account JSON |
| `gsheets` | ⚠️ skeletal | Google Sheets | `gsheets.py` | OAuth |
| `hubspot` | ⚠️ skeletal | HubSpot CRM (REST) | `hubspot.py` | bearer / API key |
| `linear` | ⚠️ skeletal | Linear (GraphQL) | `linear.py` | bearer |
| `notion` | ⚠️ skeletal | Notion API | `notion.py` | bearer |
| `salesforce` | ⚠️ skeletal | Salesforce | `salesforce.py` | OAuth |
| `stripe` | ✅ real | Stripe API | `stripe.py` | API key |
| `conversation_source` | (internal) | Lake's own conversation projections | `conversation_source.py` | n/a |
| `evidence_source` | (internal) | Lake's own evidence projections | `evidence_source.py` | n/a |
| `external_source` | (internal) | Generic external (catalog-mirror fallback) | `external_source.py` | n/a |

⚠️ **Skeletal = the driver class exists + appears in the dashboard picker, but actual ingestion is stubbed.** Picking one of these in production = "honest preview" surface; promotion to real requires filling in the driver methods. Check the file's docstring for the gap-list.

**MCP presets** — in `packages/lake-surfaces/src/wormbase_lake_surfaces/mcp_presets/`. All bearer-token auth, all real (the MCP server does the heavy lifting).

| `kind` | Server URL | File |
|---|---|---|
| `mcp:atlassian` | `https://mcp.atlassian.com/v1/mcp` | `atlassian_preset.py` |
| `mcp:github` | `https://api.githubcopilot.com/mcp/` | `github_preset.py` |
| `mcp:gworkspace` | `https://mcp.workspace.google.com/mcp` | `gworkspace_preset.py` |
| `mcp:hubspot` | `https://mcp.hubspot.com/mcp` | `hubspot_preset.py` |
| `mcp:linear` | `https://mcp.linear.app/mcp` | `linear_preset.py` |
| `mcp:notion` | `https://mcp.notion.com/mcp` | `notion_preset.py` |

**Choose MCP path when:** vendor's MCP exists + you want the vendor to own schema drift. **Choose native when:** no MCP, OR you need precise control over what's pulled.

---

## §2 — Wire-up procedure for an existing driver

The 4-stage canonical lifecycle (see `apps/worm-core/src/wormbase_core/source_builder.py:94`):

```
source_proposed → source_confirmed → source_connected → source_profiled
```

Each stage is a ledger entry; the `SourceBuilder` enforces ordering. After `source_connected`, lake-maintainer Reactivities auto-wire (drift / classification / staleness / lineage).

### The canonical command — `build_full_sequence`

`apps/worm-core/src/wormbase_core/source_builder.py:568` exposes `build_full_sequence(...)` — runs all four stages atomically for "I have credentials, just wire it." Use this for operator-driven wire-up:

```python
import asyncio
from uuid import uuid4
from wormbase_channel_adapter.tenant import tenant_to_company_uuid
from wormbase_ledger import Ledger
from wormbase_core.source_builder import SourceBuilder, SourceProposal
from wormbase_lake_maintainer.registry import SourceRegistry
import os

async def main():
    ledger = Ledger(os.environ["WORMBASE_LEDGER_DSN"])
    tenant = "altis"
    company_id = tenant_to_company_uuid(tenant)

    builder = SourceBuilder(
        ledger=ledger,
        source_registry=SourceRegistry(),
        reactivity_registry=None,  # or wire one if you want maintenance auto-fire
    )

    proposal = SourceProposal(
        correlation_id=str(uuid4()),
        company_id=company_id,
        kind="mcp:hubspot",                     # or "mcp:notion", "csv_local", ...
        uri="https://mcp.hubspot.com/mcp",      # vendor-defined; mirrors driver's expected URI shape
        proposed_by="ricardo-manual",
        added_via_flow="dashboard_form",        # provenance: where the proposal came from
        added_in_response_to="ruben_mentioned_hubspot_in_kickoff_group_msg_id_X",
        # Plus driver-specific config in `config_payload`:
        config_payload={"portal_id": "12345"},
    )

    seq = await builder.build_full_sequence(
        proposal,
        confirmed_by="ricardo-manual",
        credential_ref="vault://altis/hubspot/bearer_token",  # see §"Where to put secrets" below
    )
    print(f"source connected; final ledger seq {seq}")

asyncio.run(main())
```

(Verify the actual `build_full_sequence` signature — it may differ; this is the conceptual shape.)

### Where to put secrets

Two patterns supported in the repo:

1. **Vault path** — e.g. `vault://altis/hubspot/bearer_token`. The `CredentialBroker` resolves at sampling time. Use this for production-ish creds; doesn't leak into ledger.
2. **Env var, namespaced** — e.g. `WORMBASE_HUBSPOT_BEARER_TOKEN_ALTIS`. Simpler for dev; the entrypoint.sh-style render picks it up.

The `credential_ref` in the proposal points at whichever you used.

### Verify ingestion

```bash
# After build_full_sequence completes, the source should start producing
# catalog_table_imported entries within the next maintainer pass.
uv run --directory apps/worm-core wormbase-ledger-recent \
  --tenant altis --kind catalog_table_imported --limit 20
```

If nothing appears within ~5 minutes: probe the connector's runtime state via the worm-core HTTP API:

```bash
curl -H "X-Tenant: altis" \
     "http://localhost:8080/api/v1/connectors/<kind>/probe"
# returns {"state": "works|degraded|failed|unknown", "message": "..."}
```

Implemented at `apps/worm-core/src/wormbase_core/http_api.py:6999` (`get_connector_probe`).

### List what's available to a tenant

```bash
curl "http://localhost:8080/api/v1/connectors"  # all registered drivers
```

Implemented at `apps/worm-core/src/wormbase_core/http_api.py:7528` (`get_connectors`).

---

## §3 — Adding a NEW driver (when the customer mentions something not in the catalog)

### Path A — MCP preset (when the vendor has a public MCP server)

**Effort: ~30 lines, 30 minutes.** Use this for any vendor with a published MCP endpoint (e.g. Fireflies-if-they-ever-ship-MCP, Read.AI-future, Salesforce-once-MCP-GA).

1. Copy an existing preset as the template:
   ```bash
   cp packages/lake-surfaces/src/wormbase_lake_surfaces/mcp_presets/hubspot_preset.py \
      packages/lake-surfaces/src/wormbase_lake_surfaces/mcp_presets/<vendor>_preset.py
   ```

2. Edit it. Skeleton:
   ```python
   from ..mcp import MCPServerConfig, make_mcp_preset

   <VENDOR>_CONFIG = MCPServerConfig(
       kind="mcp:<vendor>",
       server_url="https://mcp.<vendor>.com/mcp",
       required_secrets=("bearer_token",),
       optional_secrets=(),
       classification_hints=("pii",),       # if it pulls PII; else omit
       scopes=("scope.read", ...),
       description="One-liner about what this source pulls.",
   )
   <Vendor>MCPSurfaceDriver = make_mcp_preset(<VENDOR>_CONFIG, status="preview")
   __all__ = ["<VENDOR>_CONFIG", "<Vendor>MCPSurfaceDriver"]
   ```

3. Import it eagerly in `packages/lake-surfaces/src/wormbase_lake_surfaces/__init__.py` (alongside the other preset imports) so `@register_surface_driver` fires at package import.

4. Add a single test asserting the driver registers:
   ```python
   def test_<vendor>_preset_registers():
       from wormbase_lake_surfaces import default_registry
       assert "mcp:<vendor>" in default_registry().kinds()
   ```

5. Done — the dashboard picker, `/api/v1/connectors`, and `SourceBuilder` all see it.

### Path B — Native driver (no MCP available)

**Effort: 3-6h depending on vendor API complexity.** Use when the vendor only has REST/GraphQL.

1. Pick a template based on the vendor's API shape:
   - REST + bearer auth (Hubspot-like) → use `hubspot.py` as template
   - GraphQL (Linear-like) → use `linear.py`
   - Local file or HTTP CSV → use `csv_local.py` / `http_csv.py`
   - DB connection (Postgres-like) → use `postgres.py` or `snowflake.py`

2. Implement the `SurfaceDriver` Protocol from `base.py` — methods: `kind` (str), `probe(...)`, `sample(...)`, `discover(...)`, etc. Check the Protocol definition for the exact contract.

3. Register via `@register_surface_driver` at module level.

4. Eager-import in `__init__.py`.

5. Tests:
   - Driver registers under correct kind
   - `probe()` returns sensible state without real creds
   - `sample()` against a mocked HTTP response returns the expected shape

**Skeletal-first shortcut:** if you don't have time for the full native driver but want the driver in the picker (so it can be selected later when filled in), inherit from `SkeletalSurfaceDriver` in `_skeletal.py`. Several catalog entries already do this — they show in the picker but `probe` returns `state="unknown"` until the real methods land.

---

## §4 — Top-5 most-likely sources for Altis (priority list)

Based on the May 22 call + B2B-consultancy-uses-WhatsApp+Fireflies profile.

| Rank | Source | In catalog? | Effort to wire | Notes |
|---|---|---|---|---|
| 1 | **Read.AI (RID)** | 🔧 CLI (`wormbase-pull-readai`) shipping in this batch | Sprint 1: CLI exists, needs `READAI_API_KEY` from Poncho. Sprint 2: ~4-6h native `SurfaceDriver` in `lake-surfaces/`. | **PRIMARY for Altis** — Poncho's team runs on Read.AI (confirmed 2026-05-23). Mentioned explicitly on the May 22 call ("nos conectaríamos a RID"). |
| 2 | **Fireflies** | 🔧 CLI (`wormbase-pull-fireflies`) shipped at `670758b` | Sprint 2: ~1h MCP preset IF Fireflies ships public MCP; else ~4h native driver. | Ricardo's own tool, not Altis's. Useful for Ricardo's dogfooding meetings + future customers on Fireflies. |
| 3 | **Notion** | ✅ MCP preset `mcp:notion` (real) AND ⚠️ native skeletal | 30 min — use MCP preset; have Altis generate a bearer token via Notion's MCP Auth flow. | Likely to come up if Altis stores client docs in Notion. |
| 4 | **Google Workspace** | ✅ MCP preset `mcp:gworkspace` | 30 min — OAuth bearer. | Drive/Docs/Sheets/Calendar via one preset. Likely useful for client deliverables. |
| 5 | **Hubspot** | ✅ both `mcp:hubspot` (real MCP) AND ⚠️ native skeletal | 30 min — prefer MCP preset (vendor maintains schema). | Mentioned as common B2B-consultancy stack. |

**For rank 1 (Read.AI):** CLI ready, just needs the API key from Poncho. Demo it dry-run on the kickoff call to prove the integration is real, then run it weekly until the Sprint 2 SurfaceDriver lands.

**For rank 2 (Fireflies):** Ricardo-internal. Don't lead with it for Altis pitches.

**For ranks 3-5 (in catalog):** when Altis mentions them, you can wire in <1h. Quote that on the call.

---

## §5 — Quick decision tree

```
Customer mentions source X.
│
├─ Is X already in §1 catalog?
│   │
│   ├─ YES + status "real" → §2 wire-up procedure. 30 min.
│   │
│   ├─ YES + status "skeletal" → either:
│   │   (a) promote the skeletal driver (fill in methods) — 3-6h
│   │   (b) tell customer "in v1.5", use a manual import path meanwhile
│   │
│   └─ YES + MCP preset → §2 wire-up. 30 min. Customer needs to grant a bearer.
│
└─ NO →
    │
    ├─ Does vendor ship a public MCP server? → Path A (§3). 30 min.
    │
    └─ No MCP → Path B (§3) native driver. 3-6h. Or quick skeletal stub + promote later.
```

---

## §6 — What NOT to do under time pressure

- **Don't promise instant wire-up for unknown sources.** "I'll wire it within 48h" is honest; "by end of day" is not unless it's an MCP preset for a vendor with public MCP + customer has bearer ready.
- **Don't skip the `source_proposed → source_confirmed` audit trail** by writing directly to `source_connected`. The lake-maintainer Reactivities expect the full sequence; skipping breaks drift detection.
- **Don't put real creds in env vars without namespacing them per-tenant** (`WORMBASE_<VENDOR>_<KEY>_<TENANT>`). Cross-tenant cred bleed is a one-way trip in a multi-tenant ledger.
- **Don't add a new driver class outside `lake-surfaces/`.** The dashboard / `SourceBuilder` / probe API all read from `default_registry()`; drivers registered elsewhere won't appear.
