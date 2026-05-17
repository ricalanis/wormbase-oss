"""Phase 2 Task 2B (Wave H) — :class:`TopicLabelerLLMClient`.

Adapter that satisfies the ``TopicLabeler`` Protocol declared in
``wormbase_process_extractor.reactivities``:

    async def label_topic(
        self,
        *,
        cluster_signature: str,
        sample_messages: list[str],
        member_message_ids: list[str],
    ) -> tuple[str, float, str] | None: ...

The adapter routes the ask through a :class:`Router` instance with
``call_type="summarize"`` so the router defaults to Gemma (high-volume
commodity work — see the routing table in protocol.py). The
Reactivity that calls ``label_topic`` therefore inherits the full
router behaviour (fallback, cache, ledger trace) without knowing
anything about the underlying inference backends.

Returns
-------

A ``(label, confidence, served_by)`` triple on success, or ``None``
when the router fails or returns an empty / REJECT reply. The
Reactivity's heuristic fallback handles ``None`` — there is no path
where a cluster-cross signal fails to reach the ledger.

Confidence is a router-blessed default (``0.82`` — comfortably above
the ``0.5`` heuristic floor and below ``1.0`` so the dashboard can
still surface "high confidence but not certain" rendering for cluster
labels). The adapter does not parse a confidence number out of the
reply because the summarize prompt produces prose, not numbers; the
router itself is the trust signal.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from wormbase_inference.protocol import RouteRequest, Router

logger = logging.getLogger(__name__)


_LABEL_SYSTEM = """You are WormBase's topic-cluster labeler.

You will be shown a normalized cluster signature plus 1-3 sample
messages from the cluster. Reply with EXACTLY ONE short topic label
(2-6 words, no surrounding quotes, no period at the end) that
describes what the cluster is about.

If the input is too thin to label, reply with the literal token REJECT.

No prose, no JSON, no markdown, no explanation — just the label or
REJECT.
"""

# Maximum characters preserved from the router's reply. Mirrors the
# ``TopicProposedPayload.label`` max_length so the adapter's output
# never trips the downstream payload validator.
_MAX_LABEL_LEN = 256

# Router-blessed confidence floor — comfortably above the heuristic
# 0.5 baseline, below 1.0 so the dashboard can still render an
# "uncertain" badge when the cluster is small.
_ROUTER_CONFIDENCE_DEFAULT: float = 0.82


@dataclass
class TopicLabelerLLMClient:
    """Routes ``label_topic`` calls through a :class:`Router`.

    Construct with a router; pass into the process-worm Reactivity
    factory as the ``topic_labeler`` argument or wire directly into
    ``ReactivityContext.extras["topic_labeler"]``. Implements the
    ``TopicLabeler`` Protocol from
    ``wormbase_process_extractor.reactivities``.
    """

    router: Router
    requested_by: str = "process-extractor.label_topic"
    confidence: float = _ROUTER_CONFIDENCE_DEFAULT

    async def label_topic(
        self,
        *,
        cluster_signature: str,
        sample_messages: list[str],
        member_message_ids: list[str],
    ) -> tuple[str, float, str] | None:
        sample_block = (
            "\n".join(f"  - {m}" for m in sample_messages[:3])
            if sample_messages
            else "  (no sample messages provided)"
        )
        user = (
            f"Cluster signature: {cluster_signature}\n"
            f"Sample messages:\n{sample_block}"
        )

        request = RouteRequest(
            call_type="summarize",
            messages=(("user", user),),
            system=_LABEL_SYSTEM,
            backend_hint="auto",  # routes to Gemma by default
            temperature=0.0,
            requested_by=self.requested_by,
            extra=(("member_count", str(len(member_message_ids))),),
        )
        try:
            response = await self.router.call(request)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "inference-router: label_topic call failed: %s", exc
            )
            return None

        label = _parse_label_response(response.text)
        if label is None:
            return None
        # served_by may be ``"cache"`` if the router resolved from cache;
        # mirror that as-is so the projection layer can attribute
        # provenance honestly.
        return (label, self.confidence, response.served_by)


def _parse_label_response(raw: str) -> str | None:
    """Normalize a router reply into a usable label, or ``None``.

    Empty / whitespace-only / REJECT replies → ``None`` so the
    Reactivity falls back to its heuristic label. Long replies are
    truncated to the payload max_length (256 chars) — the validator
    rejects anything longer.
    """
    if not raw:
        return None
    stripped = raw.strip()
    if not stripped:
        return None
    if stripped.upper() == "REJECT":
        return None
    if len(stripped) > _MAX_LABEL_LEN:
        return stripped[:_MAX_LABEL_LEN]
    return stripped


__all__ = [
    "TopicLabelerLLMClient",
]
