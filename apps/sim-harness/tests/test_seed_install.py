"""Tests for ``seed_install_from_env`` (T1 of the onboarding tail).

Two paths exercised:

1. **Token in env, mocks for Slack + worm-core** — the helper hits
   ``auth.test`` + ``users.info`` then POSTs the orchestrator body to
   ``/api/v1/installs`` with the right shape (ovault://`` ref, scopes,
   bot/user ids, etc.).
2. **Token unset** — the helper returns ``None`` (callers decide how
   to surface) and writes a single info-level log line so the operator
   can see what happened.
"""

from __future__ import annotations

import json as _json
from uuid import uuid4

import httpx
import pytest

from wormbase_sim_harness.seed_install import (
    DEFAULT_SLACK_BOT_SCOPES,
    seed_install_from_env,
)


@pytest.mark.asyncio
async def test_seed_install_from_env_posts_to_worm_core(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end happy path: env-set token → Slack mocks → worm-core POST.

    The wire is captured so we can assert the body shape sent to
    ``/api/v1/installs`` matches the orchestrator contract.
    """
    monkeypatch.setenv("SLACK_BOT_TOKEN_BASEWORM", "xoxb-fake-bot-token")

    install_id = uuid4()
    installer_person_id = uuid4()

    requests_seen: list[tuple[str, dict | None]] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        try:
            body = (
                _json.loads(request.content.decode())
                if request.content
                else None
            )
        except Exception:
            body = None
        requests_seen.append((str(request.url), body))

        # Slack auth.test
        if request.url.host == "slack.com" and path == "/api/auth.test":
            assert request.headers.get("Authorization") == "Bearer xoxb-fake-bot-token"
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "team_id": "T123",
                    "user_id": "UINSTALLER",
                    "bot_id": "UBOT",
                },
            )
        # Slack users.info
        if request.url.host == "slack.com" and path == "/api/users.info":
            assert request.url.params.get("user") == "UINSTALLER"
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "user": {
                        "id": "UINSTALLER",
                        "real_name": "Inez Staller",
                        "name": "inez",
                        "profile": {
                            "real_name": "Inez Staller",
                            "email": "inez@example.com",
                            "image_192": "https://example.com/avatar.png",
                        },
                    },
                },
            )
        # worm-core install
        if path == "/api/v1/installs":
            assert request.headers.get("Authorization") == "Bearer fake-token"
            assert request.headers.get("X-Tenant-Slug") == "baseworm"
            assert body is not None
            assert body["platform"] == "slack"
            assert body["installer_email"] == "inez@example.com"
            assert body["installer_name"] == "Inez Staller"
            assert body["installer_avatar_url"] == "https://example.com/avatar.png"
            assert body["platform_user_id"] == "UINSTALLER"
            # vault://local-dev/<rand> shape — never a raw token,
            # never a "dev://" prefix.
            assert body["oauth_grant_ref"].startswith("vault://local-dev/")
            assert "xoxb" not in body["oauth_grant_ref"]
            # Scopes match the manifest.
            assert set(body["scopes"]) == set(DEFAULT_SLACK_BOT_SCOPES)
            # Bot user id propagated.
            assert body["bot_user_id"]
            return httpx.Response(
                201,
                json={
                    "install_id": str(install_id),
                    "installer_person_id": str(installer_person_id),
                    "entry_ids": [str(uuid4()) for _ in range(8)],
                },
            )

        return httpx.Response(404, text=f"unexpected: {request.url}")

    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        report = await seed_install_from_env(
            tenant="baseworm",
            dashboard_api_base="http://worm-core:8910",
            api_token="fake-token",
            http_client=client,
        )

    assert report is not None
    assert report.install_id == install_id
    assert report.installer_person_id == installer_person_id
    assert report.installer_email == "inez@example.com"
    assert report.installer_name == "Inez Staller"
    assert report.platform == "slack"
    assert report.team_id == "T123"

    # All three calls hit the wire.
    paths_hit = {url for url, _ in requests_seen}
    assert any("auth.test" in u for u in paths_hit)
    assert any("users.info" in u for u in paths_hit)
    assert any("/api/v1/installs" in u for u in paths_hit)


@pytest.mark.asyncio
async def test_seed_install_from_env_returns_none_when_unset(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When ``SLACK_BOT_TOKEN_BASEWORM`` is unset, return None — no synth fallback."""
    monkeypatch.delenv("SLACK_BOT_TOKEN_BASEWORM", raising=False)

    # Use a transport that would fail loudly if the helper tried to make
    # any HTTP request — proves the env-check happens before any wire.
    def _refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError(
            f"unexpected HTTP call when env unset: {request.url}"
        )

    transport = httpx.MockTransport(_refuse)
    with caplog.at_level("INFO", logger="wormbase.sim.seed_install"):
        async with httpx.AsyncClient(transport=transport) as client:
            result = await seed_install_from_env(
                tenant="baseworm",
                dashboard_api_base="http://worm-core:8910",
                api_token="fake-token",
                http_client=client,
            )

    assert result is None
    # Honest signal in the log so the CLI/operator can see the path taken.
    assert any(
        "SLACK_BOT_TOKEN_BASEWORM" in rec.message
        and "unset" in rec.message.lower()
        for rec in caplog.records
    )
