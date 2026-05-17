"""Inference-router test fixtures."""
from __future__ import annotations

import os

# Ensure tests don't accidentally hit a real LLM endpoint via env.
os.environ.pop("OLLAMA_API_KEY", None)
os.environ.pop("OLLAMA_OWN_API_KEY", None)
