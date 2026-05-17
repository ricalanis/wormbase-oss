"""Shared pytest fixtures for wormbase-agent-gateway tests.

Adds the `_vault_available` helper used by Protocol-conformance tests to
conditionally skip the Vault broker parametrize entry when `VAULT_ADDR` /
`VAULT_TOKEN` env vars are absent (CI / hermetic-dev case).
"""
from __future__ import annotations

import os


def vault_available() -> bool:
    """Return True iff VAULT_ADDR and VAULT_TOKEN are both set in env."""
    return bool(os.environ.get("VAULT_ADDR")) and bool(os.environ.get("VAULT_TOKEN"))
