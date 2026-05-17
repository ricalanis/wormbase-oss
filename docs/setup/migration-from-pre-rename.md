# Migration from pre-rename (continuous-lake / Wave D)

> 2026-05-17. Issued with [ADR-0013 (continuous lake philosophy)](../architecture/decisions/ADR-0013-continuous-lake-philosophy.md)
> and the [Wave D code rename](../superpowers/specs/2026-05-17-continuous-lake-philosophy-design.md).
>
> This doc is for external consumers of the WormBase MCP server,
> dashboard, and Python packages — early-adopter Claude Desktop /
> Cursor / Cline users, anyone embedding WormBase via `wormbase-agent-gateway`.

## TL;DR

The `Connector` vocabulary has been renamed to `SurfaceDriver` /
`lake-surface` across the codebase. The architectural commitment is
documented in [ADR-0013](../architecture/decisions/ADR-0013-continuous-lake-philosophy.md):
the lake is a continuous substrate; surfaces are kinds of faces of it,
not pipes feeding it.

Aliases are in place for one release. They will be removed at the
**v1.0 cutover** (~6 weeks from 2026-05-17, i.e. ~early July 2026).
Update callers before then.

## Python imports

| Old | New |
|---|---|
| `wormbase_connectors` | `wormbase_lake_surfaces` |
| `from wormbase_connectors import Connector` | `from wormbase_lake_surfaces import SurfaceDriver` |
| `from wormbase_connectors import register_connector` | `from wormbase_lake_surfaces import register_surface_driver` |
| `from wormbase_connectors import ConnectorRegistry` | `from wormbase_lake_surfaces import SurfaceDriverRegistry` |
| `from wormbase_connectors.stripe import StripeConnector` | `from wormbase_lake_surfaces.stripe import StripeSurfaceDriver` |
| (and the analogous renames for `postgres`, `snowflake`, `bigquery`, `s3_csv`, `http_csv`, `salesforce`, `hubspot`, `gsheets`, `notion`, `linear`, `csv_local`, `local_lake`, `_skeletal`, `mcp`) | |

> **No back-compat shim in Python.** The `wormbase_connectors` module
> no longer exists — imports must be updated.

## MCP tool names

No MCP tool name in the WormBase gateway contained "connector" at the
rename cut-over (tool names already use the `lake.*` / `decisions.*` /
`processes.*` / `data_products.*` namespaces). No aliases are required.

If a future rename of a `lake.*` tool to `surfaces.*` is undertaken,
the alias table at
`packages/wormbase-agent-gateway/src/wormbase_agent_gateway/aliases.py`
is the registration point. Aliases registered there route old → new in
both directions and surface in this doc.

## Dashboard URLs

| Old | New |
|---|---|
| `/lake/connectors` | `/lake/surfaces` |

External link integrations should follow up; an HTTP-level redirect
will not be wired in OSS (fresh-snapshot release, no inbound traffic
to preserve).

## Dashboard UI strings

User-facing label changes (no functional effect on integrations, but
docs / screenshots may need refreshing):

| Old | New |
|---|---|
| "Connectors" (tab label) | "Lake surfaces" |
| "Pick a connector" (picker title) | "Add a lake surface" |
| "Connector" (status pill noun) | "Surface" |
| "Add source" CTA | "Add a lake surface" |
| Empty-state copy: "connector registry unreachable" | "surface registry unreachable" |

## Database columns

No DB columns containing `connector_kind` / `connector_type` were
present at the rename cut-over (verified by grep across
`packages/ledger/src/wormbase_ledger/migrations/` and
`packages/*/src/*/projections/`). No additive migration was required.

## Why the rename?

See [ADR-0013](../architecture/decisions/ADR-0013-continuous-lake-philosophy.md).
TL;DR: "connector" frames the data-source primitive as a *pipe feeding
the lake*. The actual architecture is the opposite — the lake is a
continuous substrate, and the driver classes describe *faces of the
lake*. The rename aligns the code with the architecture-as-pitch and
removes the implicit "the lake is downstream of the connectors" frame.

## Questions

File an issue at the WormBase OSS repo or ping the WormBase pilot
channel. The alias-removal timeline is firm; the support window is
generous.
