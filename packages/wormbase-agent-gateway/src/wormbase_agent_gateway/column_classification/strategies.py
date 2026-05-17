"""L6 column-level governance classification — three inference strategies.

Three concrete :class:`ColumnClassificationStrategy` impls, ranked by
``(productivity-today, ground-truth-proximity)``:

  1. :class:`NamingPatternClassificationStrategy` — **productive
     today** on bare column names from the catalog reader. Regex over
     credential/secret/PII patterns. No data sampled, no upstream
     dependency. Fastest + cheapest of the three L6 strategies; fires
     even without L5 enabled.
  2. :class:`SemanticTypeClassificationStrategy` — **the cross-axis
     chain**. Reads L5's confirmed semantic types via the new
     :class:`ConfirmedSemanticTypeReader` Protocol and maps each value
     to a classification level + base confidence. Productive when L5
     has confirmed types; empty-upstream until then.
  3. :class:`DomainDefaultClassificationStrategy` — reads domain pack
     classification_defaults via the consumer-owned
     :class:`DomainDefaultReader` Protocol (governance integration
     point; concrete impl lives in worm-core wiring). For each column
     whose table belongs to a domain with a default, proposes that
     level at low confidence (0.60). Productive when an onboarding
     domain pack is selected; empty-upstream otherwise.

Each strategy is independently constructable + testable. The composite
in :mod:`.composite` consumes any subset via :class:`LakeLoopComposite`
(Optional-Effect Injection doctrine case 13).

Cross-axis policy: L6 introduces ONE new cross-axis Protocol
(:class:`ConfirmedSemanticTypeReader` — the 2nd instance after L4's
:class:`LineageEdgeReader`). The domain_default strategy uses a small
consumer-owned :class:`DomainDefaultReader` Protocol for the same
minimum-coupling reason. Both fulfill the canonical cross-axis-read
template.
"""
from __future__ import annotations

import re
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from .protocol import (
    ClassificationLevel,
    ColumnClassificationStrategy,
    ConfirmedSemanticTypeReader,
    ConfirmedSemanticTypeRecord,
    ProposedColumnClassification,
    make_classification_id,
)

__all__ = [
    "DomainDefaultClassificationStrategy",
    "DomainDefaultReader",
    "NamingPatternClassificationStrategy",
    "SemanticTypeClassificationStrategy",
]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _propose(
    *,
    table_id: str,
    column: str,
    classification_level: ClassificationLevel,
    upstream_semantic_type_id: str | None,
    confidence: float,
    strategy: str,
    reasoning: str,
    evidence: dict[str, Any],
) -> ProposedColumnClassification:
    """Construct a :class:`ProposedColumnClassification` with canonical id.

    Single shared constructor across strategies — guarantees the
    ``classification_id`` hash is computed consistently (same dedup
    key per strategy).
    """
    return ProposedColumnClassification(
        classification_id=make_classification_id(
            table_id=table_id,
            column=column,
            classification_level=classification_level,
            strategy=strategy,
        ),
        table_id=table_id,
        column=column,
        classification_level=classification_level,
        upstream_semantic_type_id=upstream_semantic_type_id,
        confidence=round(max(0.0, min(1.0, confidence)), 4),
        strategy=strategy,
        reasoning=reasoning,
        evidence=evidence,
    )


# ---------------------------------------------------------------------------
# Strategy 1 — SemanticTypeClassificationStrategy (cross-axis to L5)
# ---------------------------------------------------------------------------


# Mapping per spec §4.3: L5 semantic_type → (classification_level,
# base_confidence, reason). Each L5 value maps to exactly one L6
# proposal; duplicates of the same level across different L5 types on
# the same column merge via the composite's dedup.
_SEMANTIC_TYPE_TO_CLASSIFICATION: dict[
    str, tuple[ClassificationLevel, float, str],
] = {
    # PII (sensitive — regulated tier)
    "pii_credit_card": ("regulated", 0.95, "PCI scope"),
    "pii_ssn": ("regulated", 0.95, "HIPAA/SOC-2 scope"),
    # PII (standard tier)
    "pii_name": ("pii", 0.95, "personal name"),
    "pii_address": ("pii", 0.95, "personal address"),
    # Identity (often-PII even when sometimes-public)
    "email": ("pii", 0.90, "email — PII even when sometimes public"),
    "phone_e164": ("pii", 0.90, "phone number — PII"),
    "phone_us": ("pii", 0.90, "phone number — PII"),
    # Metrics (internal default)
    "metric_count": ("internal", 0.70, "count metric — internal default"),
    "metric_amount": ("internal", 0.70, "amount metric — internal default"),
    "metric_rate": ("internal", 0.70, "rate metric — internal default"),
    # Identifiers (internal default)
    "uuid_v4": ("internal", 0.60, "uuid identifier — internal default"),
    "uuid_v7": ("internal", 0.60, "uuid identifier — internal default"),
    "business_id": ("internal", 0.60, "business identifier — internal default"),
    # Geo/locale (public)
    "country_iso": ("public", 0.85, "ISO country code — public"),
    "language_iso": ("public", 0.85, "ISO language code — public"),
    "currency_iso": ("public", 0.85, "ISO currency code — public"),
    # Temporal (internal — timestamps usually safe)
    "iso_date": ("internal", 0.50, "date — usually internal-safe"),
    "iso_datetime": ("internal", 0.50, "datetime — usually internal-safe"),
    "unix_timestamp": ("internal", 0.50, "unix ts — usually internal-safe"),
}


class SemanticTypeClassificationStrategy:
    """Maps L5-confirmed semantic types to L6 classification levels.

    **The cross-axis chain.** Reads L5's confirmed semantic types via
    the injected :class:`ConfirmedSemanticTypeReader` Protocol and emits
    one classification proposal per (L5 type → L6 level) mapping in the
    table. Productive when L5 has confirmed types; empty-upstream until
    then.

    Mapping table per spec §4.3 (see
    :data:`_SEMANTIC_TYPE_TO_CLASSIFICATION` for the full set):

      * ``pii_credit_card``, ``pii_ssn`` → ``regulated`` at 0.95
        (compliance-scoped)
      * ``pii_name``, ``pii_address`` → ``pii`` at 0.95
      * ``email``, ``phone_*`` → ``pii`` at 0.90
      * ``metric_*`` → ``internal`` at 0.70
      * ``uuid_*``, ``business_id`` → ``internal`` at 0.60
      * ``country_iso``, ``language_iso``, ``currency_iso`` → ``public``
        at 0.85
      * ``iso_date``, ``iso_datetime``, ``unix_timestamp`` → ``internal``
        at 0.50 (timestamps usually safe)
      * ``other`` and any unmapped value → no proposal

    Sets :attr:`ProposedColumnClassification.upstream_semantic_type_id`
    to the L5 record's ``type_id`` so the /lake/column-classification
    surface can render the "view L5 semantic type →" cross-axis link.

    When multiple L5 types are confirmed on the same column, this
    strategy emits one proposal per mapped (level, type) pair. The
    composite dedups by ``classification_id`` (which includes
    strategy + level but not the upstream type) so two L5 types
    mapping to the SAME level merge into one proposal — the merge's
    ``upstream_semantic_type_id`` is the highest-confidence
    contributor.

    name: str = ``"semantic_type"``
    """

    name: str = "semantic_type"

    def __init__(
        self,
        *,
        semantic_type_reader: ConfirmedSemanticTypeReader,
    ) -> None:
        self.semantic_type_reader = semantic_type_reader

    async def propose(
        self,
        *,
        table_id: str,
        column: str,
        company_id: UUID,
    ) -> list[ProposedColumnClassification]:
        """Read L5 confirmed types; map each to a classification."""
        if not table_id or not column:
            return []
        records = await self.semantic_type_reader.list_confirmed_types_for_table_column(
            table_id=table_id,
            column=column,
            company_id=company_id,
        )
        if not records:
            return []

        # Track per-level the contributing L5 type with the highest
        # upstream confidence — that one wins as the
        # upstream_semantic_type_id for the (per-strategy)
        # classification_id. Replay-stability: iterate records in
        # input order, ties broken by first-seen.
        per_level: dict[
            ClassificationLevel,
            tuple[ConfirmedSemanticTypeRecord, float, str, str],
        ] = {}
        for record in records:
            mapping = _SEMANTIC_TYPE_TO_CLASSIFICATION.get(record.semantic_type)
            if mapping is None:
                continue
            level, base_conf, reason = mapping
            existing = per_level.get(level)
            if existing is None or record.confidence > existing[1]:
                per_level[level] = (record, base_conf, reason, record.semantic_type)

        proposals: list[ProposedColumnClassification] = []
        for level, (record, base_conf, reason, semantic_type) in per_level.items():
            proposals.append(
                _propose(
                    table_id=table_id,
                    column=column,
                    classification_level=level,
                    upstream_semantic_type_id=record.type_id,
                    confidence=base_conf,
                    strategy=self.name,
                    reasoning=(
                        f"L5 confirmed {semantic_type!r} (confidence "
                        f"{record.confidence:.2f}) → {level} at "
                        f"{base_conf:.2f} ({reason})"
                    ),
                    evidence={
                        "semantic_type": semantic_type,
                        "upstream_type_confidence": record.confidence,
                        "upstream_l5_strategy": record.strategy,
                        "reason": reason,
                    },
                )
            )
        return proposals


# ---------------------------------------------------------------------------
# Strategy 2 — NamingPatternClassificationStrategy (independent of L5)
# ---------------------------------------------------------------------------


# Pattern table. Each entry is (compiled regex, classification_level,
# confidence, reason). Execution order matters for replay stability:
# the first matched pattern per (column, level) wins so reasoning is
# deterministic. Multiple distinct levels CAN match the same column
# (e.g. ``customer_internal_ssn`` matches both ``_internal_`` →
# internal AND ``_ssn`` → regulated); the composite dedups via
# classification_id (which includes level + strategy).
_NamingPattern = tuple[re.Pattern[str], ClassificationLevel, float, str]


def _ncompile(
    pat: str, level: ClassificationLevel, conf: float, reason: str,
) -> _NamingPattern:
    return (re.compile(pat), level, conf, reason)


_NAMING_PATTERNS: tuple[_NamingPattern, ...] = (
    # ---------- confidential (credentials/secrets) ----------
    # ``*_<credential>`` glob from spec §4.3 — must have an underscore
    # separator before the credential keyword (so ``user_secret`` matches
    # but bare ``secret`` does NOT, avoiding false-positives on common
    # column names like ``trade_secret_id``). The ``(_.*)?$`` tail also
    # admits suffixes like ``user_secret_v2``.
    _ncompile(r"(?i).*_secret(_.*)?$", "confidential", 0.95,
              "_secret column — credential pattern"),
    _ncompile(r"(?i).*_password(_.*)?$", "confidential", 0.95,
              "_password column — credential pattern"),
    _ncompile(r"(?i).*_api_key(_.*)?$", "confidential", 0.95,
              "_api_key column — credential pattern"),
    _ncompile(r"(?i).*_token(_.*)?$", "confidential", 0.95,
              "_token column — credential pattern"),

    # ---------- regulated (compliance-scoped PII) ----------
    # ``*_ssn`` glob plus bare ``ssn`` (spec admits the unprefixed form
    # — see :func:`make_classification_id` audit test).
    _ncompile(r"(?i).*_ssn(_.*)?$|^ssn$", "regulated", 0.95,
              "_ssn column — regulated PII"),
    _ncompile(r"(?i).*_tax_id(_.*)?$|^tax_id$", "regulated", 0.95,
              "_tax_id column — regulated PII"),

    # ---------- internal (explicit naming convention) ----------
    _ncompile(r"(?i).*_internal_.*", "internal", 0.80,
              "_internal_ naming convention"),

    # ---------- public (explicit naming convention) ----------
    _ncompile(r"(?i).*_public_.*", "public", 0.85,
              "_public_ naming convention"),
)


class NamingPatternClassificationStrategy:
    """Regex over column names → classification level.

    **Productive today** — no data sampled, no upstream readers
    consulted. Independent of L5. Reads only the column name string
    passed by the composite's caller; fires even when L5 is disabled.

    Per spec §4.3:

      * ``*_secret``, ``*_password``, ``*_api_key``, ``*_token`` →
        ``confidential`` at 0.95
      * ``*_ssn``, ``*_tax_id`` → ``regulated`` at 0.95
      * ``*_internal_*`` → ``internal`` at 0.80
      * ``*_public_*`` → ``public`` at 0.85

    Multiple distinct levels MAY match a single column name (e.g.
    ``customer_internal_ssn``). The strategy emits one proposal per
    matched level; the composite then dedups across strategies by
    ``classification_id`` (which includes level + strategy).

    name: str = ``"naming_pattern"``
    """

    name: str = "naming_pattern"

    async def propose(
        self,
        *,
        table_id: str,
        column: str,
        company_id: UUID,
    ) -> list[ProposedColumnClassification]:
        """Regex over column name; emit 0+ proposals (one per matched level)."""
        del company_id  # unused — naming pattern is column-only
        if not table_id or not column:
            return []

        # Track first-matched (highest-precedence) pattern per level so
        # the declaration order is honored. Replay-stable.
        seen: dict[ClassificationLevel, tuple[float, str, str]] = {}
        for pat, level, conf, reason in _NAMING_PATTERNS:
            if pat.fullmatch(column) or pat.match(column):
                if level in seen:
                    continue
                seen[level] = (conf, reason, pat.pattern)

        if not seen:
            return []

        proposals: list[ProposedColumnClassification] = []
        for level, (conf, reason, pat_str) in seen.items():
            proposals.append(
                _propose(
                    table_id=table_id,
                    column=column,
                    classification_level=level,
                    upstream_semantic_type_id=None,
                    confidence=conf,
                    strategy=self.name,
                    reasoning=(
                        f"naming-pattern regex matched {pat_str!r} → "
                        f"{level} ({reason}) at {conf:.2f}"
                    ),
                    evidence={
                        "regex": pat_str,
                        "reason": reason,
                        "matched_column": column,
                    },
                )
            )
        return proposals


# ---------------------------------------------------------------------------
# Strategy 3 — DomainDefaultClassificationStrategy
# ---------------------------------------------------------------------------


@runtime_checkable
class DomainDefaultReader(Protocol):
    """Reads domain-pack classification defaults for a table.

    Consumer-owned Protocol (mirrors the cross-axis pattern). The
    concrete impl lives in worm-core wiring (Sub-wave C) and reads the
    existing governance domain-pack state from onboarding.

    Tenant isolation rides on ``company_id``.

    Replay-stability: implementations MUST be deterministic for a given
    ``(company_id, table_id)``.
    """

    async def get_classification_default_for_table(
        self,
        *,
        table_id: str,
        company_id: UUID,
    ) -> tuple[ClassificationLevel, str] | None:
        """Return the (classification_level, domain_id) default for the table.

        Returns ``None`` when:

          * No domain pack is selected for the tenant.
          * The table is not associated with any domain.
          * The selected domain pack has no classification_default
            (some packs intentionally leave it unset).

        Returns ``(level, domain_id)`` tuple when a default applies.
        The ``domain_id`` is surfaced in evidence for the audit trail.
        """
        ...


class DomainDefaultClassificationStrategy:
    """Proposes the domain-pack default classification for a column.

    Reads domain pack ``classification_defaults`` via the injected
    :class:`DomainDefaultReader` Protocol. For each column whose table
    belongs to a domain with a default, proposes that classification
    level at 0.60 (low confidence; admin should override with specific
    signals from the other two strategies).

    **Productive today** when a domain pack is selected (post-
    onboarding). Empty-upstream when:

      * No domain pack selected (reader returns ``None``).
      * Table not associated with a domain.
      * Domain pack has no classification_default for this resource
        type.

    Independent of L5. Fires on naked column names.

    name: str = ``"domain_default"``
    """

    name: str = "domain_default"
    DEFAULT_CONFIDENCE: float = 0.60

    def __init__(
        self,
        *,
        domain_default_reader: DomainDefaultReader,
        confidence: float = DEFAULT_CONFIDENCE,
    ) -> None:
        self.domain_default_reader = domain_default_reader
        # Per spec §4.3: low confidence — admin should override with
        # other strategies' more specific signals.
        self.confidence = confidence

    async def propose(
        self,
        *,
        table_id: str,
        column: str,
        company_id: UUID,
    ) -> list[ProposedColumnClassification]:
        """Read domain-pack default for the table; emit 0-1 proposal."""
        if not table_id or not column:
            return []
        result = await self.domain_default_reader.get_classification_default_for_table(
            table_id=table_id,
            company_id=company_id,
        )
        if result is None:
            return []
        level, domain_id = result
        return [
            _propose(
                table_id=table_id,
                column=column,
                classification_level=level,
                upstream_semantic_type_id=None,
                confidence=self.confidence,
                strategy=self.name,
                reasoning=(
                    f"domain-pack default for domain {domain_id!r}: "
                    f"{level} at {self.confidence:.2f} (admin should "
                    f"override with more specific signals)"
                ),
                evidence={
                    "domain_id": domain_id,
                    "domain_default_level": level,
                },
            ),
        ]


# Static check: each strategy implements the Protocol.
_proto_check: tuple[type[ColumnClassificationStrategy], ...] = (
    NamingPatternClassificationStrategy,
)
del _proto_check
