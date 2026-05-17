# wormbase-ledger

Append-only, hash-chained event ledger logically partitioned by `company_id` —
the substrate from which lake, memory, governance, and KPI tree are
materialized. Exposes the shared `write_primitive(propose, execute, verify,
resolve)` function used by every quadrant, plus `replay(company_id, until_ts)`
to rebuild projections to any timestamp.

Python-only; depended on by `worm-core`, `sim-harness`, `inference-router`,
`channel-adapter`, and the dashboard.

## Installation (dev)

```sh
cd packages/ledger
uv sync --extra dev   # or: pip install -e '.[dev]'
```

## Run tests

```sh
pytest                       # uses sqlite (offline, fast)
WORMBASE_TEST_DB_URL=postgresql+asyncpg://user:pw@host/db pytest  # uses Postgres
```

## Public API

```python
from wormbase_ledger import (
    Ledger, InMemoryLedger,        # async DB-backed and in-memory
    LedgerEntry, KIND_REGISTRY,    # Pydantic models, 20 kinds
    write_primitive,               # atomic propose/execute/verify/resolve
    KpiNode,                       # projection contract for P3↔P4
)
```

## Acceptance gates

| Gate | Test |
|---|---|
| Every entry kind has Pydantic model + DB table + round-trip test | `tests/test_entries_payloads.py` + `tests/test_entries_roundtrip.py` |
| `write_primitive` atomically writes a 4-entry sequence or rolls back | `tests/test_write_primitive.py` |
| `replay(company_id, until_ts)` produces bitwise-identical projections across 10 invocations | `tests/test_replay_determinism.py` |
| Hash chain verifies end-to-end with `wormbase verify` | `tests/test_cli_verify.py` + `tests/test_verify_chain_db.py` |

Exit criteria: `pytest && ruff check src tests && mypy src && wormbase verify --help`.
