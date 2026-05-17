"""CredentialBroker Protocol — unified for data and model credentials.

Per spec §3.3, one Protocol + one Vault instance covers both:
- Data creds: Snowflake JWT, dbt artifacts URL, etc.
- Model creds: Anthropic API key, Kimi key (OLLAMA_API_KEY), Gemma endpoint URL

The spike S4 verified this works against a single Vault instance.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .types import AccountHandle, DataScope, ModelScope, ScopedToken


@runtime_checkable
class CredentialBroker(Protocol):
    """Unified broker over data and model credentials.

    Implementations must satisfy `isinstance(impl, CredentialBroker)` at runtime
    so dispatch/registry code can validate without import-time coupling.
    """

    kind: str  # "vault" | "env" | "aws_sm" (v1.1) | "customer_kms" (v1.1)

    # ---- DATA access ----

    async def hold_data_account(
        self,
        install_id: str,
        *,
        upstream_kind: str,
    ) -> AccountHandle: ...

    async def issue_data_token(
        self,
        *,
        agent_id: str,
        scope: DataScope,
        ttl_s: int,
    ) -> ScopedToken: ...

    # ---- MODEL access ----

    async def hold_model_account(
        self,
        install_id: str,
        *,
        model_kind: str,
    ) -> AccountHandle: ...

    async def issue_model_token(
        self,
        *,
        agent_id: str,
        scope: ModelScope,
        ttl_s: int,
    ) -> ScopedToken: ...

    # ---- Lifecycle ----

    async def is_valid(self, token_id: str) -> bool: ...

    async def revoke(self, token_id: str) -> None: ...
