"""Inline governance gates that fire on every MCP tool call.

Per Wave 2 Task 7 Step 2. The 4 gates form a composable chain wrapped
around each MCP tool's backend work. Chain order is canonical:

    1. AgentAccessGate     — agent has the right ``agent_grant`` for the op?
    2. ClassificationGate  — resource classification within the agent's ceiling?
    3. PIIRedactionGate    — scan ``args`` for PII; redact in the audit row
    4. CostGate            — agent has model-budget remaining?

Each gate returns ``None`` on pass, or a :class:`GateDenial` carrying
``reason``, ``gate_name`` and an optional ``suggested_fix``.

On any denial, the calling MCP tool emits ``agent_query`` with
``status="denied"`` in the resolve phase and short-circuits before
backend execution.

v1.1 unification (Hole #7)
--------------------------
The four inline gates above are minimal, agent-gateway-scoped, and pure
functions. ``wormbase-governance`` also ships four heavier *stateful*
gates (``PIIGate`` / ``WarmupGate`` / ``InterjectionGate`` /
``KnowledgeGate``) that emit their own ``gate_fired`` ledger entries
when they fire. Pre-unification those only ran in the chat-presence
wire — external agent MCP calls got no observation from them.

v1.1 Task 5 unifies the two surfaces by composing the stateful gates
AFTER the inline gates inside :func:`apply_gates`. Order is canonical:

    inline gates (Wave 2: fast, pure, no ledger writes)
        ↓ if any denied, short-circuit — saves the stateful ledger writes
    stateful gates (packages/governance/: emit gate_fired on fire)
        ↓
    proceed

The stateful segment is *optional* — wire it only when the install has
a configured ledger + company_id + ontology loader. When the
``stateful`` field on :class:`GateChain` is None (the default), the
behaviour matches Wave 2 exactly. This keeps existing tests + the
chat-presence path byte-identical: chat-presence constructs the
stateful gates independently from worm-core.service, not via this
chain, so its wire is unchanged.

PII concern overlap
~~~~~~~~~~~~~~~~~~~
The inline ``PIIRedactionGate`` redacts args for the audit row (pure,
no ledger writes). The stateful ``PIIGate`` runs on the same args, but
its job is to *record* the match as a ``gate_fired`` ledger entry —
the inline gate is the redaction-renderer, the stateful gate is the
audit-trail emitter. They are not redundant; they have non-overlapping
side-effects.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Awaitable, Callable, Iterable, Sequence

from wormbase_inference import AgentID, GovernanceContext

from .identity import AgentGrant


# ---------------------------------------------------------------------------
# Denial value type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateDenial:
    """Single gate's denial — never raised; returned + propagated.

    ``gate_name`` is the canonical short name (``agent_access`` /
    ``classification`` / ``pii_redaction`` / ``cost``). ``reason`` is
    a human-readable summary used both in the audit row and in the
    MCP tool's structured response. ``suggested_fix`` is an optional
    hint (e.g. "ask admin for resource.read on resource_id=...") the
    caller can surface to the agent.
    """

    reason: str
    gate_name: str
    suggested_fix: str | None = None


# ---------------------------------------------------------------------------
# Classification ordering (matches wormbase_governance.entities.Classification)
# ---------------------------------------------------------------------------


_CLASSIFICATION_RANK: dict[str, int] = {
    "public": 0,
    "internal": 1,
    "confidential": 2,
    "pii": 3,
    "regulated": 4,
}


def _rank(c: str | None) -> int:
    """Return classification rank; treat unknown / None as ``internal``.

    Internal is the soft-default everywhere else in the codebase — see
    ``wormbase_inference.GovernanceContext.classification_ceiling``.
    """
    if c is None:
        return _CLASSIFICATION_RANK["internal"]
    return _CLASSIFICATION_RANK.get(c, _CLASSIFICATION_RANK["internal"])


# ---------------------------------------------------------------------------
# Gate 1: AgentAccessGate
# ---------------------------------------------------------------------------


# MCP tool name -> list of acceptable grant-kind/-target patterns.
# A grant matches when its ``grant_kind`` is in the accepted list AND
# (when ``required_target`` is provided) its ``grant_target`` matches.
# For v1 we allow ANY active grant of the listed kind to satisfy access;
# fine-grained target-matching (e.g. resource_id in the request) is
# checked by the classification gate next.
_TOOL_GRANT_KINDS: dict[str, tuple[str, ...]] = {
    "lake.catalog.tables":        ("domain.read", "resource.read"),
    "lake.semantic.metric":       ("domain.read", "resource.read"),
    "lake.lineage":               ("domain.read", "resource.read"),
    "lake.query":                 ("domain.read", "resource.read"),
    "lake.semantic.search":       ("domain.read", "resource.read"),
    "lake.semantic.query_spec":   ("domain.read", "resource.read"),
    "lake.query.suggest_correction": ("domain.read", "resource.read"),
    "lake.query.record_outcome":  ("domain.read", "resource.read"),
    "lake.semantic.gap":          ("domain.read", "resource.read"),
    # Wave 3.2 Hole #3 — gold-artifact MCP tools. Decisions / processes /
    # data products are read with the same domain.read grant kind as the
    # data-plane tools; resource.read is also accepted so per-artifact
    # grants compose. The write tool (data_products.consume) is gated
    # identically because consumption is observation-shaped (records who
    # read what), not a state mutation requiring elevated trust.
    "decisions.list":             ("domain.read", "resource.read"),
    "decisions.get":              ("domain.read", "resource.read"),
    "decisions.search":           ("domain.read", "resource.read"),
    "processes.list":             ("domain.read", "resource.read"),
    "processes.get":              ("domain.read", "resource.read"),
    "data_products.list":         ("domain.read", "resource.read"),
    "data_products.get":          ("domain.read", "resource.read"),
    "data_products.consume":      ("domain.read", "resource.read"),
}


class AgentAccessGate:
    """Allow if the agent holds an active grant covering the tool's data needs.

    v1 policy: any active ``domain.read`` OR ``resource.read`` grant
    satisfies access for the data-plane tools. ``model.access`` is
    checked by the CostGate. ``resource.maintainer`` implicitly grants
    read (maintainers are super-readers).
    """

    name = "agent_access"

    def __init__(self, *, grant_lookup: Callable[[AgentID], Awaitable[Sequence[AgentGrant]]]) -> None:
        self._lookup = grant_lookup

    async def check(
        self,
        *,
        agent_id: AgentID,
        mcp_tool: str,
        args: dict[str, Any],
    ) -> GateDenial | None:
        accepted = _TOOL_GRANT_KINDS.get(mcp_tool)
        if accepted is None:
            # Unknown tool — fail closed.
            return GateDenial(
                reason=f"unknown mcp_tool {mcp_tool!r}; no grant policy",
                gate_name=self.name,
                suggested_fix=None,
            )
        grants = list(await self._lookup(agent_id))
        accepted_set = set(accepted) | {"resource.maintainer"}
        for g in grants:
            if g.status != "active":
                continue
            if g.grant_kind in accepted_set:
                return None
        return GateDenial(
            reason=(
                f"agent {agent_id.value!r} lacks an active grant in "
                f"{sorted(accepted_set)} for tool {mcp_tool!r}"
            ),
            gate_name=self.name,
            suggested_fix=(
                "ask an admin to assign domain.read or resource.read"
            ),
        )


# ---------------------------------------------------------------------------
# Gate 2: ClassificationGate
# ---------------------------------------------------------------------------


class ClassificationGate:
    """Block when the requested resource's classification exceeds the agent's ceiling.

    The ceiling comes from :class:`GovernanceContext.classification_ceiling`.
    The resource classification is resolved via ``resource_classification``
    callback — caller supplies the lookup (catalog projection in v1; v1.1
    folds it in directly).
    """

    name = "classification"

    def __init__(
        self,
        *,
        resource_classification: Callable[[str], Awaitable[str | None]] | None = None,
    ) -> None:
        self._lookup = resource_classification

    async def check(
        self,
        *,
        agent_id: AgentID,
        mcp_tool: str,
        args: dict[str, Any],
        governance: GovernanceContext,
    ) -> GateDenial | None:
        ceiling_rank = _rank(governance.classification_ceiling)
        # Pull the candidate resource id from the args dict. Different
        # tools key it differently:
        #     lake.catalog.tables    no resource_id
        #     lake.semantic.metric   args.name -> metric name (no resource ID)
        #     lake.lineage           args.resource_id
        #     lake.query             args.scope_token has scope.resource_id
        candidate = (
            args.get("resource_id")
            or args.get("source_id")
            or (args.get("filter") or {}).get("resource_id")
        )
        if not candidate or self._lookup is None:
            return None
        classification = await self._lookup(candidate)
        if classification is None:
            return None
        cand_rank = _rank(classification)
        if cand_rank > ceiling_rank:
            return GateDenial(
                reason=(
                    f"resource classification {classification!r} exceeds agent "
                    f"ceiling {governance.classification_ceiling!r}"
                ),
                gate_name=self.name,
                suggested_fix=(
                    "raise the agent's classification_ceiling grant, or "
                    "query a lower-classification view"
                ),
            )
        return None


# ---------------------------------------------------------------------------
# Gate 3: PIIRedactionGate
# ---------------------------------------------------------------------------


# Minimal regex set — agent_args PII patterns. The heavy
# wormbase_governance.PIIGate uses an ontology-driven pattern set + Luhn
# validation; we deliberately keep this thin to avoid loading the seed
# loader for every MCP call. Wave 3+ unifies the two surfaces.
import re as _re

_PII_PATTERNS: tuple[tuple[str, "_re.Pattern[str]"], ...] = (
    ("email",       _re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("ssn",         _re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("phone",       _re.compile(r"\b\+?1?[ -]?\(?\d{3}\)?[ -]?\d{3}[ -]?\d{4}\b")),
    ("credit_card", _re.compile(r"\b(?:\d[ -]?){13,19}\b")),
)


def _redact_value(v: Any) -> tuple[Any, list[str]]:
    """Recursively scan ``v`` for PII patterns; return (redacted, matched_ids).

    Strings are scanned + substituted. Lists / dicts are walked. Other
    scalars pass through unchanged.
    """
    if isinstance(v, str):
        matched: list[str] = []
        result = v
        for pid, pat in _PII_PATTERNS:
            if pat.search(result):
                result = pat.sub(f"[REDACTED:{pid}]", result)
                matched.append(pid)
        return result, matched
    if isinstance(v, list):
        new_list: list[Any] = []
        all_matched: list[str] = []
        for item in v:
            r, m = _redact_value(item)
            new_list.append(r)
            all_matched.extend(m)
        return new_list, all_matched
    if isinstance(v, dict):
        new_d: dict[str, Any] = {}
        all_matched = []
        for k, item in v.items():
            r, m = _redact_value(item)
            new_d[k] = r
            all_matched.extend(m)
        return new_d, all_matched
    return v, []


class PIIRedactionGate:
    """Scan args for PII patterns; redact for audit; never block on PII alone.

    v1 policy: PII presence does NOT deny the call — it redacts the
    ``args`` dict passed to the audit row. Returning ``None`` therefore
    is the contract even when PII is present; the redacted args are
    surfaced via :meth:`redact_args` (called separately by the tool
    wrapper). The gate's structural ``check`` signature stays uniform
    with the other three so :func:`apply_gates` composes the chain
    without special-casing.

    A future Wave can flip ``deny_on_match`` to ``True`` to refuse
    calls when args contain regulated PII; v1 keeps the call open so
    the agent's question is preserved in the ledger (redacted).
    """

    name = "pii_redaction"

    async def check(
        self,
        *,
        agent_id: AgentID,
        mcp_tool: str,
        args: dict[str, Any],
    ) -> GateDenial | None:
        # v1: never denies. Caller invokes redact_args() separately.
        return None

    def redact_args(self, args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        """Return (redacted_args, matched_pattern_ids).

        ``matched_pattern_ids`` is a deduped list of pattern ids that
        fired across the entire args tree.
        """
        redacted, matched = _redact_value(args)
        # _redact_value always returns dict for dict input
        assert isinstance(redacted, dict)
        return redacted, sorted(set(matched))


# ---------------------------------------------------------------------------
# Gate 4: CostGate
# ---------------------------------------------------------------------------


class CostGate:
    """Block when the agent's model-access grant is out of budget.

    Reads the ``model.access`` grant's ``budget_remaining_usd`` from the
    grant lookup. If the agent has no model.access grant at all, the
    gate passes (model spend is observed via the inference-router's
    own gates; the agent-gateway only enforces the existence of a
    grant when one is required).

    v1 deny rule: ``budget_remaining_usd <= 0``. Wave 3+ adds
    soft-warnings under threshold + hard-deny at zero.
    """

    name = "cost"

    def __init__(self, *, grant_lookup: Callable[[AgentID], Awaitable[Sequence[AgentGrant]]]) -> None:
        self._lookup = grant_lookup

    async def check(
        self,
        *,
        agent_id: AgentID,
        mcp_tool: str,
        args: dict[str, Any],
    ) -> GateDenial | None:
        grants = list(await self._lookup(agent_id))
        model_grants = [
            g for g in grants
            if g.grant_kind == "model.access" and g.status == "active"
        ]
        if not model_grants:
            # No model.access grant — let downstream handle it.
            return None
        for g in model_grants:
            remaining = g.budget_remaining_usd
            if remaining is None:
                continue
            if remaining <= Decimal("0"):
                return GateDenial(
                    reason=(
                        f"agent model budget exhausted: "
                        f"target={g.grant_target} remaining={remaining}"
                    ),
                    gate_name=self.name,
                    suggested_fix=(
                        "ask an admin to top up the agent's model.access "
                        "budget_remaining_usd"
                    ),
                )
        return None


# ---------------------------------------------------------------------------
# Stateful gate adapters (v1.1 Hole #7 — governance unification)
# ---------------------------------------------------------------------------
#
# The 4 stateful gates in ``wormbase_governance`` have heterogeneous APIs
# tailored to their original chat-presence call sites:
#
#   PIIGate.check(text: str, context: dict | None) -> PIIGateResult
#   WarmupGate.check(action_type: Literal["passive","active"], cid) -> _GateDecisionLite
#   InterjectionGate.allow(channel_id: str, question_type: str) -> bool
#   KnowledgeGate.check(query_concepts: list[str]) -> _GateDecisionLite
#
# To compose these into ``apply_gates`` we wrap each one in a thin
# adapter that:
#
#   1. Maps the uniform ``(agent_id, mcp_tool, args, governance)`` MCP
#      surface to the underlying gate's expected inputs.
#   2. Returns a :class:`GateDenial` on block, ``None`` on pass — so
#      ``apply_gates`` can short-circuit the chain uniformly.
#   3. Lets the underlying stateful gate emit its own ``gate_fired``
#      ledger entry as a side effect (we never re-emit).
#
# Adapters live here, not in ``wormbase_governance``, because the
# argument-extraction logic is MCP-call-shaped — chat-presence calls
# the gates with channel-shaped arguments and would not benefit from
# the args-tree text walking we do here.
# ---------------------------------------------------------------------------


def _walk_strings(value: Any) -> Iterable[str]:
    """Yield every string contained anywhere in ``value`` (recursive)."""
    if isinstance(value, str):
        if value:
            yield value
        return
    if isinstance(value, dict):
        for v in value.values():
            yield from _walk_strings(v)
        return
    if isinstance(value, (list, tuple)):
        for v in value:
            yield from _walk_strings(v)
        return


class StatefulPIIGateAdapter:
    """Run ``wormbase_governance.PIIGate.check`` over the args' text content.

    The underlying gate emits a ``gate_fired`` ledger entry when its
    pattern set matches; we do not emit anything ourselves. PII presence
    never denies the call (consistent with the inline
    :class:`PIIRedactionGate`); the gate's value-add is the audit-trail
    write, not the deny decision.
    """

    name = "pii_stateful"

    def __init__(self, *, pii_gate: Any) -> None:
        self._pii_gate = pii_gate

    async def check(
        self,
        *,
        agent_id: AgentID,
        mcp_tool: str,
        args: dict[str, Any],
    ) -> GateDenial | None:
        # Concatenate string args into one scan target. We don't care
        # which key the PII came from for the gate's audit purpose;
        # the entry records "an MCP call from agent X to tool Y matched
        # N PII patterns". The inline PIIRedactionGate's redact_args
        # is what actually scrubs the audit row.
        chunks = [s for s in _walk_strings(args)]
        if not chunks:
            return None
        text = "\n".join(chunks)
        context = {
            "source": f"mcp:{mcp_tool}",
            "agent_id": agent_id.value,
        }
        await self._pii_gate.check(text, context)
        # Never deny on PII alone — args are redacted in the audit row.
        return None


class StatefulWarmupGateAdapter:
    """Run ``wormbase_governance.WarmupGate.check`` for MCP-call semantics.

    External-agent MCP tool calls are read-shaped (data plane) — the
    worm is *observing*, not *acting* from its own initiative. The
    underlying gate treats ``passive`` as always-allowed, which matches
    the MCP semantics exactly. We still call ``check`` so any future
    flip of that policy (e.g. cold-start lockout on regulated data) is
    a one-line change in :class:`WarmupGate` rather than here.
    """

    name = "warmup_stateful"

    def __init__(self, *, warmup_gate: Any) -> None:
        self._warmup_gate = warmup_gate

    async def check(
        self,
        *,
        agent_id: AgentID,
        mcp_tool: str,
        args: dict[str, Any],
    ) -> GateDenial | None:
        decision = await self._warmup_gate.check("passive")
        if getattr(decision, "allow", True):
            return None
        return GateDenial(
            reason=f"warmup gate denied: {getattr(decision, 'reason', 'unknown')}",
            gate_name=self.name,
            suggested_fix=(
                "wait for the worm's schema-axis ramp to cross threshold, "
                "then retry"
            ),
        )


class StatefulInterjectionGateAdapter:
    """Adapter for ``wormbase_governance.InterjectionGate``.

    MCP tool calls do NOT post clarifying questions back into channels
    (that's the chat-presence wire's job). The interjection budget is
    therefore N/A for normal data-plane MCP traffic. We retain the
    adapter so the chain composition is uniform and so a future
    "agent-asks-clarification-via-MCP" tool family (none today) plugs
    in without changing :func:`apply_gates`.

    The adapter is configured with an optional ``mcp_tool`` allowlist
    of clarify-shaped tools. The default empty allowlist means the
    adapter is a no-op for every tool name — InterjectionGate is never
    invoked from the MCP path. Chat-presence's existing direct usage
    is unaffected.
    """

    name = "interjection_stateful"

    def __init__(
        self,
        *,
        interjection_gate: Any,
        clarify_tools: Sequence[str] = (),
    ) -> None:
        self._gate = interjection_gate
        self._clarify_tools = frozenset(clarify_tools)

    async def check(
        self,
        *,
        agent_id: AgentID,
        mcp_tool: str,
        args: dict[str, Any],
    ) -> GateDenial | None:
        if mcp_tool not in self._clarify_tools:
            return None
        channel_id = args.get("channel_id") or args.get("source_id") or ""
        if not channel_id:
            return None
        allowed = await self._gate.allow(channel_id, "clarification")
        if allowed:
            return None
        return GateDenial(
            reason=(
                f"interjection budget exhausted for channel {channel_id!r}"
            ),
            gate_name=self.name,
            suggested_fix=(
                "wait for the daily window to roll over, or raise the "
                "channel's daily_interjection_budget"
            ),
        )


class StatefulKnowledgeGateAdapter:
    """Adapter for ``wormbase_governance.KnowledgeGate``.

    The underlying gate refuses to answer when query concepts are
    not in the worm's ontology + confirmed concept set. We extract
    candidate concepts from the args' string content via the optional
    ``concept_extractor`` callable. When the extractor returns an empty
    list (or no extractor is configured), the gate trivially allows —
    matching the underlying gate's "no_concepts_referenced" branch.

    Production callers wire an extractor that uses the worm's NLU
    pipeline. Tests can supply a literal-keyword extractor.
    """

    name = "knowledge_stateful"

    def __init__(
        self,
        *,
        knowledge_gate: Any,
        concept_extractor: Callable[[dict[str, Any]], Sequence[str]] | None = None,
    ) -> None:
        self._gate = knowledge_gate
        self._extract = concept_extractor

    async def check(
        self,
        *,
        agent_id: AgentID,
        mcp_tool: str,
        args: dict[str, Any],
    ) -> GateDenial | None:
        if self._extract is None:
            return None
        concepts = list(self._extract(args))
        if not concepts:
            return None
        decision = await self._gate.check(concepts)
        if getattr(decision, "allow", True):
            return None
        meta = getattr(decision, "metadata", {}) or {}
        missing = meta.get("missing") or []
        return GateDenial(
            reason=f"knowledge gap: missing {missing}",
            gate_name=self.name,
            suggested_fix=getattr(decision, "suggested_action", None),
        )


@dataclass(frozen=True)
class StatefulGateBundle:
    """The four stateful adapters bundled together for one chain.

    Each adapter wraps a concrete ``wormbase_governance`` gate
    instance — the same gates chat-presence + worm-core construct at
    boot. When the agent-gateway shares an install with worm-core
    (the production deployment), the same gate instances can be
    handed to both surfaces so their ledger writes are
    deduplicated-by-context (the gate's own propose dedup window).
    """

    pii: StatefulPIIGateAdapter
    warmup: StatefulWarmupGateAdapter
    interjection: StatefulInterjectionGateAdapter
    knowledge: StatefulKnowledgeGateAdapter


def make_stateful_gate_bundle(
    *,
    pii_gate: Any,
    warmup_gate: Any,
    interjection_gate: Any,
    knowledge_gate: Any,
    clarify_tools: Sequence[str] = (),
    concept_extractor: Callable[[dict[str, Any]], Sequence[str]] | None = None,
) -> StatefulGateBundle:
    """Factory — wraps the 4 ``wormbase_governance`` gates in MCP adapters.

    Pass instances of ``wormbase_governance.PIIGate`` /
    ``WarmupGate`` / ``InterjectionGate`` / ``KnowledgeGate``. The
    bundle is then handed to :func:`make_default_gate_chain` as the
    ``stateful`` argument.
    """
    return StatefulGateBundle(
        pii=StatefulPIIGateAdapter(pii_gate=pii_gate),
        warmup=StatefulWarmupGateAdapter(warmup_gate=warmup_gate),
        interjection=StatefulInterjectionGateAdapter(
            interjection_gate=interjection_gate,
            clarify_tools=clarify_tools,
        ),
        knowledge=StatefulKnowledgeGateAdapter(
            knowledge_gate=knowledge_gate,
            concept_extractor=concept_extractor,
        ),
    )


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateChain:
    """Canonical 4-inline-gate chain (+ optional 4-stateful bundle).

    The agent-gateway constructs this at boot time with the right
    grant lookup + classification lookup callbacks. ``apply_gates``
    runs the chain in order and short-circuits on the first denial.

    When ``stateful`` is not ``None``, the four ``wormbase_governance``
    adapters run after the four inline gates — they emit
    ``gate_fired`` ledger entries when they fire, giving the MCP path
    the same observability the chat-presence wire has had since Wave
    1. When ``stateful`` is ``None`` (the default), the chain behaves
    exactly as in Wave 2 — useful for unit tests and for installs
    that have not yet wired the stateful gates.
    """

    agent_access: AgentAccessGate
    classification: ClassificationGate
    pii_redaction: PIIRedactionGate
    cost: CostGate
    stateful: StatefulGateBundle | None = None


def make_default_gate_chain(
    *,
    grant_lookup: Callable[[AgentID], Awaitable[Sequence[AgentGrant]]],
    resource_classification: Callable[[str], Awaitable[str | None]] | None = None,
    stateful: StatefulGateBundle | None = None,
) -> GateChain:
    """Factory — constructs the canonical gate chain.

    Use this from the FastMCP server's `build_*` site. Pass the
    relevant projection-reader as the grant_lookup; for tests, pass
    an in-memory list / dict-backed callable.

    Pass ``stateful`` (from :func:`make_stateful_gate_bundle`) to
    unify with the heavier ``wormbase_governance`` gates. Default
    None preserves Wave 2 behaviour byte-for-byte.
    """
    return GateChain(
        agent_access=AgentAccessGate(grant_lookup=grant_lookup),
        classification=ClassificationGate(resource_classification=resource_classification),
        pii_redaction=PIIRedactionGate(),
        cost=CostGate(grant_lookup=grant_lookup),
        stateful=stateful,
    )


async def apply_gates(
    chain: GateChain,
    *,
    agent_id: AgentID,
    mcp_tool: str,
    args: dict[str, Any],
    governance: GovernanceContext | None = None,
) -> GateDenial | None:
    """Run the gate chain in canonical order; return the first denial.

    Returns ``None`` when every gate passes; otherwise the
    :class:`GateDenial` from the FIRST failing gate. Subsequent gates
    are not invoked once a denial is observed.

    Order::

        1. inline AgentAccessGate
        2. inline ClassificationGate
        3. inline PIIRedactionGate    (never denies; redacts args separately)
        4. inline CostGate
        5. stateful PII (emits gate_fired on PII match; never denies)
        6. stateful Warmup (denies if schema-axis under threshold)
        7. stateful Interjection (denies if clarify-budget exhausted;
           default no-op for data-plane MCP tools)
        8. stateful Knowledge (denies if query references unknown
           concepts; default no-op when no extractor configured)

    Inline-gate denials short-circuit BEFORE any stateful gate runs —
    this is the cost-saving property: a missing access grant doesn't
    cause a wasted ``gate_fired`` ledger write.
    """
    ctx = governance or GovernanceContext()
    denial = await chain.agent_access.check(
        agent_id=agent_id, mcp_tool=mcp_tool, args=args,
    )
    if denial is not None:
        return denial
    denial = await chain.classification.check(
        agent_id=agent_id, mcp_tool=mcp_tool, args=args, governance=ctx,
    )
    if denial is not None:
        return denial
    denial = await chain.pii_redaction.check(
        agent_id=agent_id, mcp_tool=mcp_tool, args=args,
    )
    if denial is not None:
        return denial
    denial = await chain.cost.check(
        agent_id=agent_id, mcp_tool=mcp_tool, args=args,
    )
    if denial is not None:
        return denial
    if chain.stateful is not None:
        # PII stateful — emit gate_fired on PII match but never deny.
        denial = await chain.stateful.pii.check(
            agent_id=agent_id, mcp_tool=mcp_tool, args=args,
        )
        if denial is not None:
            return denial
        denial = await chain.stateful.warmup.check(
            agent_id=agent_id, mcp_tool=mcp_tool, args=args,
        )
        if denial is not None:
            return denial
        denial = await chain.stateful.interjection.check(
            agent_id=agent_id, mcp_tool=mcp_tool, args=args,
        )
        if denial is not None:
            return denial
        denial = await chain.stateful.knowledge.check(
            agent_id=agent_id, mcp_tool=mcp_tool, args=args,
        )
        if denial is not None:
            return denial
    return None


__all__ = [
    "AgentAccessGate",
    "ClassificationGate",
    "CostGate",
    "GateChain",
    "GateDenial",
    "PIIRedactionGate",
    "StatefulGateBundle",
    "StatefulInterjectionGateAdapter",
    "StatefulKnowledgeGateAdapter",
    "StatefulPIIGateAdapter",
    "StatefulWarmupGateAdapter",
    "apply_gates",
    "make_default_gate_chain",
    "make_stateful_gate_bundle",
]
