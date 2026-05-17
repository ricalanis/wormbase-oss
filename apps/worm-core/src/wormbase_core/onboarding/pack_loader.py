"""Onboarding pack loader — Sub-wave C (2026-05-30).

Reads + validates the 4 YAML packs bundled under
``apps/worm-core/src/wormbase_core/onboarding/packs/``. Each pack is a
declarative bundle of domains, policies, and classification defaults
that ``pack_seeder.seed_pack`` fans out into a single PEVR batch on
``domain_pack_selected`` + ``emit_domain_registered`` +
``emit_policy_applied`` ledger writes.

Loader contract:

* Strict validation at load time — malformed YAML / missing required
  fields / duplicate domain IDs / pack_id ≠ filename raise
  ``PackLoadError`` with an operator-actionable message.
* Returns frozen ``Pack`` dataclasses; the typed surface is
  ergonomic for the seeder + the dashboard accessor.
* Module-level ``list_packs()`` reads from disk once per call (no
  caching) — pack contents change rarely enough that a cache adds
  complexity without payoff; the dashboard accessor calls this on
  every page render to stay honest about disk-state.

The pack files live alongside this module (importlib.resources
lookup) so the worm-core wheel ships them as data. Future packs land
by dropping a new ``<pack_id>.yaml`` next to the existing four —
no Python code change required.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class PackLoadError(ValueError):
    """Raised when a pack YAML is missing, malformed, or fails validation.

    The error message is operator-actionable: it names the pack and
    the specific structural problem (missing field, duplicate ID,
    pack_id ≠ filename, etc).
    """


_VALID_CLASSIFICATIONS = frozenset(
    {"public", "internal", "confidential", "pii", "regulated"},
)
_REQUIRED_DOMAIN_FIELDS = frozenset({"id", "name", "default_classification"})
_REQUIRED_POLICY_FIELDS = frozenset({"id", "applies_to_domains", "rule"})
_REQUIRED_CLASSIFICATION_FIELDS = frozenset({"pattern", "classification"})


@dataclass(frozen=True)
class PackDomain:
    """A single domain entry inside a pack.

    ``owner_role`` is a hint, not a binding grant — the actual
    ``domain_role_assigned`` PEVR cycle is written separately at
    install time or as the installer confirms ownership.
    """

    id: str
    name: str
    default_classification: str
    owner_role: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class PackPolicy:
    """A single policy entry inside a pack.

    ``gate_impl`` is a dotted import path; validated at policy-load
    time by the existing ``PolicyLoader`` (out of scope for the
    onboarding pack loader, which trusts the path string).
    """

    id: str
    name: str
    applies_to_domains: tuple[str, ...]
    rule: str
    gate_impl: str | None = None


@dataclass(frozen=True)
class PackClassificationDefault:
    """A single classification-default pattern entry."""

    pattern: str
    classification: str


@dataclass(frozen=True)
class Pack:
    """A loaded, validated onboarding pack.

    Frozen so callers cannot mutate the in-memory representation
    after load. Re-load by calling ``load_pack`` again.
    """

    pack_id: str
    pack_version: str
    display_name: str
    description: str
    domains: tuple[PackDomain, ...] = field(default_factory=tuple)
    policies: tuple[PackPolicy, ...] = field(default_factory=tuple)
    classification_defaults: tuple[PackClassificationDefault, ...] = field(
        default_factory=tuple,
    )

    @property
    def domain_count(self) -> int:
        return len(self.domains)


# ---------------------------------------------------------------------------
# Pack lookup + loading
# ---------------------------------------------------------------------------


def _packs_dir() -> Path:
    """Directory containing the bundled pack YAMLs.

    Resolved relative to this module so the wheel ships the YAMLs as
    package data.
    """
    return Path(__file__).resolve().parent / "packs"


def available_pack_ids() -> tuple[str, ...]:
    """Return the sorted tuple of pack IDs discovered on disk.

    Discovery: scan ``packs/`` for ``*.yaml`` files; strip the suffix.
    Future packs land by dropping a new file — no Python edit.
    """
    pdir = _packs_dir()
    if not pdir.is_dir():
        return ()
    return tuple(sorted(p.stem for p in pdir.glob("*.yaml")))


def load_pack(pack_id: str) -> Pack:
    """Load + validate a single pack by id.

    Raises:
        PackLoadError: when the file is missing, malformed, or fails
            structural validation.
    """
    pdir = _packs_dir()
    pack_path = pdir / f"{pack_id}.yaml"
    if not pack_path.is_file():
        raise PackLoadError(
            f"pack {pack_id!r} not found at {pack_path}. "
            f"Available: {available_pack_ids()}"
        )

    try:
        with pack_path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise PackLoadError(
            f"pack {pack_id!r} at {pack_path} is not valid YAML: {exc}"
        ) from exc

    if not isinstance(raw, dict):
        raise PackLoadError(
            f"pack {pack_id!r} top-level must be a mapping; got "
            f"{type(raw).__name__}"
        )

    return _validate_and_build(pack_id, raw)


def list_packs() -> tuple[Pack, ...]:
    """Load every pack on disk in pack-id alphabetical order.

    Loader errors on any one pack propagate — a malformed pack must
    not silently disappear from the picker.
    """
    return tuple(load_pack(pid) for pid in available_pack_ids())


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_and_build(pack_id: str, raw: dict[str, Any]) -> Pack:
    """Apply structural validation rules + build the typed Pack."""
    file_pack_id = raw.get("pack_id")
    if file_pack_id != pack_id:
        raise PackLoadError(
            f"pack file {pack_id}.yaml declares pack_id={file_pack_id!r}; "
            f"filename and pack_id MUST match (wire-replay determinism)."
        )

    pack_version = raw.get("pack_version")
    if not pack_version or not isinstance(pack_version, str):
        raise PackLoadError(
            f"pack {pack_id!r} missing required string field 'pack_version'."
        )

    display_name = raw.get("display_name")
    if not display_name or not isinstance(display_name, str):
        raise PackLoadError(
            f"pack {pack_id!r} missing required string field 'display_name'."
        )

    description = raw.get("description")
    if not description or not isinstance(description, str):
        raise PackLoadError(
            f"pack {pack_id!r} missing required string field 'description'."
        )

    # ------------------------------------------------------------------
    # Domains.
    # ------------------------------------------------------------------
    raw_domains = raw.get("domains") or []
    if not isinstance(raw_domains, list):
        raise PackLoadError(
            f"pack {pack_id!r} 'domains' must be a list; got "
            f"{type(raw_domains).__name__}"
        )

    seen_domain_ids: set[str] = set()
    domains: list[PackDomain] = []
    for i, d in enumerate(raw_domains):
        if not isinstance(d, dict):
            raise PackLoadError(
                f"pack {pack_id!r} domains[{i}] must be a mapping; got "
                f"{type(d).__name__}"
            )
        missing = _REQUIRED_DOMAIN_FIELDS - set(d.keys())
        if missing:
            raise PackLoadError(
                f"pack {pack_id!r} domains[{i}] missing required fields: "
                f"{sorted(missing)}"
            )
        did = d["id"]
        if not isinstance(did, str) or not did:
            raise PackLoadError(
                f"pack {pack_id!r} domains[{i}] 'id' must be a non-empty string."
            )
        if did in seen_domain_ids:
            raise PackLoadError(
                f"pack {pack_id!r} has duplicate domain id {did!r} — "
                f"every domain id must be unique within a pack."
            )
        seen_domain_ids.add(did)

        cls = d["default_classification"]
        if cls not in _VALID_CLASSIFICATIONS:
            raise PackLoadError(
                f"pack {pack_id!r} domain {did!r} default_classification "
                f"{cls!r} not in {sorted(_VALID_CLASSIFICATIONS)}"
            )

        domains.append(
            PackDomain(
                id=did,
                name=str(d["name"]),
                default_classification=cls,
                owner_role=(
                    str(d["owner_role"]) if d.get("owner_role") else None
                ),
                description=(
                    str(d["description"]) if d.get("description") else None
                ),
            )
        )

    # ------------------------------------------------------------------
    # Policies.
    # ------------------------------------------------------------------
    raw_policies = raw.get("policies") or []
    if not isinstance(raw_policies, list):
        raise PackLoadError(
            f"pack {pack_id!r} 'policies' must be a list; got "
            f"{type(raw_policies).__name__}"
        )

    seen_policy_ids: set[str] = set()
    policies: list[PackPolicy] = []
    for i, pol in enumerate(raw_policies):
        if not isinstance(pol, dict):
            raise PackLoadError(
                f"pack {pack_id!r} policies[{i}] must be a mapping; got "
                f"{type(pol).__name__}"
            )
        missing = _REQUIRED_POLICY_FIELDS - set(pol.keys())
        if missing:
            raise PackLoadError(
                f"pack {pack_id!r} policies[{i}] missing required fields: "
                f"{sorted(missing)}"
            )
        pid = pol["id"]
        if not isinstance(pid, str) or not pid:
            raise PackLoadError(
                f"pack {pack_id!r} policies[{i}] 'id' must be a non-empty "
                f"string."
            )
        if pid in seen_policy_ids:
            raise PackLoadError(
                f"pack {pack_id!r} has duplicate policy id {pid!r}."
            )
        seen_policy_ids.add(pid)

        applies = pol["applies_to_domains"]
        if not isinstance(applies, list) or not all(
            isinstance(x, str) for x in applies
        ):
            raise PackLoadError(
                f"pack {pack_id!r} policy {pid!r} 'applies_to_domains' "
                f"must be a list of strings."
            )
        unknown = set(applies) - seen_domain_ids
        if unknown:
            raise PackLoadError(
                f"pack {pack_id!r} policy {pid!r} references unknown "
                f"domain ids: {sorted(unknown)}"
            )

        policies.append(
            PackPolicy(
                id=pid,
                name=str(pol.get("name", pid)),
                applies_to_domains=tuple(applies),
                rule=str(pol["rule"]),
                gate_impl=(
                    str(pol["gate_impl"]) if pol.get("gate_impl") else None
                ),
            )
        )

    # ------------------------------------------------------------------
    # Classification defaults.
    # ------------------------------------------------------------------
    raw_class = raw.get("classification_defaults") or []
    if not isinstance(raw_class, list):
        raise PackLoadError(
            f"pack {pack_id!r} 'classification_defaults' must be a list; "
            f"got {type(raw_class).__name__}"
        )

    classifications: list[PackClassificationDefault] = []
    for i, c in enumerate(raw_class):
        if not isinstance(c, dict):
            raise PackLoadError(
                f"pack {pack_id!r} classification_defaults[{i}] must be a "
                f"mapping; got {type(c).__name__}"
            )
        missing = _REQUIRED_CLASSIFICATION_FIELDS - set(c.keys())
        if missing:
            raise PackLoadError(
                f"pack {pack_id!r} classification_defaults[{i}] missing "
                f"required fields: {sorted(missing)}"
            )
        cls = c["classification"]
        if cls not in _VALID_CLASSIFICATIONS:
            raise PackLoadError(
                f"pack {pack_id!r} classification_defaults[{i}] classification "
                f"{cls!r} not in {sorted(_VALID_CLASSIFICATIONS)}"
            )
        classifications.append(
            PackClassificationDefault(
                pattern=str(c["pattern"]),
                classification=cls,
            )
        )

    return Pack(
        pack_id=pack_id,
        pack_version=pack_version,
        display_name=display_name,
        description=description,
        domains=tuple(domains),
        policies=tuple(policies),
        classification_defaults=tuple(classifications),
    )


__all__ = [
    "Pack",
    "PackClassificationDefault",
    "PackDomain",
    "PackLoadError",
    "PackPolicy",
    "available_pack_ids",
    "list_packs",
    "load_pack",
]
