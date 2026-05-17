"""Block G — :class:`DecisionLLMClient`.

Adapter that satisfies the ``LLMClient`` Protocol declared in
``wormbase_process_extractor.decisions``:

    async def affirm_decision(
        self, *, text: str, evidence_message_ids: list[str]
    ) -> float | None: ...

The adapter routes the ask through a :class:`Router` instance; the
router decides cache-vs-Kimi-vs-Gemma per its policy. The Reactivity
that calls ``affirm_decision`` therefore inherits the full router
behaviour (fallback, cache, ledger trace) without knowing anything
about it.

Confidence parsing
------------------

The response prompt asks the LLM to reply with a single number in the
range ``[0.0, 1.0]`` (or the literal token ``REJECT``). Anything else
parses to ``None``. The parsing is intentionally narrow — the
Reactivity that decides whether to emit a decision-record needs a
trustworthy signal, not a free-form analysis.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from wormbase_inference.protocol import RouteRequest, Router

logger = logging.getLogger(__name__)


_AFFIRM_SYSTEM = """You are WormBase's decision affirmation oracle.

You will be shown a candidate decision clause extracted from a chat message.
Reply with EXACTLY ONE of the following:

  * a single floating-point number between 0.0 and 1.0 (no prose), where
    1.0 means "yes, this is clearly a decision being recorded by humans"
    and 0.0 means "no, this is idle chatter that the regex over-matched."
  * the literal token REJECT (uppercase, alone) when the clause is plainly
    not a decision.

No other output is permitted. No prose, no JSON, no markdown.
"""

_NUMBER_RE = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*$")


@dataclass
class DecisionLLMClient:
    """Routes ``affirm_decision`` calls through a :class:`Router`.

    Construct with a router; pass into the process-worm Reactivity
    factory as the optional ``llm`` argument. Implements the
    ``LLMClient`` Protocol from
    ``wormbase_process_extractor.decisions``.
    """

    router: Router
    requested_by: str = "process-extractor.affirm_decision"

    async def affirm_decision(
        self,
        *,
        text: str,
        evidence_message_ids: list[str],
    ) -> float | None:
        evidence_block = (
            f"Evidence message ids: {', '.join(evidence_message_ids)}"
            if evidence_message_ids
            else "Evidence message ids: (none)"
        )
        user = f"Candidate decision clause:\n---\n{text}\n---\n{evidence_block}"

        request = RouteRequest(
            call_type="affirm",
            messages=(("user", user),),
            system=_AFFIRM_SYSTEM,
            backend_hint="auto",  # routes to Kimi by default
            temperature=0.0,
            requested_by=self.requested_by,
            extra=(("evidence_count", str(len(evidence_message_ids))),),
        )
        try:
            response = await self.router.call(request)
        except Exception as exc:  # noqa: BLE001
            # Affirmation is best-effort — the Reactivity falls back to
            # the heuristic-only confidence on None.
            logger.warning(
                "inference-router: affirm_decision call failed: %s", exc
            )
            return None

        return _parse_affirm_response(response.text)


def _parse_affirm_response(raw: str) -> float | None:
    """Return a float in ``[0,1]`` or ``None``.

    Strict parser — anything outside the documented contract returns
    ``None`` so the Reactivity falls back to its heuristic confidence.
    """
    if not raw:
        return None
    stripped = raw.strip()
    if stripped.upper() == "REJECT":
        return None
    m = _NUMBER_RE.match(stripped)
    if m is None:
        return None
    try:
        v = float(m.group(1))
    except ValueError:
        return None
    if v < 0.0 or v > 1.0:
        return None
    return v


__all__ = [
    "DecisionLLMClient",
]
