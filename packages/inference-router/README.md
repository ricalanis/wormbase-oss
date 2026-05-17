# wormbase-inference-router

Deterministic router between remote inference (Kimi K2.6 via API, high-stakes reasoning) and own inference (Gemma 4 E4B on VLAN endpoint, high-volume classification/embedding/summarization). Exposes a single `call(call_type, prompt, ...)` interface that dispatches by type, applies a hash-keyed cache for demo reproducibility, and falls back from Gemma to Kimi on a 2s timeout. Python-only; depended on by `worm-core` (classifier) and `sim-harness` (bot message generation).
