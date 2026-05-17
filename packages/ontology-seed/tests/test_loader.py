"""Tests for the ontology-seed loader."""

from __future__ import annotations

import re

import pytest

from wormbase_ontology_seed import (
    Concept,
    DomainTemplate,
    Loader,
    PIIPattern,
    PolicyTemplate,
)


@pytest.fixture
def loader() -> Loader:
    return Loader()


# -- ontology packs --------------------------------------------------


def test_load_saas_ontology_returns_at_least_50_concepts(loader: Loader) -> None:
    concepts = loader.load_ontology("saas")
    assert len(concepts) >= 50


def test_load_marketplace_ontology_loads(loader: Loader) -> None:
    concepts = loader.load_ontology("marketplace")
    assert len(concepts) >= 40


def test_load_fintech_ontology_loads(loader: Loader) -> None:
    concepts = loader.load_ontology("fintech")
    assert len(concepts) >= 40


def test_each_concept_has_id_label_category_aliases_examples(loader: Loader) -> None:
    for domain in ("saas", "marketplace", "fintech"):
        for c in loader.load_ontology(domain):
            assert isinstance(c, Concept)
            assert c.id and isinstance(c.id, str)
            assert c.label
            assert c.category in {
                "metric",
                "entity",
                "event",
                "dimension",
                "source_archetype",
            }
            assert c.aliases, f"{c.id} missing aliases"
            assert c.examples, f"{c.id} missing examples"


def test_concept_ids_are_unique_within_a_pack(loader: Loader) -> None:
    for domain in ("saas", "marketplace", "fintech"):
        ids = [c.id for c in loader.load_ontology(domain)]
        assert len(set(ids)) == len(ids), f"duplicate ids in {domain}"


def test_load_unknown_domain_pack_raises(loader: Loader) -> None:
    with pytest.raises(ValueError):
        loader.load_ontology("unknown")  # type: ignore[arg-type]


def test_loader_returns_copies_not_references(loader: Loader) -> None:
    first = loader.load_ontology("saas")
    first.append(first[0])
    second = loader.load_ontology("saas")
    assert len(second) == len(first) - 1


# -- pii patterns ----------------------------------------------------


def test_load_pii_patterns_returns_non_empty_list(loader: Loader) -> None:
    patterns = loader.load_pii_patterns()
    assert len(patterns) >= 12
    for p in patterns:
        assert isinstance(p, PIIPattern)
        # Already validated by Pydantic, but assert again for safety.
        re.compile(p.regex)


# -- policy templates ------------------------------------------------


def test_load_policy_templates_returns_list(loader: Loader) -> None:
    templates = loader.load_policy_templates()
    assert len(templates) >= 3
    names = {t.id for t in templates}
    assert {"pii_redaction", "warmup_required", "interjection_budget"} <= names
    for t in templates:
        assert isinstance(t, PolicyTemplate)
        # gate_impl must be an importable dotted path shape.
        assert re.match(r"^[a-z_][a-z0-9_.]*\.[a-z_][a-z0-9_]*$", t.gate_impl)


# -- domain templates ------------------------------------------------


def test_domain_templates_load_for_each_pack(loader: Loader) -> None:
    for pack in ("saas", "marketplace", "fintech"):
        templates = loader.load_domain_templates(pack)
        assert len(templates) >= 3
        for d in templates:
            assert isinstance(d, DomainTemplate)


def test_unknown_domain_pack_raises(loader: Loader) -> None:
    with pytest.raises(ValueError):
        loader.load_domain_templates("nope")
