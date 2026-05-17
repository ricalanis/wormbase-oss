"""CredentialBroker value types — discriminated union per credential_kind.

Per Wave 2 plan §Task 2 Step 1.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal


@dataclass(frozen=True)
class AccountHandle:
    """Opaque handle returned by hold_*_account. Wraps the broker-resolved creds."""

    kind: Literal["data", "model"]
    upstream_kind: str  # "snowflake" | "kimi" | etc.
    install_id: str
    payload: dict[str, Any]  # implementation-specific; opaque to consumers


@dataclass(frozen=True)
class DataScope:
    resource_id: str
    row_filter: str | None = None
    column_mask: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModelScope:
    model_kind: str
    budget_usd: Decimal
    max_tokens_per_call: int | None = None
    rate_limit_rps: int | None = None


@dataclass(frozen=True)
class ScopedToken:
    token_id: str
    issued_at: int
    expires_at: int
    scope: DataScope | ModelScope
    kind: Literal["data", "model"]
