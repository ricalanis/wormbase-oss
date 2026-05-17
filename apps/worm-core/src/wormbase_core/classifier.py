"""Backwards-compat shim — classifier.py lifted to wormbase_chat_presence in Wave B.

Implementations live in wormbase_chat_presence.classifier (chat-worm-private).
This shim re-exports for any worm-core caller that hasn't migrated yet.
"""
from __future__ import annotations

from wormbase_chat_presence.classifier import (
    OllamaCloudClassifier,
    SemanticClassifier,
    StubClassifier,
    evaluate_on_seed_bank,
)

__all__ = [
    "OllamaCloudClassifier",
    "SemanticClassifier",
    "StubClassifier",
    "evaluate_on_seed_bank",
]
