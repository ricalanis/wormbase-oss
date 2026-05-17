# `tests/fixtures/users/`

Synthetic Person / Domain / Resource graphs used by governance and
projection tests.

## Format

YAML files, one graph per scenario:

```yaml
people:
  - id: 00000000-0000-0000-0000-00000000000a
    name: Ricardo
    email: r@example.com
    role: admin
domains:
  - id: 00000000-0000-0000-0000-0000000000d1
    name: finance
    classification: confidential
resources:
  - id: 00000000-0000-0000-0000-0000000000e1
    domain_id: 00000000-0000-0000-0000-0000000000d1
    uri: s3://bucket/quarterly.csv
```

UUIDs are deterministic so projection hashes stay stable across runs.

## Convention

- `tiny_3people_2domains.yaml` — minimal graph for projection tests
- `multi_tenant.yaml` — two companies sharing nothing for isolation tests
- `pii_heavy.yaml` — domains classified PII for gate tests
