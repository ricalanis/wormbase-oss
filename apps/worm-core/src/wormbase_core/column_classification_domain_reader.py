"""L6 Sub-wave C — concrete LedgerDomainDefaultReader for column-classification.

Sub-wave B introduced the :class:`DomainDefaultReader` Protocol on the
column_classification subpackage in ``wormbase-agent-gateway``. The
Protocol is the **consumer-owned read surface** for L6's
:class:`DomainDefaultClassificationStrategy` — it reads the existing
onboarding governance domain-pack state to propose a default
classification level for columns whose table belongs to a domain.

This module ships the production impl that
``agent_gateway_construction.compose_column_classification_reactivity_if_enabled``
threads into the strategy at composite construction time.

Implementation approach: ledger-walk + fold replay over the
``emit_domain_pack_selected`` + ``emit_domain_registered`` execute
entries written by the onboarding ``pack_seeder``. Mirrors the rest of
the lake-side readers — ``ledger.fetch(company_id)`` then in-memory
projection.

Domain → table association policy (the honest baseline)
-------------------------------------------------------

The current onboarding doctrine does not yet ship an explicit
table → domain mapping ledger entry; tables surface via
``emit_external_catalog_imported`` (lake-side) while domains surface
via ``emit_domain_registered`` (governance-side). The L6 spec §4.3
calls for a "pack default" with low confidence (0.60) so admins can
override; the strategy fires when a pack is selected and proposes the
domain default.

The honest baseline this impl ships:

* When a domain pack is selected AND at least one domain has been
  registered with a default_classification that maps to one of the 5
  canonical :class:`ClassificationLevel` values, return the
  alphabetically-first registered domain's
  ``(default_classification, domain_id)``.
* When no pack is selected OR no domain matches → return ``None``
  (the strategy fires no proposals via the domain_default path).

Rationale: the strategy is structurally complete and exercises the
domain-pack signal; an explicit per-table-domain mapping is a future
enhancement (Wave 1+ when ``resource_role_assigned`` /
``resource_classification_proposed`` ledger entries land). Until then,
the baseline ships an honest signal that admins can override per
spec §4.3 (low confidence 0.60 = "admin should pick a more specific
strategy's signal").

Replay-stable: deterministic sort by domain id; same ledger state →
same return value.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

logger = logging.getLogger(
    "wormbase_core.column_classification_domain_reader",
)

__all__ = [
    "LedgerDomainDefaultReader",
]

# The 5 canonical classification levels per CLAUDE.md
# §"Ledger-native governance" and the L6 spec §4.2 ClassificationLevel
# Literal. We accept registered domains whose default_classification
# value is one of these; anything else (e.g. "operational" from a
# legacy pack) returns None rather than coerce.
_VALID_LEVELS: frozenset[str] = frozenset(
    {"public", "internal", "confidential", "pii", "regulated"},
)


class _LedgerFetcher(Protocol):
    """Minimal surface — fetch-by-company_id async returning ledger rows."""

    async def fetch(
        self, company_id: UUID, until_ts: Any | None = ...,
    ) -> list[dict[str, Any]]: ...  # pragma: no cover


def _is_emit_tool(entry: dict[str, Any], tool: str) -> bool:
    """True iff this is an execute entry whose payload.tool matches ``tool``."""
    if entry.get("kind") != "execute":
        return False
    payload = entry.get("payload") or {}
    if not isinstance(payload, dict):
        return False
    return payload.get("tool") == tool


def _execute_args(entry: dict[str, Any]) -> dict[str, Any]:
    """Extract the ``args`` dict from an execute entry's payload."""
    if entry.get("kind") != "execute":
        return {}
    payload = entry.get("payload") or {}
    if not isinstance(payload, dict):
        return {}
    args = payload.get("args") or {}
    if not isinstance(args, dict):
        return {}
    return args


@dataclass
class LedgerDomainDefaultReader:
    """Reads onboarding governance state to propose domain-pack defaults.

    Implements the
    :class:`wormbase_agent_gateway.column_classification.DomainDefaultReader`
    Protocol. L6's :class:`DomainDefaultClassificationStrategy` injects
    this reader to look up the active domain pack's default
    classification for the column under classification.

    Tenant scope rides on ``company_id`` per call. No per-instance
    tenant pinning — the reader is shared and each strategy invocation
    passes its own company_id.

    Graceful no-op posture:

    * No ``emit_domain_pack_selected`` execute entry → returns ``None``.
    * Pack selected but no ``emit_domain_registered`` entries (e.g.
      legacy install) → returns ``None``.
    * Domains registered but none with a valid 5-level
      ``default_classification`` → returns ``None``.

    The strategy treats ``None`` as "no proposal via this path" — the
    other two L6 strategies (semantic_type + naming_pattern) still
    fire independently.
    """

    ledger: _LedgerFetcher

    async def get_classification_default_for_table(
        self,
        *,
        table_id: str,
        company_id: UUID,
    ) -> tuple[str, str] | None:
        """Return ``(classification_level, domain_id)`` or ``None``.

        Reads existing ``emit_domain_pack_selected`` +
        ``emit_domain_registered`` ledger entries from the onboarding
        wave's governance flow.

        Per the module-level docstring: this returns the
        alphabetically-first registered domain's
        ``(default_classification, domain_id)`` when a pack is selected
        AND at least one domain has a valid 5-level
        ``default_classification``. Returns ``None`` otherwise.

        The ``table_id`` argument is part of the Protocol surface
        (future versions will resolve per-table-domain associations
        once ``resource_role_assigned`` lands) but is currently
        used only as a non-emptiness guard — empty / falsy
        ``table_id`` always returns ``None``.
        """
        if not table_id:
            return None

        entries = await self.ledger.fetch(company_id)

        # Walk the ledger once. Two signals we care about:
        # 1) Has any ``emit_domain_pack_selected`` execute entry fired?
        # 2) What domains have been registered, with which defaults?
        pack_selected = False
        # domain_id -> default_classification (latest write wins for
        # the same domain_id, matching the projection-fold semantics
        # of governance writes).
        registered_domains: dict[str, str] = {}

        for entry in entries:
            if _is_emit_tool(entry, "emit_domain_pack_selected"):
                pack_selected = True
            elif _is_emit_tool(entry, "emit_domain_registered"):
                args = _execute_args(entry)
                domain_id = str(args.get("id") or "")
                default_class = args.get("default_classification")
                if not domain_id:
                    continue
                if not isinstance(default_class, str):
                    continue
                if default_class not in _VALID_LEVELS:
                    # Skip drift-class values (e.g. "operational" from
                    # a legacy pack). The reader stays honest about
                    # which levels can flow into L6.
                    logger.debug(
                        "skipping domain %s: default_classification "
                        "%r not in canonical 5-value enum",
                        domain_id, default_class,
                    )
                    continue
                registered_domains[domain_id] = default_class

        if not pack_selected:
            return None
        if not registered_domains:
            return None

        # Deterministic pick: alphabetically-first domain_id wins.
        # Stable across runs — same ledger state → same tuple.
        first_domain_id = sorted(registered_domains)[0]
        return (registered_domains[first_domain_id], first_domain_id)
