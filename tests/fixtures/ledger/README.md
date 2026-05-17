# `tests/fixtures/ledger/`

Pre-built ledger snapshots for replay verification. Each file is a
JSONL dump of `wormbase_ledger.fetch_entries` output for a known
scenario, plus a sibling `.expected_hash` text file with the expected
`replay()` projection hash (hex-encoded).

## Format

```
<scenario>.jsonl              # one ledger row per line
<scenario>.expected_hash      # 64 hex chars (SHA-256)
<scenario>.summary.md         # human-readable description
```

## Why these matter

The reproducibility gate (F2 in PRD §6) demands that replaying a known
ledger always produces the same projection hash, byte-for-byte. We
keep the canonical inputs here so any change to the projection
algorithm gets caught the moment hashes drift.

To regenerate after an INTENTIONAL projection change:

```bash
uv run python -m wormbase_ledger.replay \
    --input tests/fixtures/ledger/<scenario>.jsonl \
    --print-hash > tests/fixtures/ledger/<scenario>.expected_hash
```

…then commit the new hash WITH a note in the summary explaining what
changed and why drift is acceptable.
