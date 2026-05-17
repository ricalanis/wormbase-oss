"""VaultCredentialBroker — productionized S4 spike.

Promotes `spikes/2026-05-10-semantic-layer/s4_credential_broker/spike.py` to
production. Key differences from spike:

1. **API shape locked to spec §3.3 Protocol**: `issue_data_token` /
   `issue_model_token` take `scope: DataScope | ModelScope` (not free dicts).
2. **`put_secret` method**: signature matches `EnvCredentialBroker.put_secret`
   so the Protocol-conformance test suite seeds identically across both.
3. **Class attribute `kind: str = "vault"`** — required for Protocol.
4. **Reload `_issued` from Vault KV at startup**: spike's in-memory state did
   not survive broker restart (S4 finding). On `__init__`, we list every
   `tokens/<kind>/*` path and rebuild `_issued` so token validity survives
   process restarts.
5. **`is_valid` falls back to Vault KV** when the in-memory record is missing,
   supporting broker-restart recovery in mid-flight.

Vault lease wiring is deferred to v1.1 (per S4 risk). Static KV + broker-side
TTL gating is acceptable for Wave 2.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from decimal import Decimal
from typing import Any

import hvac

from .errors import AuthenticationError
from .types import AccountHandle, DataScope, ModelScope, ScopedToken


class VaultCredentialBroker:
    """Hashicorp-Vault-backed broker covering both data and model credentials."""

    kind: str = "vault"

    def __init__(self, *, addr: str, token: str, mount_point: str = "secret") -> None:
        self._client = hvac.Client(url=addr, token=token)
        if not self._client.is_authenticated():
            raise AuthenticationError(
                f"Vault auth failed against {addr} (token rejected or sealed)"
            )
        self._mount_point = mount_point
        self._revoked: set[str] = set()
        self._issued: dict[str, ScopedToken] = {}
        # State-reload (S4 finding): rebuild in-memory `_issued` from Vault KV
        # at startup so broker restart doesn't drop token validity tracking.
        self._reload_issued_from_vault()

    # ------------------------------------------------------------------ init
    def _reload_issued_from_vault(self) -> None:
        """List every `tokens/<kind>/*` path and rebuild `_issued`."""
        for kind in ("data", "model"):
            try:
                listing = self._client.secrets.kv.v2.list_secrets(
                    path=f"tokens/{kind}",
                    mount_point=self._mount_point,
                )
            except hvac.exceptions.InvalidPath:
                # No tokens issued yet for this kind — fresh install.
                continue
            except Exception:  # pragma: no cover — Vault unavailable mid-startup
                continue
            for token_id in listing.get("data", {}).get("keys", []):
                try:
                    record = self._client.secrets.kv.v2.read_secret_version(
                        path=f"tokens/{kind}/{token_id}",
                        mount_point=self._mount_point,
                        raise_on_deleted_version=True,
                    )
                except Exception:  # pragma: no cover — partial read race
                    continue
                payload = record["data"]["data"]
                scope = self._scope_from_payload(kind, payload.get("scope", {}))
                self._issued[token_id] = ScopedToken(
                    token_id=token_id,
                    issued_at=int(payload.get("issued_at", 0)),
                    expires_at=int(payload["expires_at"]),
                    scope=scope,
                    kind=kind,  # type: ignore[arg-type]
                )

    @staticmethod
    def _scope_from_payload(
        kind: str, scope_data: dict[str, Any]
    ) -> DataScope | ModelScope:
        if kind == "data":
            return DataScope(
                resource_id=scope_data.get("resource_id", ""),
                row_filter=scope_data.get("row_filter"),
                column_mask=tuple(scope_data.get("column_mask", ())),
            )
        # model
        return ModelScope(
            model_kind=scope_data.get("model_kind", ""),
            budget_usd=Decimal(str(scope_data.get("budget_usd", "0"))),
            max_tokens_per_call=scope_data.get("max_tokens_per_call"),
            rate_limit_rps=scope_data.get("rate_limit_rps"),
        )

    # ------------------------------------------------------------- put_secret
    async def put_secret(self, path: str, data: dict[str, Any]) -> None:
        """Test/seed helper. Mirrors `EnvCredentialBroker.put_secret`."""
        await asyncio.to_thread(
            self._client.secrets.kv.v2.create_or_update_secret,
            path=path,
            secret=data,
            mount_point=self._mount_point,
        )

    # ----------------------------------------------------- hold_*_account
    async def hold_data_account(
        self, install_id: str, *, upstream_kind: str
    ) -> AccountHandle:
        path = f"data/{upstream_kind}/{install_id}"
        result = await asyncio.to_thread(
            self._client.secrets.kv.v2.read_secret_version,
            path=path,
            mount_point=self._mount_point,
            raise_on_deleted_version=True,
        )
        return AccountHandle(
            kind="data",
            upstream_kind=upstream_kind,
            install_id=install_id,
            payload=result["data"]["data"],
        )

    async def hold_model_account(
        self, install_id: str, *, model_kind: str
    ) -> AccountHandle:
        path = f"data/{model_kind}/{install_id}"
        result = await asyncio.to_thread(
            self._client.secrets.kv.v2.read_secret_version,
            path=path,
            mount_point=self._mount_point,
            raise_on_deleted_version=True,
        )
        return AccountHandle(
            kind="model",
            upstream_kind=model_kind,
            install_id=install_id,
            payload=result["data"]["data"],
        )

    # ---------------------------------------------------- issue_*_token
    async def issue_data_token(
        self, *, agent_id: str, scope: DataScope, ttl_s: int
    ) -> ScopedToken:
        return await self._issue("data", agent_id, scope, ttl_s)

    async def issue_model_token(
        self, *, agent_id: str, scope: ModelScope, ttl_s: int
    ) -> ScopedToken:
        return await self._issue("model", agent_id, scope, ttl_s)

    async def _issue(
        self,
        kind: str,
        agent_id: str,
        scope: DataScope | ModelScope,
        ttl_s: int,
    ) -> ScopedToken:
        token_id = f"vault-{kind}-{uuid.uuid4()}"
        now = int(time.time())
        token = ScopedToken(
            token_id=token_id,
            issued_at=now,
            expires_at=now + ttl_s,
            scope=scope,
            kind=kind,  # type: ignore[arg-type]
        )
        await asyncio.to_thread(
            self._client.secrets.kv.v2.create_or_update_secret,
            path=f"tokens/{kind}/{token_id}",
            secret={
                "agent_id": agent_id,
                "scope": self._scope_to_payload(scope),
                "issued_at": str(now),
                "expires_at": str(token.expires_at),
            },
            mount_point=self._mount_point,
        )
        self._issued[token_id] = token
        return token

    @staticmethod
    def _scope_to_payload(scope: DataScope | ModelScope) -> dict[str, Any]:
        if isinstance(scope, DataScope):
            return {
                "resource_id": scope.resource_id,
                "row_filter": scope.row_filter,
                "column_mask": list(scope.column_mask),
            }
        # ModelScope
        return {
            "model_kind": scope.model_kind,
            "budget_usd": str(scope.budget_usd),
            "max_tokens_per_call": scope.max_tokens_per_call,
            "rate_limit_rps": scope.rate_limit_rps,
        }

    # ---------------------------------------------------------- lifecycle
    async def is_valid(self, token_id: str) -> bool:
        if token_id in self._revoked:
            return False
        token = self._issued.get(token_id)
        if token is None:
            # Broker-restart recovery: re-check Vault KV before declaring invalid.
            token = await self._lookup_in_vault(token_id)
            if token is None:
                return False
            self._issued[token_id] = token
        return token.expires_at > int(time.time())

    async def _lookup_in_vault(self, token_id: str) -> ScopedToken | None:
        for kind in ("data", "model"):
            try:
                record = await asyncio.to_thread(
                    self._client.secrets.kv.v2.read_secret_version,
                    path=f"tokens/{kind}/{token_id}",
                    mount_point=self._mount_point,
                    raise_on_deleted_version=True,
                )
            except hvac.exceptions.InvalidPath:
                continue
            except Exception:  # pragma: no cover — transient Vault error
                continue
            payload = record["data"]["data"]
            return ScopedToken(
                token_id=token_id,
                issued_at=int(payload.get("issued_at", 0)),
                expires_at=int(payload["expires_at"]),
                scope=self._scope_from_payload(kind, payload.get("scope", {})),
                kind=kind,  # type: ignore[arg-type]
            )
        return None

    async def revoke(self, token_id: str) -> None:
        self._revoked.add(token_id)
        # Best-effort: delete from Vault so restart-reload doesn't resurrect.
        for kind in ("data", "model"):
            try:
                await asyncio.to_thread(
                    self._client.secrets.kv.v2.delete_metadata_and_all_versions,
                    path=f"tokens/{kind}/{token_id}",
                    mount_point=self._mount_point,
                )
            except hvac.exceptions.InvalidPath:
                continue
            except Exception:  # pragma: no cover — transient Vault error
                continue
