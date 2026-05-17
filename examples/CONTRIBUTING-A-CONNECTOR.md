# Contributing a Connector

A literate, line-by-line walkthrough for adding a new data source to
WormBase. We'll build `parquet_local` from scratch — the exact file
that ships at `examples/connectors/parquet_local.py` — and finish by
running the conformance harness against it.

By the end you'll have:

- A working Connector implementation, ~60 lines of code
- A passing run of the six conformance invariants
- A mental model of how the source-builder calls into your code

This walkthrough assumes Python 3.10+, comfort with `async`/`await`,
and that you've used `pytest` before. No WormBase internals required.

---

## Table of contents

1. [What a Connector is, in plain language](#1-what-a-connector-is-in-plain-language)
2. [The five capabilities](#2-the-five-capabilities)
3. [Setting up a fresh repo](#3-setting-up-a-fresh-repo)
4. [Step 1 — the dataclasses](#4-step-1--the-dataclasses)
5. [Step 2 — the class skeleton](#5-step-2--the-class-skeleton)
6. [Step 3 — `authenticate`](#6-step-3--authenticate)
7. [Step 4 — `discover`](#7-step-4--discover)
8. [Step 5 — `profile`](#8-step-5--profile)
9. [Step 6 — `sample`](#9-step-6--sample)
10. [Step 7 — `watch`](#10-step-7--watch)
11. [Running the conformance harness](#11-running-the-conformance-harness)
12. [Customizing the harness](#12-customizing-the-harness)
13. [Skeletal connectors and `coming_soon`](#13-skeletal-connectors-and-coming_soon)
14. [Common mistakes](#14-common-mistakes)
15. [Next steps — landing your connector in the registry](#15-next-steps--landing-your-connector-in-the-registry)

---

## 1. What a Connector is, in plain language

A WormBase **Connector** is the bridge between a data source out in
the world (a Parquet file, a Postgres table, a Stripe API endpoint, a
Notion workspace) and the worm's data lake. The worm doesn't care
what kind of source it is — it cares that it can ask five questions
and get answers in a stable shape.

The five questions, in human terms:

1. *"Here are some credentials. Can you talk to this source?"* → `authenticate`
2. *"What's available in this source?"* → `discover`
3. *"Tell me about this specific resource — what columns, what types,
   how many rows?"* → `profile`
4. *"Show me a few bytes of actual data."* → `sample`
5. *"Stream me changes as they happen."* → `watch`

A Connector class answers all five. The worm wraps your class behind
a registry, so adding a connector is **a class plus a registry entry**
— nothing else in WormBase changes.

The Connector contract is duck-typed: as long as your class has the
right attribute names with the right return shapes, the worm will use
it. You don't need to import or subclass anything from WormBase. (The
conformance harness in `wormbase-tools-test` enforces this.)

---

## 2. The five capabilities

Each method has a tight contract. Here's the cheat-sheet:

| Method | Async | Inputs | Returns | Required? |
|---|---|---|---|---|
| `authenticate(secrets)` | yes | `SecretBundle` | `AuthHandle` | yes |
| `discover(handle)` | yes | `AuthHandle` | `list[ResourceProposal]` | yes (return `[]` if N/A) |
| `profile(handle, resource_id)` | yes | handle, str | `Profile` | for `production` status |
| `sample(handle, resource_id, n)` | yes | handle, str, int | `bytes` | for `production` status |
| `watch(handle, resource_id)` | yes (async generator) | handle, str | `AsyncIterator[Change]` | optional (yield nothing if N/A) |

Three rules carry across all five methods:

- **Idempotency.** Calling `discover()` twice in a row returns the
  same list in the same order. Calling `profile()` twice returns
  Profiles with the same `schema_hash`. Calling `sample(handle, rid,
  n)` twice with the same arguments returns identical bytes. The worm
  replays your connector during ledger replay, and replays must match.

- **No surprise side effects.** A Connector is a *read* surface.
  `discover` does not write to the source. `profile` does not insert
  metadata rows. `sample` does not advance any cursor.

- **Honest failure.** Bad credentials → `ValueError`. Resource not
  found → return `[]` from discover, or raise if profile/sample is
  called against a missing id. Skeletal connectors raise
  `NotImplementedError` from methods they don't support yet.

---

## 3. Setting up a fresh repo

You don't need to clone WormBase. A connector lives in any Python
package; the worm registers it later by class path.

```bash
mkdir my-connector && cd my-connector
python3 -m venv .venv
source .venv/bin/activate
pip install pyarrow wormbase-tools-test
```

Three deps:

- `pyarrow` — the data library we'll use for Parquet. Replace with
  whatever your source needs (`asyncpg` for Postgres,
  `snowflake-connector-python` for Snowflake, `httpx` for HTTP APIs).
- `wormbase-tools-test` — the conformance harness, including the
  pytest plugin we'll run at the end.
- `pytest` is pulled in transitively.

Create one file: `parquet_local.py`. We'll fill it in step by step.

---

## 4. Step 1 — the dataclasses

The Connector Protocol uses five dataclasses to shape its inputs and
outputs. You can either import them from `wormbase_lake_surfaces.types`
(if you're working inside the WormBase monorepo) or define them
locally. We'll define them locally so this file is fully self-contained.

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SecretBundle:
    """Opaque container for connector credentials."""
    payload: dict[str, Any]


@dataclass(frozen=True)
class AuthHandle:
    """Returned by ``authenticate()``. Used in subsequent calls."""
    connector_kind: str
    handle_id: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResourceProposal:
    """A resource discovered by ``discover()``."""
    resource_id: str
    name: str
    kind: str  # "table" | "file" | "endpoint" | ...
    classification_hint: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Profile:
    """Result of ``profile()``."""
    row_count: int | None
    column_count: int | None
    columns: list[dict[str, Any]]
    schema_hash: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Change:
    """Streaming change record from ``watch()``."""
    resource_id: str
    seq: int
    kind: str  # "insert" | "update" | "delete"
    payload: dict[str, Any]
```

Notes:

- All five are `frozen=True`. The Connector Protocol assumes hashable
  inputs and outputs because the ledger replays them. Mutable defaults
  use `field(default_factory=dict)`.
- The field **names** matter — the conformance harness checks them
  structurally. The order doesn't.
- You can rename your local dataclasses or import them from anywhere;
  the duck-typed harness doesn't care. We use these exact names so
  any Python data person reading the file recognizes the shapes
  immediately.

---

## 5. Step 2 — the class skeleton

```python
from collections.abc import AsyncIterator


class ParquetLocalConnector:
    """Connector for local Parquet files — discover, profile, sample."""

    kind: str = "parquet_local"
    capability: set[str] = {"discover", "profile", "sample"}
    classification_hints: list[str] = []
    status: str = "production"
    status_note: str = "Drop a .parquet file at the configured path; we'll profile it."
```

Five class attributes:

- **`kind`** — a stable string id. Used in the registry, surfaced in
  the dashboard's connector picker, written into ledger entries.
  Lowercase, snake_case, no spaces. Match the source name when in
  doubt: `parquet_local`, `postgres`, `stripe`, `snowflake`.

- **`capability`** — the subset of `{"discover", "profile", "sample",
  "watch"}` your implementation actually supports. We're skipping
  `watch` (Parquet files don't stream changes), so the set is just
  the first three. The dashboard surfaces this badge.

- **`classification_hints`** — an optional list of hint strings the
  classifier uses to default new sources to a sensible classification
  (e.g. `"pii_filename"` if your source flags PII columns by name).
  Empty list is fine.

- **`status`** — one of `"production"`, `"preview"`, `"coming_soon"`.
  Drives the connector picker's badge. `"production"` means every
  capability you declared works; `"preview"` means some capabilities
  raise `NotImplementedError`; `"coming_soon"` is a skeleton that
  exists only to prove the abstraction.

- **`status_note`** — a short, user-facing string the dashboard shows
  next to the badge. One sentence. No "TODO".

---

## 6. Step 3 — `authenticate`

`authenticate` validates the secret bundle's shape and returns a handle
the rest of the methods can use. For local files there's nothing to
authenticate against, but we still verify the path is well-formed:

```python
    async def authenticate(self, secrets: SecretBundle) -> AuthHandle:
        path = secrets.payload.get("path")
        if not path or not isinstance(path, str):
            raise ValueError("parquet_local requires {path: str}")
        return AuthHandle(
            connector_kind=self.kind,
            handle_id=path,
            extra={"path": path},
        )
```

Three things to notice:

1. **We `raise ValueError` for malformed bundles.** This is the day-one
   contract. The conformance harness asserts this directly: invariant
   2 calls `authenticate` with an empty bundle and expects a
   `ValueError` or `KeyError`. Don't return `None`. Don't return a
   half-formed handle.

2. **`handle_id` is non-secret.** Anything in `handle_id` shows up in
   logs, in error traces, in the ledger. For `parquet_local` the path
   is fine. For Stripe, use `account_id`, not the API key. Treat
   `handle_id` as PII-grade safe.

3. **`extra` is the connector's private bag.** The path lives there
   (along with anything else you need at runtime — connection pool
   keys, session tokens, refresh expiry timestamps). The worm never
   reads `extra`. You read it in `discover`/`profile`/`sample`/`watch`.

For real auth (Postgres, Snowflake, OAuth APIs) this method opens a
connection or validates a token. Cache the connection in `extra` if
your connector is short-lived, or in a module-level dict keyed by
`handle_id` if multiple methods share connections. Just remember:
**`extra` is never serialized**. If you need to persist state across
process boundaries, you need a different abstraction.

---

## 7. Step 4 — `discover`

`discover` lists what's at the source. For Parquet, the source is a
single file (or directory of parts), so we return one
`ResourceProposal`:

```python
    async def discover(self, handle: AuthHandle) -> list[ResourceProposal]:
        path = Path(handle.extra["path"])
        if not path.exists():
            return []
        return [
            ResourceProposal(
                resource_id=str(path),
                name=path.name,
                kind="file" if path.is_file() else "directory",
                classification_hint=None,
                metadata={
                    "size_bytes": _path_size(path),
                    "path": str(path),
                    "mimetype": "application/x-parquet",
                },
            )
        ]
```

(With a small helper for size:)

```python
def _path_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.iterdir() if p.is_file())
```

The `discover` contract:

- **Stable ordering across calls.** Conformance invariant 3. If your
  source returns rows in a non-deterministic order (a `dict`, an SQL
  query without `ORDER BY`), sort before returning. The worm replays
  `discover` during ledger replay; flicker breaks determinism.

- **`resource_id` is opaque to the worm but stable to you.** It's the
  string you'll receive in `profile`/`sample`/`watch`. Use a
  fully-qualified path: `schema.table`, `bucket/key`, `endpoint_name`.

- **`kind`** is a free-form string. Common values: `"file"`,
  `"directory"`, `"table"`, `"view"`, `"endpoint"`. The worm doesn't
  use this for routing — it's documentation.

- **Empty results are fine.** If the source has no resources, return
  `[]`. The worm handles the empty case gracefully.

- **`metadata`** is anything you want to surface to the dashboard:
  size, mtime, ETag, native id. Avoid putting secrets in there.

For Postgres `discover` would query `information_schema.tables`. For
Stripe, it would return a static list of API endpoints. The shape is
the same.

---

## 8. Step 5 — `profile`

`profile` answers "what's the shape of this resource?" — column names,
types, row count, a stable schema hash. For Parquet, `pyarrow` does
nearly all of this for us:

```python
import hashlib
import pyarrow.parquet as pq


    async def profile(self, handle: AuthHandle, resource_id: str) -> Profile:
        pf = pq.ParquetFile(resource_id)
        schema = pf.schema_arrow
        columns = [
            {
                "name": field.name,
                "dtype": str(field.type),
                "nullable": field.nullable,
            }
            for field in schema
        ]
        schema_hash = hashlib.sha256(
            ",".join(f"{c['name']}:{c['dtype']}" for c in columns).encode()
        ).hexdigest()[:16]
        return Profile(
            row_count=pf.metadata.num_rows,
            column_count=len(columns),
            columns=columns,
            schema_hash=schema_hash,
            extra={
                "path": resource_id,
                "row_groups": pf.metadata.num_row_groups,
            },
        )
```

The `profile` contract:

- **Idempotent.** Conformance invariant 4. Two calls with the same
  `(handle, resource_id)` must return Profiles with byte-identical
  `schema_hash` and equal `columns`. We compute the hash deterministically
  from the column list, so this is automatic for Parquet.

- **`schema_hash` is the schema-stability proxy.** The lake-builder
  uses it to detect schema drift between profile calls. Make it
  short (16 hex chars is fine) and stable: SHA256 of a canonical
  string representation of the column list usually works.

- **`columns` is `list[dict[str, Any]]`.** Each dict is shaped however
  your source describes a column. Common keys: `name`, `dtype`,
  `nullable`, `sample_values`, `null_count`. The dashboard renders
  whatever you put here; consistency across connectors helps user
  experience but isn't enforced.

- **`row_count` may be `None`.** Streaming sources don't know their
  row count. Connectors that do should populate it; connectors that
  don't should set `None`, not 0 or -1.

For SQL sources, `profile` runs `information_schema.columns` plus a
`SELECT COUNT(*)`. For HTTP APIs it does a `HEAD` request and parses
schema from a known endpoint. The shape is the same.

---

## 9. Step 6 — `sample`

`sample` returns up to `n` "units" of actual data, as raw bytes. The
unit is connector-specific: byte-streaming connectors (S3, HTTP, MCP)
treat `n` as a byte cap; record-paging connectors (Postgres, Snowflake,
Stripe) treat `n` as a record count and return whatever bytes that
many records serialize to.

For Parquet we'll go byte-cap so the conformance harness's strict
mode passes:

```python
    async def sample(
        self, handle: AuthHandle, resource_id: str, n: int
    ) -> bytes:
        pf = pq.ParquetFile(resource_id)
        if pf.metadata.num_row_groups == 0:
            return b""
        table = pf.read_row_group(0)
        out = bytearray()
        names = table.column_names
        for row_idx in range(table.num_rows):
            if len(out) >= n:
                break
            row = {name: table.column(name)[row_idx].as_py() for name in names}
            out.extend(_jsonl_encode(row))
        return bytes(out[:n])


def _jsonl_encode(row: dict[str, Any]) -> bytes:
    import json
    return (json.dumps(row, sort_keys=True, default=str) + "\n").encode("utf-8")
```

The `sample` contract:

- **Returns bytes.** Always. Even for binary sources. The dashboard
  decodes them per `mimetype` from `discover.metadata`.

- **Deterministic for the same `(handle, resource_id, n)`.**
  Conformance invariant 5. We use `read_row_group(0)` and JSON with
  `sort_keys=True` to guarantee stable output. If your source has a
  natural ordering (Parquet row groups, SQL `ORDER BY id LIMIT n`,
  S3 byte-range), use it.

- **Honors `n` as a best-effort cap.** For byte-cap connectors:
  `len(result) <= n`. For record-cap connectors: `result` contains at
  most `n` records, byte length unrestricted. Document which mode
  your connector uses; the conformance harness has a
  `--connector-byte-cap-strict` flag that switches between them.

---

## 10. Step 7 — `watch`

`watch` is the streaming surface. Day-one connectors usually skip it
(`watch` is post-day-one — CDC, file-watching, webhook subscription).
But the Protocol still requires the method to exist as an async
iterator. The trick: an empty async generator.

```python
    async def watch(
        self, handle: AuthHandle, resource_id: str
    ) -> AsyncIterator[Change]:
        # Pull-only; CDC is post-day-one. Yield nothing; iterator exits cleanly.
        if False:
            yield  # type: ignore[unreachable]
```

That `if False: yield` pattern is the canonical way to write an "empty
async generator" — Python recognizes the function as a generator
function (because `yield` is in the body) but never yields anything.
The conformance harness drains the iterator, gets zero changes, and
moves on.

When you do implement `watch`:

- It's an `async def` with `yield` statements (an async generator).
- It yields `Change` records one at a time as they arrive.
- It runs forever until cancelled. The worm wraps it in a task and
  cancels on shutdown; you should not catch `asyncio.CancelledError`.

---

## 11. Running the conformance harness

You've got a complete connector. Time to verify it. From the directory
containing `parquet_local.py`:

```bash
# Make a Parquet file to test against:
python -c "
import pyarrow as pa, pyarrow.parquet as pq
pq.write_table(pa.table({'id': [1,2,3], 'name': ['Alice','Bob','Carol']}), 'fixture.parquet')
"

# Tell the harness where the test fixture is:
cat > conftest.py <<'EOF'
import pytest
from parquet_local import SecretBundle


@pytest.fixture
def connector_valid_secrets():
    return SecretBundle({"path": "fixture.parquet"})


@pytest.fixture
def connector_invalid_secrets():
    return SecretBundle({})


@pytest.fixture
def connector_known_resource_id():
    return "fixture.parquet"
EOF

# Run:
pytest --connector parquet_local:ParquetLocalConnector -v
```

Expected output:

```
collected 6 items

::TestConnectorProtocolConformance::test_authenticate_valid_returns_authhandle PASSED
::TestConnectorProtocolConformance::test_authenticate_invalid_raises PASSED
::TestConnectorProtocolConformance::test_discover_stable_ordering PASSED
::TestConnectorProtocolConformance::test_profile_idempotent PASSED
::TestConnectorProtocolConformance::test_sample_deterministic PASSED
::TestConnectorProtocolConformance::test_watch_cancellable PASSED

============================== 6 passed in 0.06s ==============================
```

If any test fails, the failure message names the invariant and (where
relevant) prints the diff between the two calls. Fix the underlying
behavior and re-run; conformance is binary.

---

## 12. Customizing the harness

The harness ships sensible defaults but every fixture is overridable in
your `conftest.py`:

| Fixture | Default | Override when |
|---|---|---|
| `connector_valid_secrets` | `SecretBundle({})` | always — your connector needs real-shaped secrets |
| `connector_invalid_secrets` | `SecretBundle({})` | when an empty payload happens to be valid (rare) |
| `connector_known_resource_id` | first `discover()` result | when `discover()` returns `[]` (skeletal) or you want a specific resource |
| `connector_is_skeletal` | `True` if `connector.status == "coming_soon"` | when you want to assert skeletal contract regardless of status |
| `connector_sample_n` | 32, or `--connector-sample-n` | rarely; defaults are fine |
| `connector_byte_cap_strict` | False, or `--connector-byte-cap-strict` | True for byte-streaming connectors |

Two CLI flags also exist:

- `--connector-sample-n=N` — passes `N` as the third arg to `sample`.
- `--connector-byte-cap-strict` — asserts `len(sample) <= n` strictly
  (use for `s3_csv`, `http_csv`, MCP-style byte connectors; skip for
  Postgres, Snowflake, Stripe).

---

## 13. Skeletal connectors and `coming_soon`

Some connectors land in the registry as proof-of-abstraction stubs —
they exist so the dashboard's connector picker can show them, but
their `profile`/`sample`/`watch` methods raise `NotImplementedError`.
Set `status = "coming_soon"`:

```python
class FoobarConnector:
    kind = "foobar"
    capability: set[str] = set()
    classification_hints: list[str] = []
    status = "coming_soon"
    status_note = "Foobar API connector coming Q3 2026."

    async def authenticate(self, secrets):
        if "token" not in secrets.payload:
            raise ValueError("foobar requires {token: str}")
        return AuthHandle(connector_kind=self.kind, handle_id="x")

    async def discover(self, handle):
        return []

    async def profile(self, handle, resource_id):
        raise NotImplementedError("foobar profile not yet implemented")

    async def sample(self, handle, resource_id, n):
        raise NotImplementedError("foobar sample not yet implemented")

    async def watch(self, handle, resource_id):
        raise NotImplementedError("foobar watch not yet implemented")
        if False:
            yield  # type: ignore[unreachable]
```

The harness honors the skeletal contract: invariants 4, 5, 6 assert
that `profile`/`sample`/`watch` raise `NotImplementedError` rather than
returning data. Invariants 1, 2, 3 still require working
`authenticate` and `discover`.

---

## 14. Common mistakes

**Returning a `Profile` with a list-keyed `schema_hash`.** Hash from a
deterministic *string* representation. `hash(tuple(columns))` is not
stable across Python processes (`PYTHONHASHSEED`).

**Catching `asyncio.CancelledError` in `watch`.** Don't. The worm
cancels by design. Catching breaks shutdown.

**Returning `[]` from `discover` when the source is unreachable.**
Return `[]` only when the source is empty. Raise on connectivity
failures so the worm surfaces the error to the user.

**Treating `extra` like a database.** It's a per-handle dict, lost
across processes. For state that needs to survive, keep it in your
own backend or expose it via metadata on `ResourceProposal`.

**Forgetting `if False: yield` in `watch` for pull-only connectors.**
Without `yield` somewhere in the body, Python sees `async def watch`
as a coroutine, not an async generator, and the harness's
`async for` rejects it.

**Stable-sorting in `discover` only when input order is deterministic.**
If your source returns rows in a `dict` or an unordered API response,
sort. If you skip the sort, conformance invariant 3 catches it
intermittently — flaky tests are the worst kind.

**Putting secrets in `handle_id`.** It surfaces in logs and ledger
entries. Use an opaque non-secret like a username, account id, or
hash of the secret.

---

## 15. Next steps — landing your connector in the registry

If your connector targets the WormBase monorepo:

1. Drop your file in `packages/lake-surfaces/src/wormbase_lake_surfaces/<kind>.py`.
2. Decorate the class with `@register_connector` from
   `wormbase_lake_surfaces.registry`.
3. Replace your local `SecretBundle`/`AuthHandle`/`ResourceProposal`/
   `Profile`/`Change` imports with `from wormbase_lake_surfaces.types
   import …`.
4. Add a fixture entry in
   `tests/contract/test_connector_protocol_conformance.py`'s
   `_build_fixtures` dict — the same six invariants, but with an
   in-process mock if your source needs network.
5. Open a PR.

If your connector ships in your own package:

1. Publish to PyPI as `wormbase-connector-<kind>`.
2. Document the install snippet:
   `pip install wormbase-connector-<kind>` plus a
   `wormbase-tools register <module>:<class>` step.
3. Submit it to the WormBase community connector index (see the
   project README for the current submission process).

Either way, the conformance harness is your contract: green on six
invariants and you're done.

---

## Where to look when stuck

- **The reference file:** `examples/connectors/parquet_local.py` — the
  exact code we built above, in a single ~140-line file.
- **The csv_local connector:** `packages/lake-surfaces/src/wormbase_lake_surfaces/csv_local.py`
  — production-grade `Connector` for local CSV files. Same shape;
  more robust handling of dtype inference and PII heuristics.
- **The Postgres connector:** same directory, `postgres.py`. Worth
  reading if your source is SQL-shaped — it shows how `authenticate`
  opens a real connection and how `discover` queries
  `information_schema`.
- **The Stripe connector:** same directory, `stripe.py`. Shows the
  HTTP-API shape with `httpx`, pagination, and how `sample` returns
  JSON-encoded API records.

When you write a new connector, copy the file whose source most
resembles yours and adapt. The shapes are identical; only the
transport changes.

Welcome to the catalog.
