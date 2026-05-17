"""wormbase_ontology_seed — pre-seeded SaaS / marketplace / fintech ontologies.

Exports:
    Loader               — read-only loader for ontology packs + PII + policy + domain templates
    Concept              — Pydantic model for a single ontology concept
    PIIPattern           — Pydantic model for a regex-backed PII detector
    PolicyTemplate       — Pydantic model for a policy seed
    DomainTemplate       — Pydantic model for a pre-seeded domain
    DEFAULT_DATA_DIR     — Path to the bundled YAML data directory
"""

from __future__ import annotations

from wormbase_ontology_seed.loader import (
    DEFAULT_DATA_DIR,
    Concept,
    DomainTemplate,
    Loader,
    PIIPattern,
    PolicyTemplate,
)

__all__ = [
    "DEFAULT_DATA_DIR",
    "Concept",
    "DomainTemplate",
    "Loader",
    "PIIPattern",
    "PolicyTemplate",
]
