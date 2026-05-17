"""L1 source-candidate triage — three acquisition inference strategies.

Three concrete :class:`SourceCandidateStrategy` impls, ranked by
``(productivity-today, ground-truth-proximity)``:

  1. :class:`KpiGapAcquisitionStrategy` — reads
     :class:`KpiNodeReader`; maps KPI name patterns to connector kinds
     (``*_revenue`` / ``*_sales`` / ``*_arr`` → ``stripe`` /
     ``salesforce``; ``*_signups`` / ``*_users`` / ``*_dau`` →
     ``postgres`` / ``mcp:notion``; ``*_pipeline`` / ``*_leads`` →
     ``hubspot`` / ``salesforce``; fallback ``csv_local``). Threads the
     KPI's owning ``domain_id`` through as ``domain_id_hint``.
     **Productive today** when KPI tree has unbacked nodes; **`configured
     · awaiting-kpi-tree-population`** when the KPI tree is empty
     (honest stub).
  2. :class:`ChannelMentionAcquisitionStrategy` — reads
     :class:`SilverConversationReader`; regex bank of ~30 patterns
     covering top connectors (``"our snowflake"``, ``"export from
     stripe"``, etc.). For each match: propose the mentioned connector
     kind with ``evidence.message_refs`` carrying the originating
     message id so admin can navigate. **Configured ·
     empty-upstream** today when the silver projection has no rows
     (honest stub — per Sub-wave A handoff concern #1); productive
     once the silver pipeline lands signal.
  3. :class:`ComplementaritySourceStrategy` — reads
     :class:`ConnectedSourceReader`; portfolio-gap heuristics
     (sales-heavy portfolio → propose marketing source; finance-heavy
     → propose product/usage source; no file source → propose
     ``csv_local``). **Productive today** as soon as ≥1 source is
     connected (static heuristic, no upstream signal dependency).

Each strategy is independently constructable + testable. The composite
in :mod:`.composite` consumes any subset via :class:`LakeLoopComposite`
(Optional-Effect Injection doctrine case 15).

Confidence scale per L1 spec §4.3 (lower than other axes by design;
L1's ``MIN_CONFIDENCE`` floor of 0.4 is configured at the env knob
``WORMBASE_SOURCE_CANDIDATE_MIN_CONFIDENCE``):

  * KpiGap: 0.40 (fallback csv_local) - 0.80 (high-signal pattern match)
  * ChannelMention: 0.50 - 0.75 (regex matches are noisy by definition)
  * Complementarity: 0.40 - 0.65 (portfolio heuristic; weakest signal)

Reuse posture — L1 introduces 3 NEW lightweight Reader Protocols (see
:mod:`.protocol` for the doctrine clarification that these are NOT
cross-axis chains — they read first-class platform projections, not
peer L-axis projections). The strategies own the Readers as
construction-time dependencies.
"""
from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from .protocol import (
    ConnectedSourceReader,
    KpiNodeReader,
    ProposedSourceCandidate,
    SilverConversationReader,
    SourceCandidateStrategy,
    make_candidate_id,
)

__all__ = [
    "ChannelMentionAcquisitionStrategy",
    "ComplementaritySourceStrategy",
    "KpiGapAcquisitionStrategy",
]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _build_candidate(
    *,
    proposed_kind: str,
    proposed_identifier: str,
    strategy: str,
    confidence: float,
    reasoning: str,
    evidence: dict[str, Any],
    domain_id_hint: str | None = None,
) -> ProposedSourceCandidate:
    """Construct a :class:`ProposedSourceCandidate` with canonical
    ``candidate_id``.

    Single shared constructor across strategies — guarantees the
    ``candidate_id`` hash is computed consistently across strategies
    via :func:`make_candidate_id`. Confidence is clamped to [0.0, 1.0]
    and rounded to 4 places for ledger-write byte-stability.
    """
    return ProposedSourceCandidate(
        candidate_id=make_candidate_id(
            proposed_kind=proposed_kind,
            proposed_identifier=proposed_identifier,
            strategy=strategy,
        ),
        proposed_kind=proposed_kind,
        proposed_identifier=proposed_identifier,
        domain_id_hint=domain_id_hint,
        confidence=round(max(0.0, min(1.0, confidence)), 4),
        strategy=strategy,
        reasoning=reasoning,
        evidence=evidence,
    )


# ---------------------------------------------------------------------------
# Strategy 1 — KpiGapAcquisitionStrategy
# ---------------------------------------------------------------------------


# Pattern bank: substring → (connector_kind, fallback_kind, confidence,
# reasoning_suffix). Patterns are checked in declaration order; first
# match wins. Substring matching is case-insensitive against the
# normalised KPI name; the patterns are conservative (require concrete
# domain tokens like "revenue" / "signups" / "pipeline").
#
# Mapping rationale per spec §4.3:
# - revenue/sales/arr → billing/CRM systems (stripe / salesforce)
# - signups/users/dau → app database / docs (postgres / mcp:notion)
# - pipeline/leads/opportunities → CRM (hubspot / salesforce)
# Fallback for unmatched gaps → csv_local at low confidence
_KPI_PATTERN_BANK: list[tuple[str, str, str, float, str]] = [
    # (pattern_substring, primary_kind, alt_kind, confidence, reasoning)
    ("revenue", "stripe", "salesforce", 0.80, "revenue KPI"),
    ("sales", "stripe", "salesforce", 0.75, "sales KPI"),
    ("arr", "stripe", "salesforce", 0.75, "ARR KPI"),
    ("mrr", "stripe", "salesforce", 0.75, "MRR KPI"),
    ("signups", "postgres", "mcp:notion", 0.65, "signups KPI"),
    ("users", "postgres", "mcp:notion", 0.60, "users KPI"),
    ("dau", "postgres", "mcp:notion", 0.65, "DAU KPI"),
    ("mau", "postgres", "mcp:notion", 0.65, "MAU KPI"),
    ("pipeline", "hubspot", "salesforce", 0.70, "pipeline KPI"),
    ("leads", "hubspot", "salesforce", 0.65, "leads KPI"),
    ("opportunities", "hubspot", "salesforce", 0.65, "opportunities KPI"),
]

# Fallback when no pattern matches — propose a manual file drop at low
# confidence. Per spec §4.3 — "no domain inference; manual file drop
# suggested." Kept distinct from the pattern bank so callers can
# inspect or override it.
_KPI_FALLBACK_KIND: str = "csv_local"
_KPI_FALLBACK_CONFIDENCE: float = 0.40


class KpiGapAcquisitionStrategy:
    """KPI-driven source proposal: scan unbacked KPI nodes; map names → connectors.

    Reads :class:`KpiNodeReader.list_kpi_nodes_without_source` to enumerate
    KPI nodes that have NO backing data source. For each unbacked node:

      * Normalises the KPI ``name`` (lowercased, underscores kept) and
        scans the pattern bank in declaration order. First-match wins:
        the primary kind becomes the proposal's ``proposed_kind`` at
        the matched confidence; the alt kind is recorded in
        ``evidence.alternative_kind`` so admin can swap on triage.
      * When no pattern matches, falls back to ``csv_local`` at 0.40
        confidence with reasoning "no domain inference; manual file
        drop suggested" (per spec §4.3).
      * Threads the KPI's ``domain_id`` through as ``domain_id_hint``
        on the proposal so the admin surface groups by domain.

    The strategy emits ONE proposal per unbacked KPI node. When the
    KPI tree has no unbacked nodes (every KPI is backed OR the tree is
    empty), the strategy returns ``[]`` — the honest stub posture per
    spec §4.3 / "configured · awaiting-kpi-tree-population".

    ``proposed_identifier`` is the KPI name (e.g.
    ``"kpi:q3_net_revenue"``) so admin can recognise which gap this
    candidate addresses without cross-referencing.

    name: str = ``"kpi_gap"``
    """

    name: str = "kpi_gap"

    def __init__(
        self,
        *,
        kpi_node_reader: KpiNodeReader,
    ) -> None:
        # Required dependency — no None-defaults. KpiGap is meaningless
        # without a reader; callers wire one at construction time.
        self.kpi_node_reader = kpi_node_reader

    async def propose(
        self,
        *,
        company_id: UUID,
    ) -> list[ProposedSourceCandidate]:
        """Scan unbacked KPI nodes; emit one candidate proposal per gap."""
        kpi_nodes = await self.kpi_node_reader.list_kpi_nodes_without_source(
            company_id=company_id,
        )
        if not kpi_nodes:
            # Honest stub posture per spec §4.3 — KPI tree empty or no
            # unbacked nodes → no proposals (the reader did the filter).
            return []

        proposals: list[ProposedSourceCandidate] = []
        for node in kpi_nodes:
            normalized_name = node.name.strip().lower()
            if not normalized_name:
                continue

            matched_entry: tuple[str, str, float, str] | None = None
            for pattern, primary, alt, conf, suffix in _KPI_PATTERN_BANK:
                if pattern in normalized_name:
                    matched_entry = (primary, alt, conf, suffix)
                    break

            if matched_entry is not None:
                primary_kind, alt_kind, confidence, suffix = matched_entry
                reasoning = (
                    f"KPI {node.name!r} matches {suffix} pattern; "
                    f"propose {primary_kind} at {confidence:.2f} "
                    f"(alt: {alt_kind})"
                )
                evidence: dict[str, Any] = {
                    "kpi_node_id": node.kpi_node_id,
                    "kpi_name": node.name,
                    "matched_pattern": suffix,
                    "alternative_kind": alt_kind,
                }
            else:
                primary_kind = _KPI_FALLBACK_KIND
                confidence = _KPI_FALLBACK_CONFIDENCE
                reasoning = (
                    f"KPI {node.name!r} has no domain inference; "
                    f"manual file drop suggested at {confidence:.2f}"
                )
                evidence = {
                    "kpi_node_id": node.kpi_node_id,
                    "kpi_name": node.name,
                    "matched_pattern": "fallback",
                }

            proposals.append(
                _build_candidate(
                    proposed_kind=primary_kind,
                    proposed_identifier=f"kpi:{node.name}",
                    strategy=self.name,
                    confidence=confidence,
                    reasoning=reasoning,
                    evidence=evidence,
                    domain_id_hint=node.domain_id,
                ),
            )
        return proposals


# ---------------------------------------------------------------------------
# Strategy 2 — ChannelMentionAcquisitionStrategy
# ---------------------------------------------------------------------------


# Pattern bank: regex → connector_kind. Patterns are case-insensitive
# and intentionally conservative (require concrete vendor / product
# tokens). The bank covers the 10 day-one native connectors + the
# common MCP presets so a fresh worm catches the most common
# source-mention phrasings without dragging in NLP infrastructure.
#
# Bank size: ~30 patterns per spec §4.3 (honest regex bank; future
# waves can swap in the existing channel-mention NLP).
_CHANNEL_MENTION_PATTERN_BANK: list[tuple[re.Pattern[str], str, str]] = [
    # (compiled_regex, connector_kind, reasoning_excerpt)
    # csv_local
    (re.compile(r"\b(csv|excel|spreadsheet)\s+(file|export|attach)", re.I),
     "csv_local", "CSV/Excel file mention"),
    (re.compile(r"\bgoogle\s+sheet|gsheet|google\s+spreadsheet", re.I),
     "gsheets", "Google Sheets mention"),
    (re.compile(r"\bthe\s+marketing\s+(google\s+)?sheet", re.I),
     "gsheets", "marketing Google Sheet mention"),
    # postgres / databases
    (re.compile(r"\bpostgres(ql)?\b|\bpg\s+(db|database)\b", re.I),
     "postgres", "Postgres mention"),
    (re.compile(r"\bour\s+(app\s+)?database\b", re.I),
     "postgres", "app database mention"),
    # snowflake
    (re.compile(r"\bsnowflake\b", re.I), "snowflake", "Snowflake mention"),
    (re.compile(r"\bour\s+(snowflake\s+)?warehouse\b", re.I),
     "snowflake", "warehouse mention"),
    # bigquery
    (re.compile(r"\bbig\s*query\b|\bbq\b", re.I),
     "bigquery", "BigQuery mention"),
    (re.compile(r"\bgoogle\s+cloud\s+(big\s*query|warehouse)", re.I),
     "bigquery", "GCP warehouse mention"),
    # s3_csv
    (re.compile(r"\bs3\s+(bucket|csv|export|files?)", re.I),
     "s3_csv", "S3 CSV mention"),
    (re.compile(r"\baws\s+s3\b", re.I), "s3_csv", "AWS S3 mention"),
    # stripe
    (re.compile(r"\bstripe\b", re.I), "stripe", "Stripe mention"),
    (re.compile(r"\bexport\s+from\s+stripe", re.I),
     "stripe", "Stripe export mention"),
    # salesforce
    (re.compile(r"\bsalesforce\b|\bsfdc\b", re.I),
     "salesforce", "Salesforce mention"),
    # hubspot
    (re.compile(r"\bhubspot\b", re.I), "hubspot", "HubSpot mention"),
    (re.compile(r"\bhubspot\s+(crm|database)", re.I),
     "hubspot", "HubSpot CRM mention"),
    # http_csv
    (re.compile(r"\b(public|hosted)\s+csv\s+(url|endpoint)", re.I),
     "http_csv", "HTTP CSV mention"),
    # MCP presets
    (re.compile(r"\bnotion\b", re.I), "mcp:notion", "Notion mention"),
    (re.compile(r"\blinear\b(?!\s+regression)", re.I),
     "linear", "Linear mention"),
    (re.compile(r"\b(github|gitlab)\b", re.I),
     "mcp:notion", "code-source mention (placeholder MCP)"),
    # Generic source-mention phrasings
    (re.compile(r"\bour\s+(\w+)\s+(crm|database|warehouse|lake)\b", re.I),
     "csv_local", "generic source phrasing (fallback)"),
    (re.compile(r"\bload\s+(from|the)\s+(\w+)\s+(into|to)\b", re.I),
     "csv_local", "load-from-X phrasing (fallback)"),
    (re.compile(r"\bsync\s+(\w+)\s+(to|into)\b", re.I),
     "csv_local", "sync-X phrasing (fallback)"),
]


# Default classification policy: skip mention-scanning rows whose
# governance classification is PII or regulated. Sources mentioned in
# those rows are still candidates conceptually, but the regex bank
# wasn't designed for PII-safe extraction and the policy reflects
# "honest don't-leak" posture. Override via constructor knob.
_DEFAULT_SCAN_SKIP_CLASSIFICATIONS: frozenset[str] = frozenset({"pii", "regulated"})


class ChannelMentionAcquisitionStrategy:
    """Channel-mention source proposal: regex-scan silver conversations.

    Reads
    :class:`SilverConversationReader.list_recent_conversations` to
    enumerate recent silver-conversation rows. For each row whose
    classification is NOT in the skip-set (default: ``pii`` /
    ``regulated``):

      * Runs the regex pattern bank (~30 patterns covering top
        connectors + MCP presets + generic source phrasings) against
        the message ``text``.
      * For each match: emits one proposal with the matched connector
        kind at ``base_confidence`` (default 0.55; per spec §4.3 the
        floor is 0.50, ceiling 0.75). Higher-confidence direct vendor
        mentions (``"snowflake"``, ``"stripe"``) score above the floor;
        generic phrasings stay at the floor.
      * Carries ``evidence.message_refs`` (a list of message_ids from
        the matched rows) so admin can navigate to the originating
        message. Also carries ``evidence.matched_pattern`` and
        ``evidence.matched_text_excerpt`` (first 200 chars) for
        provenance.
      * When multiple rows mention the same connector kind, the
        composite dedups by ``candidate_id`` (which is hash-of
        ``(kind, identifier, strategy)``) — the strategy emits one
        proposal per ``(kind, identifier)`` pair and accumulates
        message_refs across all matching rows.

    **Empty-upstream posture** (honest stub) — per Sub-wave A handoff
    concern #1: when the reader returns ``[]``, the strategy returns
    ``[]`` (no proposals). This is the explicit configured ·
    empty-upstream state per spec §4.3.

    name: str = ``"channel_mention"``
    """

    name: str = "channel_mention"

    DEFAULT_BASE_CONFIDENCE: float = 0.55
    DEFAULT_HIGH_CONFIDENCE: float = 0.75
    DEFAULT_LOOKBACK_SECONDS: int = 86400  # 24h
    # Vendor-token patterns where a direct match scores at HIGH;
    # everything else stays at BASE.
    _HIGH_CONFIDENCE_REASONING_PREFIXES: frozenset[str] = frozenset({
        "Snowflake mention",
        "Stripe mention",
        "Salesforce mention",
        "HubSpot mention",
        "Postgres mention",
        "BigQuery mention",
        "Notion mention",
        "Linear mention",
    })

    def __init__(
        self,
        *,
        silver_conversation_reader: SilverConversationReader,
        base_confidence: float = DEFAULT_BASE_CONFIDENCE,
        high_confidence: float = DEFAULT_HIGH_CONFIDENCE,
        lookback_seconds: int = DEFAULT_LOOKBACK_SECONDS,
        skip_classifications: frozenset[str] = _DEFAULT_SCAN_SKIP_CLASSIFICATIONS,
    ) -> None:
        # Required dependency — no None-defaults. ChannelMention is
        # meaningless without a reader.
        self.silver_conversation_reader = silver_conversation_reader
        self.base_confidence = base_confidence
        self.high_confidence = high_confidence
        self.lookback_seconds = lookback_seconds
        self.skip_classifications = skip_classifications

    async def propose(
        self,
        *,
        company_id: UUID,
    ) -> list[ProposedSourceCandidate]:
        """Scan recent silver conversations; emit one proposal per matched kind."""
        rows = await self.silver_conversation_reader.list_recent_conversations(
            company_id=company_id, since_seconds=self.lookback_seconds,
        )
        if not rows:
            # Honest empty-upstream posture per spec §4.3 + Sub-wave A
            # handoff concern #1. ChannelMention configured ·
            # empty-upstream today; productive once silver pipeline
            # lands signal.
            return []

        # Aggregate matches per (proposed_kind, proposed_identifier)
        # so multiple matches across rows on the same connector kind
        # fold into one proposal with accumulated message_refs.
        aggregates: dict[
            tuple[str, str],
            dict[str, Any],
        ] = {}
        for row in rows:
            classification = (row.classification or "").lower()
            if classification in self.skip_classifications:
                continue
            text = row.text or ""
            if not text:
                continue
            for pattern, kind, reasoning_excerpt in _CHANNEL_MENTION_PATTERN_BANK:
                match = pattern.search(text)
                if match is None:
                    continue
                # proposed_identifier is the matched connector kind
                # itself — channel mentions don't carry a concrete
                # vendor account id, so the identifier collapses to
                # the kind so multi-row mentions of (e.g.) Snowflake
                # collide on the same candidate_id (one proposal per
                # connector kind mentioned in the conversation
                # stream).
                key = (kind, kind)
                entry = aggregates.setdefault(key, {
                    "kind": kind,
                    "reasoning_excerpt": reasoning_excerpt,
                    "message_refs": [],
                    "channel_ids": set(),
                    "matched_patterns": set(),
                    "excerpts": [],
                    "domain_id_hint": row.domain_id,
                    "is_high_confidence": False,
                })
                entry["message_refs"].append(row.message_id)
                entry["channel_ids"].add(row.channel_id)
                entry["matched_patterns"].add(reasoning_excerpt)
                if reasoning_excerpt in self._HIGH_CONFIDENCE_REASONING_PREFIXES:
                    entry["is_high_confidence"] = True
                if len(entry["excerpts"]) < 3:
                    # Cap excerpts at 3 per proposal to bound evidence size.
                    excerpt = text[:200]
                    entry["excerpts"].append(excerpt)

        proposals: list[ProposedSourceCandidate] = []
        for (kind, identifier), entry in aggregates.items():
            confidence = (
                self.high_confidence if entry["is_high_confidence"]
                else self.base_confidence
            )
            patterns_str = ", ".join(sorted(entry["matched_patterns"]))
            reasoning = (
                f"channel-mention regex matched {kind!r} across "
                f"{len(entry['message_refs'])} message(s); patterns: "
                f"{patterns_str}; confidence={confidence:.2f}"
            )
            evidence: dict[str, Any] = {
                "message_refs": list(entry["message_refs"]),
                "channel_ids": sorted(entry["channel_ids"]),
                "matched_patterns": sorted(entry["matched_patterns"]),
                "excerpts": entry["excerpts"],
            }
            proposals.append(
                _build_candidate(
                    proposed_kind=kind,
                    proposed_identifier=identifier,
                    strategy=self.name,
                    confidence=confidence,
                    reasoning=reasoning,
                    evidence=evidence,
                    domain_id_hint=entry["domain_id_hint"],
                ),
            )
        return proposals


# ---------------------------------------------------------------------------
# Strategy 3 — ComplementaritySourceStrategy
# ---------------------------------------------------------------------------


# Portfolio-balance heuristic thresholds. Tunable via constructor.
_SALES_DOMAIN_TOKENS: frozenset[str] = frozenset({"sales", "revenue"})
_FINANCE_DOMAIN_TOKENS: frozenset[str] = frozenset({"finance", "ops", "operations"})
_FILE_SOURCE_KINDS: frozenset[str] = frozenset({"csv_local", "s3_csv", "http_csv"})
_MARKETING_SOURCE_KINDS: frozenset[str] = frozenset({"hubspot", "gsheets"})
_PRODUCT_USAGE_SOURCE_KINDS: frozenset[str] = frozenset({"postgres", "mcp:notion"})


class ComplementaritySourceStrategy:
    """Portfolio-gap source proposal from already-connected sources.

    Reads :class:`ConnectedSourceReader.list_connected_sources` to
    enumerate already-connected sources. Computes portfolio-gap
    heuristics per spec §4.3:

      * **Sales-heavy** — all connected sources have ``domain_id`` in
        the sales/revenue token set → propose a marketing source
        (``hubspot`` at 0.55 if no hubspot connected, else ``gsheets``
        at 0.50) with reasoning "no marketing source; sales-heavy
        portfolio".
      * **Finance-heavy** — all connected sources have ``domain_id``
        in the finance/ops token set → propose a product/usage source
        (``postgres`` at 0.55 if no postgres connected, else
        ``mcp:notion`` at 0.50) with reasoning "no product-usage
        source; finance-heavy portfolio".
      * **No file source** — tenant has ≥3 connected sources and NONE
        are in the file-source kind set (``csv_local`` / ``s3_csv`` /
        ``http_csv``) → propose ``csv_local`` at 0.45 with reasoning
        "ad-hoc file drops not configured".

    All three heuristics can fire independently in a single
    invocation; the strategy returns the union of proposals (the
    composite dedups by ``candidate_id`` if any happen to collide,
    which they generally won't because the (kind, identifier, strategy)
    triples differ).

    **Productive today** as soon as ≥1 source is connected. Returns
    ``[]`` when the company has no connected sources (zero portfolio
    to balance — honest stub).

    Empty connected-sources case is the only "honest stub" surface —
    the strategy has no upstream-NLP / sampler dependency and lights
    up as soon as the bare ``projection_sources`` projection has rows.

    name: str = ``"complementarity"``
    """

    name: str = "complementarity"

    SALES_HEAVY_MARKETING_CONFIDENCE: float = 0.55
    SALES_HEAVY_MARKETING_ALT_CONFIDENCE: float = 0.50
    FINANCE_HEAVY_PRODUCT_CONFIDENCE: float = 0.55
    FINANCE_HEAVY_PRODUCT_ALT_CONFIDENCE: float = 0.50
    NO_FILE_SOURCE_CONFIDENCE: float = 0.45
    NO_FILE_SOURCE_THRESHOLD: int = 3

    def __init__(
        self,
        *,
        connected_source_reader: ConnectedSourceReader,
    ) -> None:
        # Required dependency — no None-defaults. Complementarity is
        # meaningless without a reader.
        self.connected_source_reader = connected_source_reader

    async def propose(
        self,
        *,
        company_id: UUID,
    ) -> list[ProposedSourceCandidate]:
        """Compute portfolio-gap heuristics; emit one proposal per gap."""
        sources = await self.connected_source_reader.list_connected_sources(
            company_id=company_id,
        )
        if not sources:
            # Honest stub posture — no portfolio to balance.
            return []

        kinds_present: set[str] = {s.kind for s in sources}
        domains_present: set[str] = {
            (s.domain_id or "").lower() for s in sources if s.domain_id
        }
        # Static snapshot for evidence — small, capped at the source
        # count, used by admin for context on why this gap was inferred.
        portfolio_snapshot: list[dict[str, str | None]] = [
            {"source_id": s.source_id, "kind": s.kind, "domain_id": s.domain_id}
            for s in sources
        ]

        proposals: list[ProposedSourceCandidate] = []

        # --- Sales-heavy → propose marketing source ---
        # Only fires when EVERY source's domain is in the sales/revenue
        # token set AND there's no marketing source already.
        sales_dom_hits = sum(
            1 for d in domains_present
            if any(tok in d for tok in _SALES_DOMAIN_TOKENS)
        )
        if (
            domains_present
            and sales_dom_hits == len(domains_present)
            and not (kinds_present & _MARKETING_SOURCE_KINDS)
        ):
            if "hubspot" not in kinds_present:
                primary_kind = "hubspot"
                confidence = self.SALES_HEAVY_MARKETING_CONFIDENCE
            else:
                primary_kind = "gsheets"
                confidence = self.SALES_HEAVY_MARKETING_ALT_CONFIDENCE
            proposals.append(_build_candidate(
                proposed_kind=primary_kind,
                proposed_identifier="portfolio:marketing-gap",
                strategy=self.name,
                confidence=confidence,
                reasoning=(
                    f"no marketing source; sales-heavy portfolio "
                    f"({len(sources)} connected, all in sales/revenue "
                    f"domain); propose {primary_kind} at {confidence:.2f}"
                ),
                evidence={
                    "heuristic": "sales_heavy_marketing_gap",
                    "portfolio_snapshot": portfolio_snapshot,
                    "missing_kind_set": sorted(
                        _MARKETING_SOURCE_KINDS - kinds_present,
                    ),
                },
            ))

        # --- Finance-heavy → propose product/usage source ---
        finance_dom_hits = sum(
            1 for d in domains_present
            if any(tok in d for tok in _FINANCE_DOMAIN_TOKENS)
        )
        if (
            domains_present
            and finance_dom_hits == len(domains_present)
            and not (kinds_present & _PRODUCT_USAGE_SOURCE_KINDS)
        ):
            if "postgres" not in kinds_present:
                primary_kind = "postgres"
                confidence = self.FINANCE_HEAVY_PRODUCT_CONFIDENCE
            else:
                primary_kind = "mcp:notion"
                confidence = self.FINANCE_HEAVY_PRODUCT_ALT_CONFIDENCE
            proposals.append(_build_candidate(
                proposed_kind=primary_kind,
                proposed_identifier="portfolio:product-gap",
                strategy=self.name,
                confidence=confidence,
                reasoning=(
                    f"no product-usage source; finance-heavy portfolio "
                    f"({len(sources)} connected, all in finance/ops "
                    f"domain); propose {primary_kind} at {confidence:.2f}"
                ),
                evidence={
                    "heuristic": "finance_heavy_product_gap",
                    "portfolio_snapshot": portfolio_snapshot,
                    "missing_kind_set": sorted(
                        _PRODUCT_USAGE_SOURCE_KINDS - kinds_present,
                    ),
                },
            ))

        # --- No file source AND ≥3 connected → propose csv_local ---
        if (
            len(sources) >= self.NO_FILE_SOURCE_THRESHOLD
            and not (kinds_present & _FILE_SOURCE_KINDS)
        ):
            proposals.append(_build_candidate(
                proposed_kind="csv_local",
                proposed_identifier="portfolio:file-drop-gap",
                strategy=self.name,
                confidence=self.NO_FILE_SOURCE_CONFIDENCE,
                reasoning=(
                    f"ad-hoc file drops not configured "
                    f"({len(sources)} connected, none in file-source "
                    f"kind set); propose csv_local at "
                    f"{self.NO_FILE_SOURCE_CONFIDENCE:.2f}"
                ),
                evidence={
                    "heuristic": "no_file_source_gap",
                    "portfolio_snapshot": portfolio_snapshot,
                    "missing_kind_set": sorted(_FILE_SOURCE_KINDS),
                },
            ))

        return proposals


# Static check: each strategy implements the Protocol.
_proto_check: tuple[type[SourceCandidateStrategy], ...] = (
    ChannelMentionAcquisitionStrategy,
    ComplementaritySourceStrategy,
    KpiGapAcquisitionStrategy,
)
del _proto_check
