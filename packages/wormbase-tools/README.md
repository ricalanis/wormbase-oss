# wormbase-tools

OSS audit toolkit for WormBase. Replay a frozen ledger snapshot and
reproduce KPI values bit-for-bit, without the hosted plane.

```bash
pip install wormbase-tools
wormbase-tools replay snapshot.jsonl --tenant <id> --to kpi_q3_revenue
```

See `docs/oss-audit-replay.md` (in the WormBase monorepo) for the
auditor-facing usage guide.

## Why pure-Python

An auditor must be able to verify a tenant's KPIs without the hosted
plane: no Postgres, no asyncpg, no SQLAlchemy, no dashboard, no
cloudflared, no inference router. Every dependency in `pyproject.toml`
is a hard runtime requirement of the replay path. The hash chain is
re-implemented byte-compatibly with `wormbase-ledger`; KPI projection
folds are vendored from `wormbase-core` with the seam documented in
`src/wormbase_tools/projections/__init__.py`.

## What it does

1. Load the JSONL ledger snapshot.
2. Verify the hash chain end-to-end. Fail-closed on any break.
3. Filter entries to the requested tenant.
4. Fold KPI projections in pure Python.
5. Emit the requested KPI value on stdout.

Exit 0 = success, KPI value printed.
Exit 1 = chain break, malformed snapshot, or KPI not found
        (diagnostic to stderr).

## License

Apache-2.0.
