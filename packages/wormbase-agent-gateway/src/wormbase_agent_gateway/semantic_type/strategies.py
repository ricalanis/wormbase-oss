"""L5 semantic-type fingerprinting — three inference strategies.

Three concrete :class:`FingerprintStrategy` impls, ranked by
``(productivity-today, ground-truth-proximity)``:

  1. :class:`ColumnNameFingerprintStrategy` — **productive today** on
     bare column names from the catalog reader. Regex over 30-40
     patterns covering the 19 semantic types. No data sampled — the
     fastest + cheapest strategy. Mid confidence (0.65-0.90 tier).
  2. :class:`ValuePatternFingerprintStrategy` — requires sampled column
     values via L7's reused :class:`SamplerProtocol`. Regex over a
     window of N=20 sample values; if M/N match a known pattern,
     propose at high confidence (up to 0.95). **Configured ·
     empty-upstream today** — Wave 1 mirror doesn't expose a sampler
     hook (same gap L7 SampleOverlap surfaces).
  3. :class:`DistributionFingerprintStrategy` — requires column-level
     statistical snapshots from L7's reused
     :class:`HistoricalStatsReader`. Heuristics on cardinality / null %
     / range / distinct count. **Configured · empty-upstream today** —
     Wave 1 mirror doesn't emit column-level stats (same gap L7
     HistoricalStats surfaces).

Each strategy is independently constructable + testable. The composite
in :mod:`.composite` consumes any subset via :class:`LakeLoopComposite`
(Optional-Effect Injection doctrine case 12 — first axis to use the
shared abstraction from day one).

Reuse policy: L5 does NOT define new reader Protocols. The two
data-reading strategies inject existing Protocols from L3/L7:

  * :class:`wormbase_agent_gateway.lineage.SamplerProtocol` — value
    sampling (reused by :class:`ValuePatternFingerprintStrategy`).
  * :class:`wormbase_agent_gateway.quality.HistoricalStatsReader` —
    column-level stats (reused by
    :class:`DistributionFingerprintStrategy`).

This minimizes axis-to-axis coupling and proves the
consumer-owned-Protocol pattern composes across L-axes.
"""
from __future__ import annotations

import re
from typing import Any

from wormbase_agent_gateway.lineage.strategies import SamplerProtocol
from wormbase_agent_gateway.quality.strategies import HistoricalStatsReader

from .protocol import (
    FingerprintStrategy,
    ProposedSemanticType,
    SemanticType,
    make_type_id,
)

__all__ = [
    "ColumnNameFingerprintStrategy",
    "DistributionFingerprintStrategy",
    "ValuePatternFingerprintStrategy",
]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _propose(
    *,
    table_id: str,
    column: str,
    semantic_type: SemanticType,
    confidence: float,
    strategy: str,
    reasoning: str,
    evidence: dict[str, Any],
) -> ProposedSemanticType:
    """Construct a :class:`ProposedSemanticType` with canonical ``type_id``.

    Single shared constructor across strategies — guarantees the
    ``type_id`` hash is computed consistently (same dedup key).
    """
    return ProposedSemanticType(
        type_id=make_type_id(
            table_id=table_id,
            column=column,
            semantic_type=semantic_type,
        ),
        table_id=table_id,
        column=column,
        semantic_type=semantic_type,
        confidence=round(max(0.0, min(1.0, confidence)), 4),
        strategy=strategy,
        reasoning=reasoning,
        evidence=evidence,
    )


# ---------------------------------------------------------------------------
# Strategy 1 — ColumnNameFingerprintStrategy (productive today)
# ---------------------------------------------------------------------------


# Default stop-list — too-ambiguous bare column names that should NOT
# trigger any proposal regardless of other matches. The stop-list is
# consulted FIRST: if the lowercased column name is in the set, the
# strategy short-circuits to ``[]``. Per spec §3.3.
_DEFAULT_STOP_LIST: frozenset[str] = frozenset({
    "name",
    "type",
    "value",
    "data",
    "info",
    "label",
    "key",
    "val",
    "code",
    "text",
    "note",
    "notes",
    "comment",
    "comments",
    "description",
    "title",
    "tag",
    "tags",
})


# Pattern table. Each entry is (compiled regex, semantic_type, confidence,
# reason_template). Execution order matters for replay stability: patterns
# fire in declaration order; the first match per semantic_type wins for
# that semantic_type. Multiple distinct semantic_types CAN match the same
# column (e.g. "user_email_address" → email AND pii_name suffix).
#
# Confidence tiers (per spec §3.3):
#   * exact match  — 0.85+
#   * substring/suffix — 0.65-0.80
#   * ambiguous — no proposal (stop-list)
_ColumnNamePattern = tuple[re.Pattern[str], SemanticType, float, str]


def _compile(
    pat: str, st: SemanticType, conf: float, reason: str,
) -> _ColumnNamePattern:
    return (re.compile(pat), st, conf, reason)


_COLUMN_NAME_PATTERNS: tuple[_ColumnNamePattern, ...] = (
    # ---------- email ----------
    _compile(r"(?i)^(email|e_mail|email_address|emailaddress)$", "email", 0.90,
             "exact email column name"),
    _compile(r"(?i).*_email(_address)?$", "email", 0.85,
             "_email suffix"),
    _compile(r"(?i)^email_.*", "email", 0.75,
             "email_ prefix"),

    # ---------- phone ----------
    _compile(r"(?i)^(phone|phone_number|phonenumber|mobile|mobile_number|cell|cell_number)$",
             "phone_e164", 0.75,
             "exact phone column name (assume e164)"),
    _compile(r"(?i).*_phone(_number)?$", "phone_e164", 0.70,
             "_phone suffix"),
    _compile(r"(?i)^(phone_us|us_phone|phone_us_format)$", "phone_us", 0.85,
             "explicit US phone format"),

    # ---------- temporal ----------
    _compile(r"(?i)^(created_at|updated_at|deleted_at|inserted_at|modified_at|"
             r"timestamp|ts|event_time|event_timestamp|occurred_at)$",
             "iso_datetime", 0.85,
             "canonical timestamp column"),
    _compile(r"(?i).*_at$", "iso_datetime", 0.70,
             "_at suffix (iso_datetime)"),
    _compile(r"(?i).*_(datetime|timestamp)$", "iso_datetime", 0.80,
             "_datetime/_timestamp suffix"),
    _compile(r"(?i)^(date|day|birth_date|dob|date_of_birth)$",
             "iso_date", 0.80,
             "date column"),
    _compile(r"(?i).*_date$", "iso_date", 0.75,
             "_date suffix"),
    _compile(r"(?i)^(unix_ts|unix_time|unix_timestamp|epoch|epoch_ms|epoch_seconds)$",
             "unix_timestamp", 0.85,
             "unix timestamp column"),

    # ---------- identifiers ----------
    _compile(r"(?i)^(uuid|guid)$", "uuid_v4", 0.75,
             "uuid/guid column (default v4 assumption)"),
    _compile(r"(?i).*_uuid$", "uuid_v4", 0.75,
             "_uuid suffix"),
    _compile(r"(?i).*_guid$", "uuid_v4", 0.75,
             "_guid suffix"),
    _compile(r"(?i)^(uuid_v7|uuidv7)$", "uuid_v7", 0.85,
             "explicit uuid_v7"),
    _compile(r"(?i)^(business_id|company_id|tenant_id|org_id|account_id|customer_id)$",
             "business_id", 0.70,
             "business-id column (org/tenant/customer)"),
    _compile(r"(?i).*_business_id$", "business_id", 0.80,
             "_business_id suffix"),

    # ---------- geo/locale ----------
    _compile(r"(?i)^(country|country_code|country_iso)$",
             "country_iso", 0.85,
             "country code column"),
    _compile(r"(?i).*_country(_code)?$", "country_iso", 0.75,
             "_country suffix"),
    _compile(r"(?i)^(language|lang|language_code|locale)$",
             "language_iso", 0.80,
             "language code column"),
    _compile(r"(?i).*_language(_code)?$", "language_iso", 0.75,
             "_language suffix"),
    _compile(r"(?i)^(currency|currency_code|currency_iso)$",
             "currency_iso", 0.90,
             "currency code column"),
    _compile(r"(?i).*_currency(_code)?$", "currency_iso", 0.80,
             "_currency suffix"),

    # ---------- PII ----------
    _compile(r"(?i)^(first_name|last_name|full_name|given_name|family_name|"
             r"middle_name|surname|firstname|lastname|fullname)$",
             "pii_name", 0.90,
             "person-name column"),
    _compile(r"(?i).*_(first|last|full|given|family)_name$", "pii_name", 0.85,
             "_first_name/_last_name/etc suffix"),
    _compile(r"(?i)^(address|street_address|home_address|mailing_address|"
             r"billing_address|shipping_address|postal_code|zip|zip_code|zipcode)$",
             "pii_address", 0.85,
             "address column"),
    _compile(r"(?i).*_address$", "pii_address", 0.75,
             "_address suffix"),
    _compile(r"(?i)^(ssn|social_security_number|social_security)$",
             "pii_ssn", 0.95,
             "explicit SSN column"),
    _compile(r"(?i).*_(ssn|social_security)$", "pii_ssn", 0.90,
             "_ssn/_social_security suffix"),
    _compile(r"(?i)^(credit_card|credit_card_number|cc_number|card_number|pan|ccn)$",
             "pii_credit_card", 0.90,
             "explicit credit-card column"),
    _compile(r"(?i).*_credit_card(_number)?$", "pii_credit_card", 0.85,
             "_credit_card suffix"),

    # ---------- metric ----------
    _compile(r"(?i)^(count|cnt|num|number|qty|quantity|num_.*|n_.*)$",
             "metric_count", 0.70,
             "count column"),
    _compile(r"(?i).*_(count|cnt|num|qty|quantity)$", "metric_count", 0.70,
             "_count/_qty suffix"),
    _compile(r"(?i)^(amount|amt|price|cost|total|subtotal|balance|revenue|"
             r"profit|cents|usd|fee|tax)$",
             "metric_amount", 0.75,
             "amount column"),
    _compile(r"(?i).*_(amount|amt|price|cost|cents|usd|fee|tax|revenue)$",
             "metric_amount", 0.75,
             "_amount/_price/etc suffix"),
    _compile(r"(?i)^(rate|ratio|percentage|percent|pct|score)$",
             "metric_rate", 0.70,
             "rate column"),
    _compile(r"(?i).*_(rate|ratio|percentage|percent|pct|score)$",
             "metric_rate", 0.70,
             "_rate/_ratio/etc suffix"),
)


class ColumnNameFingerprintStrategy:
    """Infers semantic types from bare column names via regex.

    **Productive today** — no data sampled, no external readers. Reads
    only the column name string passed by the composite's caller; the
    catalog reader is the canonical source. Fastest + cheapest of the
    three L5 strategies; suitable for high-cadence catalog imports.

    Per spec §3.3:

      * 30-40 patterns covering the 19 semantic types.
      * Stop-list rejects too-ambiguous names (``name``, ``type``,
        ``value`` alone — no proposal).
      * Confidence tiers: exact match (0.85+); substring/suffix
        (0.65-0.80); ambiguous (no proposal).

    Multiple distinct semantic_types may match a single column name
    (e.g. ``user_email_address`` matches both the ``_email`` suffix and
    falls outside the PII bucket). The strategy emits one proposal per
    matched semantic_type; the composite then dedups across strategies
    by ``type_id`` (which includes ``semantic_type``).

    Optional ``stop_list`` override: callers can pass a custom
    :class:`frozenset` to extend / replace the default stop-list (e.g.
    domain-specific column conventions).

    name: str = ``"column_name"``
    """

    name: str = "column_name"

    def __init__(
        self,
        *,
        stop_list: frozenset[str] | None = None,
    ) -> None:
        self.stop_list: frozenset[str] = (
            stop_list if stop_list is not None else _DEFAULT_STOP_LIST
        )

    async def propose(
        self,
        *,
        table_id: str,
        column: str,
        sample_size: int = 20,
    ) -> list[ProposedSemanticType]:
        """Regex over column name; emit 0+ proposals (one per matched type)."""
        del sample_size  # unused — strategy is name-only
        if not column:
            return []
        normalized = column.strip().lower()
        if normalized in self.stop_list:
            return []

        # Track the first (highest-precedence) match per semantic_type
        # so the pattern table's declaration order is honored.
        seen: dict[SemanticType, tuple[float, str, str]] = {}
        for pat, st, conf, reason in _COLUMN_NAME_PATTERNS:
            if pat.fullmatch(column) or pat.match(column):
                if st in seen:
                    continue
                seen[st] = (conf, reason, pat.pattern)

        if not seen:
            return []

        proposals: list[ProposedSemanticType] = []
        for st, (conf, reason, pat_str) in seen.items():
            proposals.append(
                _propose(
                    table_id=table_id,
                    column=column,
                    semantic_type=st,
                    confidence=conf,
                    strategy=self.name,
                    reasoning=(
                        f"column-name regex matched {pat_str!r} → "
                        f"{st} ({reason}) at {conf:.2f}"
                    ),
                    evidence={
                        "regex": pat_str,
                        "reason": reason,
                        "normalized_column": normalized,
                    },
                )
            )
        return proposals


# ---------------------------------------------------------------------------
# Strategy 2 — ValuePatternFingerprintStrategy
# ---------------------------------------------------------------------------


# Per-pattern (regex, semantic_type, confidence, label). Confidence is
# the BASE confidence when match_ratio >= match_ratio_threshold (default
# 0.9). Below threshold → no proposal for that pattern.
#
# Regexes intentionally permissive enough to handle whitespace / case
# variations the producer system might leak through.
_ValuePattern = tuple[re.Pattern[str], SemanticType, float, str]


def _vcompile(
    pat: str, st: SemanticType, conf: float, label: str,
) -> _ValuePattern:
    return (re.compile(pat), st, conf, label)


# RFC5322-ish email (pragmatic, not full grammar).
_EMAIL_REGEX = (
    r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$"
)
_ISO_DATE_REGEX = r"^\d{4}-\d{2}-\d{2}$"
_ISO_DATETIME_REGEX = (
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"
    r"(\.\d+)?(Z|[+\-]\d{2}:?\d{2})?$"
)
_UUID_V4_REGEX = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-"
    r"[89ab][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)
_UUID_V7_REGEX = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-7[0-9a-fA-F]{3}-"
    r"[89ab][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)
_PHONE_E164_REGEX = r"^\+[1-9]\d{6,14}$"
_PHONE_US_REGEX = (
    r"^(\+?1[\s\-\.]?)?\(?\d{3}\)?[\s\-\.]?\d{3}[\s\-\.]?\d{4}$"
)
_US_ZIP_REGEX = r"^\d{5}(-\d{4})?$"
_COUNTRY_ISO_REGEX = r"^[A-Z]{2,3}$"
_LANGUAGE_ISO_REGEX = r"^[a-z]{2,3}(-[A-Z]{2,3})?$"
_CURRENCY_ISO_REGEX = r"^[A-Z]{3}$"


_VALUE_PATTERNS: tuple[_ValuePattern, ...] = (
    _vcompile(_EMAIL_REGEX, "email", 0.95, "RFC5322-ish"),
    _vcompile(_ISO_DATETIME_REGEX, "iso_datetime", 0.95, "ISO 8601 datetime"),
    _vcompile(_ISO_DATE_REGEX, "iso_date", 0.95, "ISO 8601 date"),
    _vcompile(_UUID_V4_REGEX, "uuid_v4", 0.95, "UUID v4 layout"),
    _vcompile(_UUID_V7_REGEX, "uuid_v7", 0.95, "UUID v7 layout"),
    _vcompile(_PHONE_E164_REGEX, "phone_e164", 0.90, "E.164 phone"),
    _vcompile(_PHONE_US_REGEX, "phone_us", 0.80, "US phone format"),
    _vcompile(_US_ZIP_REGEX, "pii_address", 0.70, "US ZIP code"),
    _vcompile(_COUNTRY_ISO_REGEX, "country_iso", 0.65, "ISO 3166 alpha-2/3"),
    _vcompile(_LANGUAGE_ISO_REGEX, "language_iso", 0.65, "ISO 639 / BCP-47"),
    _vcompile(_CURRENCY_ISO_REGEX, "currency_iso", 0.65, "ISO 4217"),
)


class ValuePatternFingerprintStrategy:
    """Infers semantic types from sample values via regex matching.

    Reuses L7's :class:`SamplerProtocol` for value sampling (no new
    cross-axis Protocol — see :mod:`.protocol` reuse-policy docstring).
    Samples N=``sample_size`` values via
    :meth:`SamplerProtocol.sample_column`; for each known pattern, if
    the match ratio (M / N) meets ``match_ratio_threshold`` (default
    0.9), emits one proposal per matched pattern.

    **Configured · empty-upstream today** — Wave 1 catalog mirror
    doesn't expose a sampler hook (same gap L7
    :class:`SampleOverlapStrategy` surfaces). Sub-wave C wires the
    ``NoopSampler`` in production, so the strategy fires on the
    structural code path but returns ``[]``.

    Confidence is the regex's base confidence; the match ratio gate
    keeps false-positive rates low. Empty samples → ``[]`` (no
    proposals — the sampler returned no values to reason over).

    name: str = ``"value_pattern"``
    """

    name: str = "value_pattern"

    DEFAULT_MATCH_RATIO_THRESHOLD: float = 0.9

    def __init__(
        self,
        *,
        sampler: SamplerProtocol,
        match_ratio_threshold: float = DEFAULT_MATCH_RATIO_THRESHOLD,
    ) -> None:
        self.sampler = sampler
        self.match_ratio_threshold = match_ratio_threshold

    async def propose(
        self,
        *,
        table_id: str,
        column: str,
        sample_size: int = 20,
    ) -> list[ProposedSemanticType]:
        """Sample N values; regex-match against known patterns; M/N gate."""
        if sample_size <= 0:
            return []
        samples = await self.sampler.sample_column(table_id, column, sample_size)
        if not samples:
            return []

        # Convert to a list of trimmed string values; preserve uniqueness
        # via the sampler's set semantics. Cap at sample_size.
        values: list[str] = [
            str(v).strip()
            for v in samples
            if isinstance(v, (str, int, float))
        ][:sample_size]
        if not values:
            return []

        n = len(values)
        proposals: list[ProposedSemanticType] = []
        for regex, st, conf, label in _VALUE_PATTERNS:
            match_count = sum(1 for v in values if regex.fullmatch(v))
            ratio = match_count / n if n else 0.0
            if ratio < self.match_ratio_threshold:
                continue
            proposals.append(
                _propose(
                    table_id=table_id,
                    column=column,
                    semantic_type=st,
                    confidence=conf,
                    strategy=self.name,
                    reasoning=(
                        f"{label} regex matched {match_count}/{n} sampled "
                        f"values ({ratio:.0%}); propose {st} at {conf:.2f}"
                    ),
                    evidence={
                        "regex_label": label,
                        "regex": regex.pattern,
                        "match_count": match_count,
                        "sample_n": n,
                        "match_ratio": round(ratio, 4),
                        "match_ratio_threshold": self.match_ratio_threshold,
                    },
                )
            )
        return proposals


# ---------------------------------------------------------------------------
# Strategy 3 — DistributionFingerprintStrategy
# ---------------------------------------------------------------------------


class DistributionFingerprintStrategy:
    """Infers semantic types from column-level statistical distributions.

    Reuses L7's :class:`HistoricalStatsReader` for column-stat reads
    (no new cross-axis Protocol). For each historical snapshot of the
    table, walks the per-column stats blob; emits proposals when a
    column's distribution signature matches a known heuristic:

      * Very high cardinality + all-distinct + UUID-length →
        ``uuid_v4`` at 0.80
      * Float in [0, 1] → ``metric_rate`` at 0.70
      * Positive integers + skewed (mean >> median) → ``metric_count``
        at 0.65

    **Configured · empty-upstream today** — Wave 1 catalog mirror
    doesn't emit column-level stats (same gap L7
    :class:`HistoricalStatsStrategy` surfaces). Sub-wave C wires the
    ``NoopHistoricalStatsReader`` in production, so the strategy fires
    on the structural code path but returns ``[]``.

    Snapshot grammar (Wave-1-future, mirrors L7):

      * Top-level: ``row_count``, ``columns`` list.
      * Per-column dict keys: ``name``, ``distinct_count``,
        ``null_count``, ``min`` / ``max`` (numerics), ``avg_length``
        (strings), optionally ``mean`` / ``median`` for numerics.

    Honest-stub posture: when the reader returns ``[]`` (no snapshots)
    or no per-column stats match the heuristics, the strategy returns
    ``[]`` — no false proposals. Per Sub-wave C, the strategy is gated
    behind ``WORMBASE_FINGERPRINT_DISTRIBUTION_ENABLED`` for auditable
    opt-in.

    name: str = ``"distribution"``
    """

    name: str = "distribution"

    # UUID hex layout (36 chars with hyphens): used by the cardinality+
    # length heuristic to flag uuid_v4 from raw stats without sample
    # values. Pragmatic — the value-pattern strategy is the precise path.
    UUID_AVG_LEN_MIN: float = 32.0
    UUID_AVG_LEN_MAX: float = 36.0

    def __init__(
        self,
        *,
        stats_reader: HistoricalStatsReader,
        min_distinct_ratio_uuid: float = 0.99,
    ) -> None:
        self.stats_reader = stats_reader
        # The fraction of (distinct / row_count) above which we treat a
        # column as effectively all-distinct (uuid-like). Default 0.99
        # to admit small null-leak / hash-collision variance.
        self.min_distinct_ratio_uuid = min_distinct_ratio_uuid

    async def propose(
        self,
        *,
        table_id: str,
        column: str,
        sample_size: int = 20,
    ) -> list[ProposedSemanticType]:
        """Walk the latest snapshot's column stats; emit per matched heuristic."""
        del sample_size  # unused — distribution reads aggregated stats
        snapshots = await self.stats_reader.get_snapshots_for_table(table_id)
        if not snapshots:
            return []

        # Use the latest snapshot (newest last per L7 contract).
        latest = snapshots[-1]
        if not isinstance(latest, dict):
            return []
        columns = latest.get("columns")
        if not isinstance(columns, list):
            return []

        col_stats: dict[str, Any] | None = None
        for c in columns:
            if isinstance(c, dict) and c.get("name") == column:
                col_stats = c
                break
        if col_stats is None:
            return []

        row_count = latest.get("row_count")
        proposals: list[ProposedSemanticType] = []

        # --- uuid heuristic ---
        distinct_count = col_stats.get("distinct_count")
        avg_length = col_stats.get("avg_length")
        if (
            isinstance(distinct_count, (int, float))
            and isinstance(avg_length, (int, float))
            and isinstance(row_count, (int, float))
            and row_count > 0
        ):
            distinct_ratio = float(distinct_count) / float(row_count)
            if (
                distinct_ratio >= self.min_distinct_ratio_uuid
                and self.UUID_AVG_LEN_MIN
                <= float(avg_length)
                <= self.UUID_AVG_LEN_MAX
            ):
                proposals.append(
                    _propose(
                        table_id=table_id,
                        column=column,
                        semantic_type="uuid_v4",
                        confidence=0.80,
                        strategy=self.name,
                        reasoning=(
                            f"distribution: distinct_ratio="
                            f"{distinct_ratio:.3f} (>= "
                            f"{self.min_distinct_ratio_uuid}) + "
                            f"avg_length={avg_length:.1f} in "
                            f"[{self.UUID_AVG_LEN_MIN:.0f}, "
                            f"{self.UUID_AVG_LEN_MAX:.0f}] → uuid_v4 at 0.80"
                        ),
                        evidence={
                            "row_count": row_count,
                            "distinct_count": distinct_count,
                            "distinct_ratio": round(distinct_ratio, 4),
                            "avg_length": avg_length,
                        },
                    )
                )

        # --- metric_rate heuristic: float in [0, 1] ---
        col_min = col_stats.get("min")
        col_max = col_stats.get("max")
        is_float = bool(col_stats.get("is_float"))
        if (
            is_float
            and isinstance(col_min, (int, float))
            and isinstance(col_max, (int, float))
            and 0.0 <= float(col_min)
            and float(col_max) <= 1.0
        ):
            proposals.append(
                _propose(
                    table_id=table_id,
                    column=column,
                    semantic_type="metric_rate",
                    confidence=0.70,
                    strategy=self.name,
                    reasoning=(
                        f"distribution: float column in "
                        f"[{col_min:.3f}, {col_max:.3f}] ⊆ [0, 1] → "
                        f"metric_rate at 0.70"
                    ),
                    evidence={
                        "min": col_min,
                        "max": col_max,
                        "is_float": is_float,
                    },
                )
            )

        # --- metric_count heuristic: positive integers + skewed ---
        is_int = bool(col_stats.get("is_int"))
        mean = col_stats.get("mean")
        median = col_stats.get("median")
        if (
            is_int
            and isinstance(col_min, (int, float))
            and float(col_min) >= 0
            and isinstance(mean, (int, float))
            and isinstance(median, (int, float))
            and float(median) > 0
            and float(mean) > 1.5 * float(median)
        ):
            proposals.append(
                _propose(
                    table_id=table_id,
                    column=column,
                    semantic_type="metric_count",
                    confidence=0.65,
                    strategy=self.name,
                    reasoning=(
                        f"distribution: positive-int column with mean="
                        f"{mean:.1f} >> median={median:.1f} (right-skew) "
                        f"→ metric_count at 0.65"
                    ),
                    evidence={
                        "min": col_min,
                        "max": col_max,
                        "mean": mean,
                        "median": median,
                        "is_int": is_int,
                    },
                )
            )

        return proposals


# Static check: each strategy implements the Protocol.
_proto_check: tuple[type[FingerprintStrategy], ...] = (
    ColumnNameFingerprintStrategy,
    ValuePatternFingerprintStrategy,
    DistributionFingerprintStrategy,
)
del _proto_check
