"""EnvCredentialBroker — local-dev impl using a file-based secret store.

Production deployments use Vault / AWS Secrets Manager. This impl exists to
keep unit tests + local dev hermetic (no network).

Layout under `secrets_dir`:

    secrets_dir/
        data/<upstream_kind>/<install_id>      # JSON secret payload
        _tokens.json                           # {token_id: {agent_id, expires_at}}
        _revoked.json                          # [token_id, ...]
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from .errors import AuthenticationError
from .types import AccountHandle, DataScope, ModelScope, ScopedToken


class EnvCredentialBroker:
    """File-based broker. Mirrors Vault's `data/<kind>/<install>` path convention
    so test fixtures + production code share one mental model.
    """

    kind: str = "env"

    def __init__(self, *, secrets_dir: Path) -> None:
        self._secrets_dir = Path(secrets_dir)
        try:
            self._secrets_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # pragma: no cover — environmental
            raise AuthenticationError(
                f"cannot create secrets_dir at {self._secrets_dir}: {exc}"
            ) from exc
        self._tokens_path = self._secrets_dir / "_tokens.json"
        self._revoked_path = self._secrets_dir / "_revoked.json"
        if not self._tokens_path.exists():
            self._tokens_path.write_text("{}")
        if not self._revoked_path.exists():
            self._revoked_path.write_text("[]")

    # Test/seed helper — mirrors hvac's put-secret shape so the Protocol-conformance
    # test suite seeds the same way against both brokers.
    async def put_secret(self, path: str, data: dict[str, Any]) -> None:
        full = self._secrets_dir / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(json.dumps(data))

    async def hold_data_account(
        self, install_id: str, *, upstream_kind: str
    ) -> AccountHandle:
        return self._read_account("data", upstream_kind, install_id)

    async def hold_model_account(
        self, install_id: str, *, model_kind: str
    ) -> AccountHandle:
        return self._read_account("model", model_kind, install_id)

    def _read_account(
        self, kind: str, upstream_kind: str, install_id: str
    ) -> AccountHandle:
        path = self._secrets_dir / "data" / upstream_kind / install_id
        if not path.exists():
            raise KeyError(f"no secret at {path}")
        return AccountHandle(
            kind=kind,  # type: ignore[arg-type]
            upstream_kind=upstream_kind,
            install_id=install_id,
            payload=json.loads(path.read_text()),
        )

    async def issue_data_token(
        self, *, agent_id: str, scope: DataScope, ttl_s: int
    ) -> ScopedToken:
        return self._issue("data", agent_id, scope, ttl_s)

    async def issue_model_token(
        self, *, agent_id: str, scope: ModelScope, ttl_s: int
    ) -> ScopedToken:
        return self._issue("model", agent_id, scope, ttl_s)

    def _issue(
        self, kind: str, agent_id: str, scope: Any, ttl_s: int
    ) -> ScopedToken:
        now = int(time.time())
        token = ScopedToken(
            token_id=f"env-{kind}-{uuid.uuid4()}",
            issued_at=now,
            expires_at=now + ttl_s,
            scope=scope,
            kind=kind,  # type: ignore[arg-type]
        )
        tokens = json.loads(self._tokens_path.read_text())
        tokens[token.token_id] = {"agent_id": agent_id, "expires_at": token.expires_at}
        self._tokens_path.write_text(json.dumps(tokens))
        return token

    async def is_valid(self, token_id: str) -> bool:
        if token_id in set(json.loads(self._revoked_path.read_text())):
            return False
        tokens = json.loads(self._tokens_path.read_text())
        record = tokens.get(token_id)
        return record is not None and record["expires_at"] > int(time.time())

    async def revoke(self, token_id: str) -> None:
        revoked = set(json.loads(self._revoked_path.read_text()))
        revoked.add(token_id)
        self._revoked_path.write_text(json.dumps(sorted(revoked)))
