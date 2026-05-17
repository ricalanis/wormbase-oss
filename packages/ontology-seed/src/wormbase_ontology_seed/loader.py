"""Ontology seed loader: reads pre-seeded YAML packs and validates via Pydantic.

The loader is read-only and returns deep-copied lists so callers can mutate
their results without disturbing the underlying cache. All Pydantic models are
frozen / extra=forbid so any drift in the YAML files is caught at parse time.
"""

from __future__ import annotations

import re
from importlib.resources import files
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, field_validator


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class Concept(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    label: str
    category: Literal["metric", "entity", "event", "dimension", "source_archetype"]
    aliases: list[str]
    examples: list[str]
    parent_id: str | None = None


class PIIPattern(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    regex: str
    classification: Literal["pii", "regulated"]

    @field_validator("regex")
    @classmethod
    def _compiles(cls, v: str) -> str:
        try:
            re.compile(v)
        except re.error as exc:
            raise ValueError(f"invalid regex {v!r}: {exc}") from exc
        return v


class PolicyTemplate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    applies_to: dict[str, str]
    rule: str
    gate_impl: str

    @field_validator("gate_impl")
    @classmethod
    def _dotted_path(cls, v: str) -> str:
        if not re.match(r"^[a-z_][a-z0-9_.]*\.[a-z_][a-z0-9_]*$", v):
            raise ValueError(f"gate_impl must be importable dotted path, got {v!r}")
        return v


class DomainTemplate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    default_classification: Literal[
        "public", "internal", "confidential", "pii", "regulated"
    ]
    description: str
    suggested_owner_role: str


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _default_data_dir() -> Path:
    """Locate the bundled `data/` directory across editable installs and wheel."""
    # First try importlib.resources (packaged wheel).
    try:
        pkg_root = files("wormbase_ontology_seed")
        candidate = pkg_root / "data"
        if candidate.is_dir():
            return Path(str(candidate))
    except (ModuleNotFoundError, FileNotFoundError):
        pass

    # Editable install: data/ sits at packages/ontology-seed/data, which is
    # one directory up from src/wormbase_ontology_seed/.
    here = Path(__file__).resolve().parent
    repo_data = here.parent.parent / "data"
    if repo_data.is_dir():
        return repo_data

    raise FileNotFoundError(
        "Could not locate ontology-seed data directory. Tried packaged "
        "resources and editable layout."
    )


DEFAULT_DATA_DIR = _default_data_dir()


_VALID_DOMAIN_PACKS = ("saas", "marketplace", "fintech")


class Loader:
    """Read-only loader for ontology seed packs."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self._data_dir = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    # -- ontology packs --------------------------------------------------

    def load_ontology(
        self, domain: Literal["saas", "marketplace", "fintech"]
    ) -> list[Concept]:
        if domain not in _VALID_DOMAIN_PACKS:
            raise ValueError(
                f"unknown domain pack {domain!r}; valid: {_VALID_DOMAIN_PACKS}"
            )
        path = self._data_dir / f"{domain}.yaml"
        if not path.is_file():
            raise ValueError(f"missing ontology file for {domain}: {path}")
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError(
                f"{path}: expected a list of concept dicts at top level"
            )
        concepts = [Concept.model_validate(c) for c in raw]
        ids = [c.id for c in concepts]
        if len(set(ids)) != len(ids):
            dups = [i for i in ids if ids.count(i) > 1]
            raise ValueError(f"{path}: duplicate concept ids {sorted(set(dups))}")
        return [c.model_copy() for c in concepts]

    # -- pii patterns ----------------------------------------------------

    def load_pii_patterns(self) -> list[PIIPattern]:
        path = self._data_dir / "pii_patterns.yaml"
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        patterns = [PIIPattern.model_validate(p) for p in raw]
        return [p.model_copy() for p in patterns]

    # -- policy templates ------------------------------------------------

    def load_policy_templates(self) -> list[PolicyTemplate]:
        path = self._data_dir / "policy_templates.yaml"
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        templates = [PolicyTemplate.model_validate(t) for t in raw]
        return [t.model_copy() for t in templates]

    # -- domain templates ------------------------------------------------

    def load_domain_templates(self, domain_pack: str) -> list[DomainTemplate]:
        path = self._data_dir / "domain_templates.yaml"
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(
                f"{path}: expected a top-level mapping keyed by domain pack"
            )
        if domain_pack not in raw:
            raise ValueError(
                f"no domain templates for pack {domain_pack!r}; "
                f"available packs: {sorted(raw.keys())}"
            )
        items = raw[domain_pack]
        templates = [DomainTemplate.model_validate(d) for d in items]
        return [d.model_copy() for d in templates]


__all__ = [
    "DEFAULT_DATA_DIR",
    "Concept",
    "DomainTemplate",
    "Loader",
    "PIIPattern",
    "PolicyTemplate",
]
