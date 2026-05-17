"""Seed a real `Install` row from a pre-issued Slack bot token.

Companion to ``seed_personas.py``: the personas-seed populates the
canonical Person roster; this module installs the worm itself so the
dashboard's no-installer redirect guard lets the operator past
``/onboarding`` without driving the full OAuth UI.

Production install path is the dashboard's
``/onboarding/oauth/{platform}/start`` → ``callback`` chain. The CLI
helper here is the **dev/CI shortcut**: when an operator already has a
long-lived bot token (e.g. from a Slack app they own), they can install
without standing up an OAuth tunnel by exporting
``SLACK_BOT_TOKEN_BASEWORM`` (or ``SLACK_BOT_TOKEN_${TENANT_UPPER}``)
and passing ``--install-from-env`` to ``wormbase demo seed``.

The function:

  1. Reads the bot token from env (caller's responsibility to choose
     which env var).
  2. Calls Slack ``auth.test`` → team_id / bot_user_id / installer
     user_id.
  3. Calls Slack ``users.info`` on the installer → display name + email
     + avatar.
  4. POSTs to worm-core ``POST /api/v1/installs`` with a
     ``vault://local-dev/<random>`` ``oauth_grant_ref`` (the dev shim
     for un-KMSed envs; production OAuth wraps the token in
     ``kms://``).

Public API:

* ``seed_install_from_env(*, tenant, dashboard_api_base, api_token)``
  — returns a ``SeedInstallReport`` on success or ``None`` when the
  ``SLACK_BOT_TOKEN_${TENANT_UPPER}`` env var is unset (caller decides
  whether to skip silently or surface to the user).
"""

from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx

logger = logging.getLogger("wormbase.sim.seed_install")


# ---------------------------------------------------------------------------
# Default bot scopes — must match the manifest at
# ``infra/openclaw/SLACK_MANIFEST.md``. The list is recorded in the
# ledger via ``emit_install_completed`` so policy gates can audit it.
# ---------------------------------------------------------------------------

DEFAULT_SLACK_BOT_SCOPES: tuple[str, ...] = (
    "channels:read",
    "channels:history",
    "channels:join",
    "chat:write",
    "chat:write.customize",
    "chat:write.public",
    "files:read",
    "files:write",
    "users:read",
    "users:read.email",
    "groups:read",
    "groups:history",
    "im:history",
    "im:read",
    "im:write",
)


@dataclass
class SeedInstallReport:
    """Outcome of a ``seed_install_from_env`` call."""

    install_id: UUID
    installer_person_id: UUID
    installer_email: str
    installer_name: str
    platform: str
    bot_user_id: str
    team_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "install_id": str(self.install_id),
            "installer_person_id": str(self.installer_person_id),
            "installer_email": self.installer_email,
            "installer_name": self.installer_name,
            "platform": self.platform,
            "bot_user_id": self.bot_user_id,
            "team_id": self.team_id,
        }


def _bot_token_env_name(tenant: str) -> str:
    """Bot token env var name derived from the tenant slug.

    ``baseworm`` → ``SLACK_BOT_TOKEN_BASEWORM``. The convention matches
    the `bot-token-env` flag default in ``demo run``.
    """
    return f"SLACK_BOT_TOKEN_{tenant.upper()}"


async def seed_install_from_env(
    *,
    tenant: str,
    dashboard_api_base: str,
    api_token: str,
    bot_token_env: str | None = None,
    http_client: httpx.AsyncClient | None = None,
    timeout_s: float = 10.0,
) -> SeedInstallReport | None:
    """Install the worm using a bot token already in the environment.

    Returns ``None`` (without raising) when the configured bot-token env
    var is unset — callers handle that branch (typically: print a
    pointer to ``--install-from-env`` then exit non-zero, or proceed
    without an install).

    Raises ``RuntimeError`` for any non-environmental failure
    (Slack API error, worm-core 4xx/5xx, etc.). The caller is expected
    to surface the message verbatim.

    Parameters
    ----------
    tenant:
        Tenant slug; sent as ``X-Tenant-Slug`` header on the
        worm-core POST. Also used to derive the default bot-token env
        name (``SLACK_BOT_TOKEN_${TENANT_UPPER}``).
    dashboard_api_base:
        Base URL for the worm-core write API.
    api_token:
        Bearer for the worm-core write API
        (``WORMBASE_LEDGER_API_TOKEN``).
    bot_token_env:
        Override the default env-var name. When ``None``,
        ``SLACK_BOT_TOKEN_${tenant.upper()}`` is used.
    http_client:
        Optional pre-built ``httpx.AsyncClient`` (tests inject a
        ``MockTransport`` here).
    timeout_s:
        Per-request timeout.
    """
    if not api_token:
        raise ValueError("api_token is required (worm-core bearer auth)")
    if not dashboard_api_base:
        raise ValueError("dashboard_api_base is required")
    if not tenant:
        raise ValueError("tenant is required")

    env_name = bot_token_env or _bot_token_env_name(tenant)
    bot_token = os.environ.get(env_name, "").strip()
    if not bot_token:
        # Honest signal to the caller: env-driven install was requested
        # but no token is in the environment. We return None instead of
        # raising so the CLI can frame the error in user terms.
        logger.info(
            "%s unset; seed_install_from_env returning None", env_name,
        )
        return None

    base = dashboard_api_base.rstrip("/")
    headers = {
        "Authorization": f"Bearer {api_token}",
        "X-Tenant-Slug": tenant,
        "Content-Type": "application/json",
    }

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=timeout_s)

    try:
        # Step 1: auth.test → team_id, bot_user_id, installer user_id.
        auth_test = await _slack_post(
            client, "https://slack.com/api/auth.test", bot_token,
        )
        team_id = str(auth_test.get("team_id") or "").strip()
        bot_user_id = str(auth_test.get("bot_id") or auth_test.get("user_id") or "").strip()
        # The installer is the `user_id` on auth.test — the user the
        # bot was installed by; bot_id is for the bot's identity itself.
        # Slack's auth.test returns both `bot_id` (the BXXXX bot id) and
        # `user_id` (the UXXXX human installer). Use bot_user_id for
        # the bot's own identity (UXXX of the bot user) when we need it
        # for chat.postMessage; here we want the installer.
        installer_user_id = str(auth_test.get("user_id") or "").strip()
        if not (team_id and installer_user_id):
            raise RuntimeError(
                f"slack auth.test returned malformed body "
                f"(team_id={team_id!r}, user_id={installer_user_id!r}): "
                f"{auth_test}"
            )
        # Some bot tokens (xoxb) report bot_id as BXXXXXXX and user_id
        # as the bot's own UXXXXXXX. We want the bot user id for the
        # ``bot_user_id`` install field. Prefer the auth.test
        # ``bot_id`` but fall back to ``user_id`` if missing.
        if not bot_user_id:
            bot_user_id = installer_user_id

        # Step 2: users.info on the installer for name + email + avatar.
        users_info = await _slack_get(
            client, "https://slack.com/api/users.info", bot_token,
            params={"user": installer_user_id},
        )
        user = users_info.get("user") or {}
        profile = user.get("profile") or {}
        installer_name = (
            (user.get("real_name") or "").strip()
            or (profile.get("real_name") or "").strip()
            or (user.get("name") or "").strip()
            or installer_user_id
        )
        installer_email = (profile.get("email") or "").strip()
        installer_avatar_url = (profile.get("image_192") or "").strip() or None
        if not installer_email:
            override = os.environ.get(
                "WORMBASE_INSTALLER_EMAIL_OVERRIDE", "",
            ).strip()
            if override:
                installer_email = override
                if not installer_name or installer_name == installer_user_id:
                    installer_name = (
                        os.environ.get(
                            "WORMBASE_INSTALLER_NAME_OVERRIDE", "",
                        ).strip()
                        or installer_name
                    )
            else:
                raise RuntimeError(
                    f"slack users.info for {installer_user_id} returned no email; "
                    "ensure the bot token has the users:read.email scope and the "
                    "installer has an email visible in the workspace, or set "
                    "WORMBASE_INSTALLER_EMAIL_OVERRIDE for dev-tooling installs "
                    "(xoxb tokens issued at app creation have no human installer "
                    "and no email on the bot user)."
                )

        # Step 3: POST to worm-core /api/v1/installs.
        install_body = {
            "platform": "slack",
            "installer_email": installer_email,
            "installer_name": installer_name,
            "installer_avatar_url": installer_avatar_url,
            "platform_user_id": installer_user_id,
            "oauth_grant_ref": _vault_local_dev_ref(),
            "scopes": list(DEFAULT_SLACK_BOT_SCOPES),
            "bot_user_id": bot_user_id,
        }
        try:
            install_resp = await client.post(
                f"{base}/api/v1/installs",
                headers=headers,
                json=install_body,
            )
        except httpx.HTTPError as exc:
            raise RuntimeError(f"POST /api/v1/installs failed: {exc}") from exc

        if install_resp.status_code >= 400:
            raise RuntimeError(
                f"POST /api/v1/installs returned HTTP {install_resp.status_code}: "
                f"{install_resp.text}"
            )

        data = install_resp.json()
        install_id = UUID(data["install_id"])
        installer_person_id = UUID(data["installer_person_id"])

        report = SeedInstallReport(
            install_id=install_id,
            installer_person_id=installer_person_id,
            installer_email=installer_email,
            installer_name=installer_name,
            platform="slack",
            bot_user_id=bot_user_id,
            team_id=team_id,
        )
        logger.info(
            "seeded install: install_id=%s installer=%s (%s) team=%s",
            install_id, installer_name, installer_email, team_id,
        )
        return report
    finally:
        if owns_client:
            await client.aclose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _slack_post(
    client: httpx.AsyncClient,
    url: str,
    bot_token: str,
    *,
    json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Slack web-API POST with bot-token auth + ``ok``-check.

    Slack returns 200 even on app-level errors and signals failure via
    ``ok: false``; we mirror that by raising ``RuntimeError`` with the
    Slack-supplied ``error`` field.
    """
    headers = {
        "Authorization": f"Bearer {bot_token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    try:
        resp = await client.post(url, headers=headers, json=json or {})
    except httpx.HTTPError as exc:
        raise RuntimeError(f"slack {url} HTTP error: {exc}") from exc
    if resp.status_code >= 400:
        raise RuntimeError(f"slack {url} HTTP {resp.status_code}: {resp.text}")
    body = resp.json()
    if not body.get("ok"):
        raise RuntimeError(
            f"slack {url} returned ok=false: error={body.get('error')!r} body={body}"
        )
    return body


async def _slack_get(
    client: httpx.AsyncClient,
    url: str,
    bot_token: str,
    *,
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Slack web-API GET with bot-token auth + ``ok``-check."""
    headers = {"Authorization": f"Bearer {bot_token}"}
    try:
        resp = await client.get(url, headers=headers, params=params)
    except httpx.HTTPError as exc:
        raise RuntimeError(f"slack {url} HTTP error: {exc}") from exc
    if resp.status_code >= 400:
        raise RuntimeError(f"slack {url} HTTP {resp.status_code}: {resp.text}")
    body = resp.json()
    if not body.get("ok"):
        raise RuntimeError(
            f"slack {url} returned ok=false: error={body.get('error')!r} body={body}"
        )
    return body


def _vault_local_dev_ref() -> str:
    """Return a ``vault://local-dev/<rand>`` reference for the dev install path.

    The dashboard OAuth callback wraps tokens in ``kms://`` when
    ``WORMBASE_KMS_KEY_ID`` is set; without it, the callback falls back
    to writing the raw token bytes to a Postgres ``_secrets`` table
    addressed by ``vault://local-dev/{id}``. The CLI seed path mirrors
    that fallback shape — the worm-core ``InstallCompletedPayload``
    validator only accepts ``kms://`` and ``vault://`` prefixes, so the
    ledger entry stays well-formed regardless of which driver wrote it.
    """
    return f"vault://local-dev/{secrets.token_hex(16)}"


__all__ = [
    "DEFAULT_SLACK_BOT_SCOPES",
    "SeedInstallReport",
    "seed_install_from_env",
]
