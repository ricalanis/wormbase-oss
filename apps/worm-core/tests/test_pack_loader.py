"""Tests for ``onboarding.pack_loader`` — Onboarding Sub-wave C (2026-05-30).

Pins:

* ``available_pack_ids()`` discovers the 4 bundled packs in
  alphabetical order.
* ``load_pack(pack_id)`` round-trips each canonical pack
  (generic / saas / marketplace / fintech) without errors.
* Strict validation: malformed YAML / missing fields / duplicate
  domain ids / pack_id ≠ filename raise ``PackLoadError`` with an
  operator-actionable message.
* ``list_packs()`` loads every pack and reports back the typed
  ``Pack`` dataclasses.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from wormbase_core.onboarding.pack_loader import (
    Pack,
    PackLoadError,
    available_pack_ids,
    list_packs,
    load_pack,
)


# ---------------------------------------------------------------------------
# Discovery + canonical packs.
# ---------------------------------------------------------------------------


def test_available_pack_ids_returns_four_canonical_packs() -> None:
    """All four canonical packs ship + are discovered alphabetically."""
    ids = available_pack_ids()
    assert "generic" in ids
    assert "saas" in ids
    assert "marketplace" in ids
    assert "fintech" in ids
    # Sort guarantee
    assert ids == tuple(sorted(ids))


@pytest.mark.parametrize(
    "pack_id",
    ["generic", "saas", "marketplace", "fintech"],
)
def test_load_pack_canonical(pack_id: str) -> None:
    """Each canonical pack loads + validates without errors."""
    p = load_pack(pack_id)
    assert isinstance(p, Pack)
    assert p.pack_id == pack_id
    assert p.pack_version == "v1.0"
    assert p.display_name
    assert p.description
    assert p.domain_count > 0  # every canonical pack has ≥1 domain
    assert all(d.id and d.name for d in p.domains)


def test_list_packs_returns_all_four() -> None:
    """``list_packs`` returns one Pack per file."""
    packs = list_packs()
    ids = {p.pack_id for p in packs}
    assert ids == {"generic", "saas", "marketplace", "fintech"}


def test_generic_pack_shape() -> None:
    """The generic pack has the minimal-baseline shape: 1 domain + 1 policy."""
    p = load_pack("generic")
    assert len(p.domains) == 1
    assert p.domains[0].id == "domain_general"
    assert p.domains[0].default_classification == "internal"
    assert len(p.policies) >= 1
    assert len(p.classification_defaults) >= 1


def test_fintech_pack_uses_regulated_classifications() -> None:
    """The fintech pack has at least one regulated-classification domain."""
    p = load_pack("fintech")
    has_regulated = any(d.default_classification == "regulated" for d in p.domains)
    assert has_regulated, (
        "fintech pack should declare at least one regulated-classification "
        "domain (e.g. ledger, compliance) for SOC-2 baseline"
    )


# ---------------------------------------------------------------------------
# Validation: unknown pack_id.
# ---------------------------------------------------------------------------


def test_load_pack_unknown_id_raises() -> None:
    """Unknown pack ids raise ``PackLoadError`` with available list."""
    with pytest.raises(PackLoadError) as excinfo:
        load_pack("does_not_exist")
    msg = str(excinfo.value)
    assert "does_not_exist" in msg
    assert "Available" in msg


# ---------------------------------------------------------------------------
# Validation: structural rules (driven via tmp_path so the canonical
# YAMLs aren't touched).
# ---------------------------------------------------------------------------


def _patch_packs_dir(monkeypatch, tmp_path: Path) -> None:
    """Redirect ``_packs_dir()`` to a temp dir so we can write malformed YAML."""
    from wormbase_core.onboarding import pack_loader

    monkeypatch.setattr(pack_loader, "_packs_dir", lambda: tmp_path)


def test_pack_id_must_match_filename(monkeypatch, tmp_path: Path) -> None:
    """A YAML declaring pack_id different from filename raises."""
    _patch_packs_dir(monkeypatch, tmp_path)
    (tmp_path / "alpha.yaml").write_text(
        "pack_id: beta\n"  # mismatch: filename says alpha
        "pack_version: v1.0\n"
        "display_name: A\n"
        "description: B\n",
        encoding="utf-8",
    )
    with pytest.raises(PackLoadError) as excinfo:
        load_pack("alpha")
    assert "filename" in str(excinfo.value).lower()


def test_missing_pack_version_raises(monkeypatch, tmp_path: Path) -> None:
    _patch_packs_dir(monkeypatch, tmp_path)
    (tmp_path / "minimal.yaml").write_text(
        "pack_id: minimal\n"
        "display_name: A\n"
        "description: B\n",
        encoding="utf-8",
    )
    with pytest.raises(PackLoadError) as excinfo:
        load_pack("minimal")
    assert "pack_version" in str(excinfo.value)


def test_missing_required_domain_field_raises(monkeypatch, tmp_path: Path) -> None:
    _patch_packs_dir(monkeypatch, tmp_path)
    (tmp_path / "bad.yaml").write_text(
        "pack_id: bad\n"
        "pack_version: v1.0\n"
        "display_name: A\n"
        "description: B\n"
        "domains:\n"
        "  - id: x\n"  # missing name + default_classification
        "    name: X\n",
        encoding="utf-8",
    )
    with pytest.raises(PackLoadError) as excinfo:
        load_pack("bad")
    msg = str(excinfo.value)
    assert "domain" in msg.lower()
    assert "default_classification" in msg


def test_duplicate_domain_id_raises(monkeypatch, tmp_path: Path) -> None:
    _patch_packs_dir(monkeypatch, tmp_path)
    (tmp_path / "dup.yaml").write_text(
        "pack_id: dup\n"
        "pack_version: v1.0\n"
        "display_name: A\n"
        "description: B\n"
        "domains:\n"
        "  - id: d1\n"
        "    name: D1\n"
        "    default_classification: internal\n"
        "  - id: d1\n"  # duplicate
        "    name: D1b\n"
        "    default_classification: internal\n",
        encoding="utf-8",
    )
    with pytest.raises(PackLoadError) as excinfo:
        load_pack("dup")
    assert "duplicate" in str(excinfo.value).lower()


def test_unknown_classification_raises(monkeypatch, tmp_path: Path) -> None:
    _patch_packs_dir(monkeypatch, tmp_path)
    (tmp_path / "weird.yaml").write_text(
        "pack_id: weird\n"
        "pack_version: v1.0\n"
        "display_name: A\n"
        "description: B\n"
        "domains:\n"
        "  - id: d1\n"
        "    name: D1\n"
        "    default_classification: super_secret\n",  # invalid
        encoding="utf-8",
    )
    with pytest.raises(PackLoadError) as excinfo:
        load_pack("weird")
    assert "super_secret" in str(excinfo.value)


def test_policy_references_unknown_domain_raises(
    monkeypatch, tmp_path: Path,
) -> None:
    _patch_packs_dir(monkeypatch, tmp_path)
    (tmp_path / "orphan.yaml").write_text(
        "pack_id: orphan\n"
        "pack_version: v1.0\n"
        "display_name: A\n"
        "description: B\n"
        "domains:\n"
        "  - id: real_one\n"
        "    name: R\n"
        "    default_classification: internal\n"
        "policies:\n"
        "  - id: p1\n"
        "    applies_to_domains: [nonexistent]\n"
        "    rule: 'r'\n",
        encoding="utf-8",
    )
    with pytest.raises(PackLoadError) as excinfo:
        load_pack("orphan")
    assert "nonexistent" in str(excinfo.value)


def test_invalid_yaml_raises_load_error(monkeypatch, tmp_path: Path) -> None:
    _patch_packs_dir(monkeypatch, tmp_path)
    (tmp_path / "broken.yaml").write_text(
        "this is: not valid: yaml: :",
        encoding="utf-8",
    )
    with pytest.raises(PackLoadError):
        load_pack("broken")
