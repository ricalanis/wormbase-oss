# wormbase-ontology-seed

Data-only package: pre-seeded ontology, classification templates, PII pattern libraries, and policy templates for the three v-demo KPI-tree variants (SaaS, marketplace, fintech). Every entry carries a concept id, human-readable label, and optional embeddings reference; together they warm-start the worm's semantic classifier on first install so ramp gauges begin above zero. Not code — consumed directly as YAML/JSON by `worm-core` and by `sim-harness` when provisioning a fresh tenant.
