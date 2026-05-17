# OSS Audit Replay — Auditor's Guide

**Status:** authoritative for `wormbase-tools >= 0.1.0`. Owns PRD §7 P8.
**Audience:** third-party auditors, regulators, compliance officers,
and anyone who needs to verify a WormBase tenant's KPI value
**without** trusting the hosted plane.

---

## TL;DR

```bash
pip install wormbase-tools
wormbase-tools replay snapshot.jsonl \
    --tenant 8b7e1c5e-93b4-4f2c-9b8d-2e0f1c5a3b6d \
    --to kpi_q3_revenue
```

Output is the bare KPI value on stdout. Exit code 0 means the chain
verified and the value resolved; exit 1 means **do not trust this
snapshot**.

You will **not** need:

- Postgres, asyncpg, SQLAlchemy
- The WormBase dashboard
- The cloudflared tunnel
- The inference router
- Any external network call

The replay is pure-Python, fail-closed, and deterministic. The same
snapshot fed to the same `wormbase-tools` version on any laptop must
produce byte-identical output.

---

## What you have

A vendor (the WormBase tenant operator) has handed you:

1. **A snapshot file** — `snapshot.jsonl`. One ledger entry per line,
   formatted per the schema below.
2. **A KPI id** — either a stable string (`revenue.q3`), a UUID (from
   an `emit_kpi_proposed` entry), or the demo shorthand
   (`kpi_q3_revenue`).
3. **A claimed value** — the number the vendor's `/kpis` view shows on
   their live dashboard for that KPI.

Your job is to verify the third claim by reproducing the value from
the first two, **without** the vendor's running system in the loop.

---

## What `wormbase-tools replay` does

In one process, in pure Python, in under 10 seconds for a 1000-entry
snapshot:

1. **Loads** the JSONL file. Every line must be a complete ledger
   entry envelope (see schema). Missing fields, malformed hex, or
   non-tz-aware timestamps abort with exit 1.
2. **Filters** entries to the tenant you pinned with `--tenant`. If
   the snapshot has only one tenant, you can omit the flag and let
   replay auto-detect.
3. **Verifies the hash chain**. Every entry's `prev_hash` must equal
   the running chain head (starting from 32 zero bytes), and every
   entry's stored `hash` must equal the recomputed
   `sha256(canonical_json(entry minus hash))`. Any mismatch ⇒ exit 1
   with a pseudo-`diff` diagnostic on stderr.
4. **Folds projections**. Entries of kind `emit_kpi_node`,
   `emit_kpi_proposed`, and `emit_source_golded` are processed in
   `seq` order to rebuild the KPI tree state. The fold is pure
   Python; it mirrors the in-memory portion of the hosted plane's
   projection logic. See the seam doc in
   `wormbase_tools.projections` for what's vendored vs re-imported.
5. **Looks up** your `--to <kpi_id>`. If the KPI is not present, exit
   1 with the list of known ids on stderr. If present, write the
   numeric value to stdout (one line, no trailing whitespace beyond
   the newline) and exit 0.

---

## Snapshot file format

JSONL. One ledger entry per line. Each line is a JSON object with the
following fields:

| Field | Type | Notes |
|---|---|---|
| `entry_id` | UUID string | The ledger row's primary key. |
| `company_id` | UUID string | The tenant. Multi-tenant snapshots are allowed; you must pass `--tenant` to disambiguate. |
| `seq` | integer | Monotonic per-tenant. Replay sorts by this. |
| `ts` | RFC 3339 string | tz-aware. Trailing `Z` accepted. |
| `kind` | string | One of the WormBase entry kinds (`execute`, `chat_received`, `propose`, …). |
| `quadrant` | string | `passive_deterministic` / `passive_probabilistic` / `active_deterministic` / `active_probabilistic`. |
| `payload` | object | Entry-kind-specific body. For `execute` rows: `{tool, args, result_ref, propose_entry_id}`. |
| `prev_hash` | 64-char hex string | The chain link. First entry: 64 zero hex chars. |
| `hash` | 64-char hex string | sha256 of canonical JSON of all other fields. |

### Canonical JSON rules

The hosted plane and `wormbase-tools` agree byte-for-byte on these
encoding rules:

- UTF-8.
- `sort_keys=True`, separators `","` and `":"` (no whitespace).
- UUIDs serialised as their string form.
- Datetimes as RFC 3339 with trailing `Z`, microseconds rendered with
  trailing-zero stripping.
- Bytes as lowercase hex.

Any deviation ⇒ hashes won't match ⇒ replay aborts. This is
intentional: the byte-stable encoding is the trust contract.

---

## Worked example

The vendor sends you `snapshot.jsonl`:

```
$ head -2 snapshot.jsonl
{"company_id":"8b7e1c5e-…","entry_id":"…","hash":"a1b2…","kind":"execute","payload":{"args":{"gold_artifact_id":"…","source_id":"…","artifact_kind":"kpi","value":{"unit":"USD","value":142857.42},"computed_at":"2026-04-28T12:00:00Z"},"propose_entry_id":"…","tool":"emit_source_golded","result_ref":"…"},"prev_hash":"0000…","quadrant":"active_deterministic","seq":1,"ts":"2026-04-28T12:00:00Z"}
{"company_id":"8b7e1c5e-…","entry_id":"…","hash":"c3d4…","kind":"execute","payload":{"args":{"kpi_id":"…","label":"Q3 Net Revenue","formula":"…","source_ids":["…"],"unit":"USD","proposed_at":"2026-04-28T12:00:01Z"},"propose_entry_id":"…","tool":"emit_kpi_proposed","result_ref":"…"},"prev_hash":"a1b2…","quadrant":"active_deterministic","seq":2,"ts":"2026-04-28T12:00:01Z"}
```

The vendor claims the KPI value is `142857.42`. You verify:

```
$ python -m venv /tmp/audit-venv
$ /tmp/audit-venv/bin/pip install wormbase-tools
$ /tmp/audit-venv/bin/wormbase-tools replay snapshot.jsonl \
    --tenant 8b7e1c5e-93b4-4f2c-9b8d-2e0f1c5a3b6d \
    --to <the kpi_id from the second line> \
    --timing
# replay: 2 entries in 0.2ms (terminal_hash=a1b2c3d4…)
142857.42
$ echo $?
0
```

`142857.42` matches the vendor's `/kpis` value. Trust verified.

If it didn't match — value differs, chain breaks, KPI not found —
replay would have written a diff-style diagnostic to stderr and exited
non-zero. You would not see `142857.42` on stdout.

---

## Producing a snapshot (vendor-side)

Tenant operators producing a snapshot for an auditor should use:

```bash
# In the WormBase monorepo, with WORMBASE_DB_URL set:
wormbase-ledger snapshot --tenant <id> > snapshot.jsonl
```

(That CLI is provided by `wormbase-ledger`; see its help for filtering
options.)

Auditor tip: ask for the snapshot to be served via a signed URL or a
detached signature. The hash chain proves entries are linked, but
not that the file came from the vendor — that's a separate trust hop.

---

## What replay verifies, and what it doesn't

**Verifies:**

- Every entry's hash is a sha256 of its canonical body.
- Every entry's `prev_hash` matches the running chain head.
- The chain's terminal hash is reproducible from the file.
- KPI values fold deterministically from the chain.
- Same snapshot ⇒ same KPI value, byte-for-byte, every time.

**Does not verify:**

- That the snapshot actually came from the vendor's tenant. Combine
  with a transport-level signature.
- That the KPI definition is what the auditor's contract specifies.
  Inspect the `formula` and `source_ids` fields manually.
- That the underlying source data is correct. Replay verifies the
  *pipeline*; it cannot detect data poisoning at the source.

---

## Troubleshooting

| Exit code | Meaning |
|---|---|
| 0 | Success. Value on stdout. |
| 1 | Replay aborted. Diagnostic on stderr. |
| 2 | Bad CLI invocation (missing `--to`, etc.). |

Common stderr messages:

- `chain break at seq=N` — the file has been edited or corrupted.
- `kpi_id=… not found` — the KPI you asked for isn't in this
  snapshot. The error includes the list of known KPI ids.
- `multiple tenants … pass --tenant` — auto-detect is off, you must
  pin a single tenant.
- `snapshot is empty` — the file has no JSON-object lines.

Run with `--timing` to see how long each step took. Run with `--json`
to see the full provenance trail (which ledger entry ids contributed
to the KPI value).

---

## License

`wormbase-tools` is Apache-2.0. You may run it offline, redistribute
it, modify it. The auditor flow does **not** phone home — by design.
