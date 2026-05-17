# `tests/fixtures/ontology/`

Minimal ontology pack snapshots for fast classifier/relevance tests.
Each file is a YAML pack identical in shape to
`packages/ontology-seed/data/saas/*.yaml` but trimmed to the smallest
useful set of concepts/synonyms/policies.

## Why we keep these here

- The real seed packs are exhaustive (hundreds of concepts) — slow to
  load in fast unit tests.
- Tests that exercise classifier edge-cases want to know exactly which
  concepts are present. Trimmed fixtures make those assertions stable.

## Convention

- `tiny_saas/` — ~10 concepts, 5 PII patterns, 2 policies
- `domain_finance.yaml` — single domain template for warmup tests
- `pii_minimal.yaml` — just the SSN/email/CC patterns

If a test needs the full pack it should call `Loader()` against the real
`packages/ontology-seed/data/`. Use this directory only when the test's
goal is to constrain what's available.
