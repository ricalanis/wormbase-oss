"""Semantic classifier — chat-worm-private.

Provides StubClassifier, OllamaCloudClassifier, SemanticClassifier, and
the evaluate_on_seed_bank utility. Consumers in v1: chat-worm internal
only (DefaultSemanticTrigger upstream of the relevance gate, plus
DropAndProfileFlow's filename classification path).

This module is NOT re-exported from `wormbase_chat_presence.__init__`.
Callers reach it via `from wormbase_chat_presence.classifier import ...`
explicitly, signaling internal consumption. When a second worm gains a
classifier consumer (likely process-worm in Wave C₂), this module
migrates to packages/inference-router as a separate wave.

Lifted verbatim from apps/worm-core/src/wormbase_core/classifier.py
in Wave B (per D6 of the orchestration doc).

Two implementations:

* ``StubClassifier``: deterministic, regex-driven, used in tests + as a fast
  pre-filter so the worm doesn't pay for a model call on obvious matches
  (e.g. ``postgres://`` is unambiguously a credential offer).
* ``OllamaCloudClassifier``: calls Ollama Cloud's OpenAI-compatible chat
  endpoint with kimi-k2.6:cloud as default, returns parsed JSON. The stub
  is invoked first and only the residual cases hit the network.

The composite ``SemanticClassifier`` runs stub first, then falls through
to OllamaCloud only when the stub's confidence is below an upgrade
threshold. Designed so the seed-bank accuracy gate (≥80%) can be hit
deterministically using the stub alone (the tests rely on this).
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from wormbase_core.reactivity import SemanticInterpretation
from wormbase_ontology_seed import Concept, Loader


# ---------------------------------------------------------------------------
# Stub classifier — regex / heuristic only, deterministic
# ---------------------------------------------------------------------------


# Question shape: starts with a wh-word OR contains a question mark.
# We're conservative: mid-sentence verbs like "is" don't count as questions.
_QUESTION_HINTS = re.compile(
    r"^\s*(what|why|how|when|who|where|did|do|does|is|are|was|were|can|could|should|"
    r"how many|how much)\b"
    r"|\?",
    re.IGNORECASE | re.MULTILINE,
)
_FILE_REF_HINT = re.compile(
    r"\b\S+\.(csv|tsv|parquet|json|jsonl|xlsx|sqlite)\b", re.IGNORECASE
)
# Phrases that strongly suggest a data-source mention (not a question).
_DATA_MENTION_PHRASES = re.compile(
    r"\b(we should|we have|our|the|in segment|from segment|segment data|"
    r"source of truth|stream|export|pull|pipe|piping|piped|connect|connected|"
    r"flowing|growing|flow)\b",
    re.IGNORECASE,
)
_CRED_PATTERNS = [
    re.compile(r"postgres(?:ql)?://[^\s]+", re.IGNORECASE),
    re.compile(r"mysql://[^\s]+", re.IGNORECASE),
    re.compile(r"mongodb(?:\+srv)?://[^\s]+", re.IGNORECASE),
    re.compile(r"sqlite:///[^\s]+", re.IGNORECASE),
    re.compile(r"s3://[^\s]+", re.IGNORECASE),
    re.compile(r"\bsk_(live|test)_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bpk_(live|test)_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9_\-\.]{16,}", re.IGNORECASE),
]


class StubClassifier:
    """Regex-driven semantic classifier seeded with the ontology aliases."""

    def __init__(
        self,
        loader: Loader | None = None,
        domain: str = "saas",
    ) -> None:
        self._loader = loader or Loader()
        self._concepts: list[Concept] = self._loader.load_ontology(domain)  # type: ignore[arg-type]
        # Pre-compile alias regexes for fast lookup.
        self._alias_index: list[tuple[Concept, list[re.Pattern[str]]]] = []
        for c in self._concepts:
            patterns = [
                re.compile(rf"\b{re.escape(a)}\b", re.IGNORECASE)
                for a in (*c.aliases, c.label, c.id)
                if a
            ]
            self._alias_index.append((c, patterns))

    async def classify(
        self, text: str, event_context: dict[str, Any]
    ) -> SemanticInterpretation:
        return self._classify_sync(text, event_context)

    # Sync helper exposed for tests + composite.
    def _classify_sync(
        self, text: str, event_context: dict[str, Any]
    ) -> SemanticInterpretation:
        if not text or not text.strip():
            return SemanticInterpretation(
                event_type="other", confidence=0.0, raw_text=text
            )

        # Credential detection — highest precedence.
        for cre in _CRED_PATTERNS:
            if cre.search(text):
                return SemanticInterpretation(
                    concepts=self._matched_concepts(text),
                    event_type="credential_offer",
                    confidence=0.95,
                    raw_text=text,
                )

        matches = self._matched_concepts(text)
        has_file_ref = bool(_FILE_REF_HINT.search(text))
        has_question_hint = bool(_QUESTION_HINTS.search(text))
        has_data_phrase = bool(_DATA_MENTION_PHRASES.search(text))

        if has_file_ref:
            return SemanticInterpretation(
                concepts=matches,
                event_type="file_reference",
                confidence=0.90,
                raw_text=text,
            )

        # Source-archetype concept + data phrase => data_mention (regardless
        # of question shape: "how is the stripe data flowing?" is a data_mention
        # in our taxonomy).
        archetype_match = any(
            self._concept_category(m) == "source_archetype" for m in matches
        )
        if archetype_match and has_data_phrase:
            return SemanticInterpretation(
                concepts=matches,
                event_type="data_mention",
                confidence=0.84,
                raw_text=text,
            )

        # Has at least one ontology hit + question marker -> question.
        if matches and has_question_hint:
            return SemanticInterpretation(
                concepts=matches,
                event_type="question",
                confidence=0.86,
                raw_text=text,
            )

        # Has data archetype mention without a question shape -> data_mention.
        if matches and archetype_match:
            return SemanticInterpretation(
                concepts=matches,
                event_type="data_mention",
                confidence=0.80,
                raw_text=text,
            )

        # Has ontology hit but no question or archetype -> statement-ish.
        if matches:
            # If there's a question hint, lean question; else statement.
            if has_question_hint:
                return SemanticInterpretation(
                    concepts=matches,
                    event_type="question",
                    confidence=0.78,
                    raw_text=text,
                )
            return SemanticInterpretation(
                concepts=matches,
                event_type="statement",
                confidence=0.65,
                raw_text=text,
            )

        # No ontology — only count as question if a wh-word starts the sentence.
        if has_question_hint and re.match(
            r"^\s*(what|why|how|when|who|where|how many|how much|did|do|does|is|are|was|were|can|could|should)\b",
            text, re.IGNORECASE,
        ):
            return SemanticInterpretation(
                concepts=[],
                event_type="question",
                confidence=0.30,
                raw_text=text,
            )

        return SemanticInterpretation(
            concepts=[],
            event_type="other",
            confidence=0.10,
            raw_text=text,
        )

    def _matched_concepts(self, text: str) -> list[str]:
        out: list[str] = []
        for c, patterns in self._alias_index:
            if any(p.search(text) for p in patterns):
                out.append(c.id)
        return out

    def _concept_category(self, cid: str) -> str | None:
        for c, _ in self._alias_index:
            if c.id == cid:
                return c.category
        return None


# ---------------------------------------------------------------------------
# Ollama Cloud classifier
# ---------------------------------------------------------------------------


_DEFAULT_OLLAMA_BASE = "https://ollama.com"
_DEFAULT_OLLAMA_MODEL = "kimi-k2.6:cloud"


_PROMPT_TEMPLATE = """You are WormBase's semantic classifier. Classify the user's message.

Reply ONLY with valid JSON matching this schema:
{{"concepts": ["concept_id", ...], "event_type": "<one of: question|statement|file_reference|credential_offer|data_mention|other>", "confidence": 0.0-1.0}}

Channel context: source={source}, channel_id={channel_id}.
Candidate concepts (choose zero or more by id):
{candidates}

Message:
---
{text}
---
"""


class OllamaCloudClassifier:
    """Calls Ollama Cloud chat endpoint; expects kimi-k2.6:cloud-shaped output."""

    def __init__(
        self,
        loader: Loader | None = None,
        domain: str = "saas",
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = _DEFAULT_OLLAMA_MODEL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("OLLAMA_API_KEY")
        self._base = (base_url or os.environ.get(
            "OLLAMA_API_BASE", _DEFAULT_OLLAMA_BASE
        )).rstrip("/")
        self._model = model
        self._client = client
        loader = loader or Loader()
        self._concepts = loader.load_ontology(domain)  # type: ignore[arg-type]

    def _build_prompt(self, text: str, context: dict[str, Any]) -> str:
        # Compact candidate list — keep prompt size bounded.
        cands = "\n".join(
            f"- {c.id}: {c.label} (aliases: {', '.join(c.aliases[:5])})"
            for c in self._concepts
        )
        return _PROMPT_TEMPLATE.format(
            source=context.get("source", "channel"),
            channel_id=context.get("channel_id"),
            candidates=cands,
            text=text,
        )

    async def classify(
        self, text: str, event_context: dict[str, Any]
    ) -> SemanticInterpretation:
        if not self._api_key:
            # Without an API key, refuse to attempt; caller falls back.
            return SemanticInterpretation(
                event_type="other", confidence=0.0, raw_text=text,
            )
        prompt = self._build_prompt(text, event_context)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": "Output JSON only. No prose."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
            "stream": False,
        }
        client = self._client or httpx.AsyncClient(timeout=20.0)
        own_client = self._client is None
        try:
            r = await client.post(
                f"{self._base}/api/chat", headers=headers, json=body,
            )
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, json.JSONDecodeError, KeyError):
            return SemanticInterpretation(
                event_type="other", confidence=0.0, raw_text=text,
            )
        finally:
            if own_client:
                await client.aclose()

        content = (
            data.get("message", {}).get("content")
            if isinstance(data, dict) else None
        )
        if not content:
            return SemanticInterpretation(
                event_type="other", confidence=0.0, raw_text=text,
            )
        return _parse_classifier_json(content, text)


def _parse_classifier_json(raw: str, text: str) -> SemanticInterpretation:
    """Best-effort JSON parse; returns 'other'/0.0 on any failure."""
    try:
        # Strip markdown code fences if present.
        stripped = raw.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", stripped, flags=re.MULTILINE)
        parsed = json.loads(stripped)
        if not isinstance(parsed, dict):
            raise ValueError
        return SemanticInterpretation(
            concepts=list(parsed.get("concepts") or []),
            event_type=parsed.get("event_type", "other"),
            confidence=float(parsed.get("confidence", 0.0)),
            raw_text=text,
        )
    except (ValueError, TypeError, json.JSONDecodeError):
        return SemanticInterpretation(
            event_type="other", confidence=0.0, raw_text=text,
        )


# ---------------------------------------------------------------------------
# Composite — stub first, network on residual
# ---------------------------------------------------------------------------


class SemanticClassifier:
    """Stub-first classifier; falls through to the cloud only on low confidence."""

    def __init__(
        self,
        loader: Loader | None = None,
        domain: str = "saas",
        *,
        upgrade_threshold: float = 0.50,
        cloud: OllamaCloudClassifier | None = None,
        stub: StubClassifier | None = None,
    ) -> None:
        loader = loader or Loader()
        self._stub = stub or StubClassifier(loader, domain)
        self._cloud = cloud
        self._upgrade_threshold = upgrade_threshold

    async def classify(
        self, text: str, event_context: dict[str, Any]
    ) -> SemanticInterpretation:
        primary = await self._stub.classify(text, event_context)
        if primary.confidence >= self._upgrade_threshold or self._cloud is None:
            return primary
        secondary = await self._cloud.classify(text, event_context)
        # Pick the higher-confidence interpretation.
        return secondary if secondary.confidence > primary.confidence else primary


# ---------------------------------------------------------------------------
# Seed-bank evaluator (used by tests + autoresearch)
# ---------------------------------------------------------------------------


def _seed_bank_path() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures" / "seed_bank.yaml"


async def evaluate_on_seed_bank(
    classifier: Callable[..., Any],
    seed_bank_path: Path | None = None,
) -> dict[str, Any]:
    """Compute precision against the bundled seed bank.

    classifier may be any object with an async ``classify(text, context)``.
    Returns dict with keys: total, correct, accuracy, by_event_type.
    """
    import yaml
    p = seed_bank_path or _seed_bank_path()
    examples = yaml.safe_load(p.read_text(encoding="utf-8"))
    total = 0
    correct = 0
    by_type: dict[str, list[int]] = {}
    for ex in examples:
        total += 1
        ctx = {
            "source": ex.get("channel_type", "channel"),
            "channel_id": "C-test",
        }
        res = await classifier.classify(ex["text"], ctx)
        bt = by_type.setdefault(ex["expected_event_type"], [0, 0])
        bt[1] += 1
        ok_event = res.event_type == ex["expected_event_type"]
        ok_concept = (
            not ex.get("expected_concepts")
            or any(c in res.concepts for c in ex["expected_concepts"])
        )
        if ok_event and ok_concept:
            correct += 1
            bt[0] += 1
    return {
        "total": total,
        "correct": correct,
        "accuracy": correct / total if total else 0.0,
        "by_event_type": {k: f"{v[0]}/{v[1]}" for k, v in by_type.items()},
    }


__all__ = [
    "OllamaCloudClassifier",
    "SemanticClassifier",
    "StubClassifier",
    "evaluate_on_seed_bank",
]
