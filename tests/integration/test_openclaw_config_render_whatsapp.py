"""L5 — OpenClaw entrypoint renders the channels.whatsapp config block correctly.

Phase 2 of the WhatsApp + conversation-provenance rollout. The entrypoint
script (`infra/openclaw/entrypoint.sh`) gained a `render_whatsapp_block`
function and a conditional `${WHATSAPP_BLOCK}` insertion inside the
top-level `channels` dict. These tests exercise the rendering path end
to end without touching a live OpenClaw daemon.

Coverage contract:

1. Disabled (default): no `channels.whatsapp` key in the rendered config.
   This guarantees existing Slack-only deploys are byte-identical with
   pre-Phase-2 behavior.
2. Enabled (`WHATSAPP_ENABLED_BASEWORM=true`): the block exists, has
   the four expected policy fields, and the comma-separated allowlists
   round-trip into JSON arrays with whitespace trimmed per element.
3. Default policies: when only the master switch is set, the rendered
   block carries `dmPolicy="pairing"` and `groupPolicy="allowlist"` —
   the conservative defaults declared in docker-compose.yml.

Strategy: copy the entrypoint into a tmp dir, rewrite the hardcoded
`/root/.openclaw` CONFIG_DIR path to a per-test tmp path, and stub
`openclaw` on PATH so the script's mid-way `openclaw config validate`
and trailing `exec openclaw gateway ...` resolve to no-ops. Pure JSON
shape check after — we deliberately do NOT install OpenClaw in tests
(out of scope for this phase).
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = REPO_ROOT / "infra" / "openclaw" / "entrypoint.sh"


def _prepare_sandbox(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """Copy entrypoint.sh into tmp_path with CONFIG_DIR rewritten.

    Returns ``(rewritten_script, env)`` where ``env`` is a clean env
    dict populated with the Slack defaults the script needs to render
    a non-empty Slack tenant block (so the surrounding JSON validates
    as a smoke check). Caller layers WhatsApp env vars on top.
    """
    config_dir = tmp_path / "openclaw-state"
    config_dir.mkdir()

    # Stub openclaw on PATH. `config validate` succeeds silently;
    # `gateway` is what the script `exec`s as its final line — we
    # short-circuit it to exit 0 so the script returns cleanly.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "openclaw"
    stub.write_text(
        "#!/bin/sh\n"
        "# Test stub: no-op for `config validate` and `gateway --port ...`.\n"
        "exit 0\n"
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    # Rewrite the hardcoded CONFIG_DIR to the tmp path. Sole hack here.
    src = ENTRYPOINT.read_text()
    rewritten = src.replace("CONFIG_DIR=/root/.openclaw", f"CONFIG_DIR={config_dir}")
    if rewritten == src:  # pragma: no cover — guards against silent drift in entrypoint.sh
        raise RuntimeError(
            "Could not find CONFIG_DIR=/root/.openclaw in entrypoint.sh — "
            "the test's path-rewrite hook is out of sync with the script."
        )
    script = tmp_path / "entrypoint.sh"
    script.write_text(rewritten)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)

    env = {
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        # Make the Slack tenant block non-empty so the surrounding JSON
        # parses (otherwise the heredoc emits an empty `accounts: { }`
        # which is still valid JSON but harder to assert against).
        "SLACK_APP_TOKEN_BASEWORM": "xapp-test-app-token",
        "SLACK_BOT_TOKEN_BASEWORM": "xoxb-test-bot-token",
    }
    return script, env


def _run_entrypoint(script: Path, env: dict[str, str]) -> dict:
    """Run the sandboxed entrypoint and return the parsed config.json."""
    result = subprocess.run(
        ["sh", str(script)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    config_dir = Path(env["PATH"].split(":")[0]).parent / "openclaw-state"
    config_file = config_dir / "openclaw.json"
    assert result.returncode == 0, (
        f"entrypoint exited {result.returncode}\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )
    assert config_file.exists(), f"config.json not written at {config_file}"
    raw = config_file.read_text()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:  # pragma: no cover — fails loudly with payload
        raise AssertionError(
            f"rendered config is not valid JSON: {exc}\n--- payload ---\n{raw}"
        ) from exc


@pytest.mark.integration
def test_whatsapp_block_omitted_when_disabled(tmp_path: Path) -> None:
    """Without WHATSAPP_ENABLED_BASEWORM=true, no whatsapp key is emitted.

    This is the byte-identical-with-pre-Phase-2 contract. Existing
    Slack-only deploys must not see any new key in their rendered
    config when they upgrade past this commit without opting in.
    """
    script, env = _prepare_sandbox(tmp_path)
    # WHATSAPP_ENABLED_BASEWORM intentionally unset.

    config = _run_entrypoint(script, env)

    assert "channels" in config
    assert "slack" in config["channels"]
    assert "whatsapp" not in config["channels"], (
        "whatsapp block leaked into config when WHATSAPP_ENABLED_BASEWORM was unset; "
        "this would break the byte-identical guarantee for Slack-only deploys."
    )


@pytest.mark.integration
def test_whatsapp_block_omitted_when_explicitly_false(tmp_path: Path) -> None:
    """Setting WHATSAPP_ENABLED_BASEWORM=false also omits the block.

    The render predicate is strictly `== "true"` so anything else —
    `false`, `0`, empty, garbage — leaves the block out. This is
    important because operators sometimes set env vars to `false`
    expecting it to be a master-off switch; we honor that intuition.
    """
    script, env = _prepare_sandbox(tmp_path)
    env["WHATSAPP_ENABLED_BASEWORM"] = "false"

    config = _run_entrypoint(script, env)

    assert "whatsapp" not in config["channels"]


@pytest.mark.integration
def test_whatsapp_block_renders_with_defaults(tmp_path: Path) -> None:
    """With only the master switch on, the block uses conservative defaults.

    `dmPolicy="pairing"` is the safest posture for a preview Baileys
    integration — no DMs admitted without explicit pairing. This is the
    same default declared in docker-compose.yml's openclaw service block.

    OpenClaw 2026.5.6 flattened the WhatsApp schema: no `accounts.<id>`
    nesting, no `transport` field, single account only with credentials
    at `credentials/whatsapp/default/`. The flat keys live directly
    under `channels.whatsapp`. See `infra/openclaw/entrypoint.sh:103-108`.
    """
    script, env = _prepare_sandbox(tmp_path)
    env["WHATSAPP_ENABLED_BASEWORM"] = "true"

    config = _run_entrypoint(script, env)

    wa = config["channels"]["whatsapp"]
    assert wa["enabled"] is True
    assert wa["selfChatMode"] is False
    assert wa["dmPolicy"] == "pairing"
    assert wa["allowFrom"] == []
    # OpenClaw 2026.5.6 dropped accounts.<id> nesting + transport field +
    # groupPolicy/groupAllowFrom from the WhatsApp block. Assert they're
    # absent so a regression to the old shape is caught loudly.
    assert "transport" not in wa
    assert "accounts" not in wa
    assert "groupPolicy" not in wa
    assert "groupAllowFrom" not in wa


@pytest.mark.integration
def test_whatsapp_block_renders_explicit_policies(tmp_path: Path) -> None:
    """All rendered policy env vars round-trip into the flat JSON shape.

    Verifies the comma-separated allowlist parsing in the entrypoint's
    awk-based JSON-array converter. Whitespace per element is trimmed
    so operators can write either ``"a,b"`` or ``"a, b"``.

    OpenClaw 2026.5.6 dropped `groupPolicy` / `groupAllowFrom` from the
    rendered schema (single-account model). The env vars are still read
    by `render_whatsapp_block` (vestigial) but no longer surface in the
    output. Setting them in this test verifies the script doesn't crash
    when operators continue to set the old names.
    """
    script, env = _prepare_sandbox(tmp_path)
    env.update({
        "WHATSAPP_ENABLED_BASEWORM": "true",
        "WHATSAPP_DM_POLICY_BASEWORM": "open",
        # Vestigial — read but no longer rendered. Set anyway so we catch
        # any regression that re-introduces a crash on the env-read path.
        "WHATSAPP_GROUP_POLICY_BASEWORM": "open",
        "WHATSAPP_ALLOW_FROM_BASEWORM": "5511999999999, 5511888888888",
        "WHATSAPP_GROUP_ALLOW_FROM_BASEWORM": "120363012345678901@g.us,120363098765432109@g.us",
    })

    config = _run_entrypoint(script, env)

    wa = config["channels"]["whatsapp"]
    assert wa["dmPolicy"] == "open"
    # Whitespace trimmed even though the operator wrote "5511..., 5511...".
    assert wa["allowFrom"] == ["5511999999999", "5511888888888"]
    # Group-* keys are not rendered post-2026.5.6.
    assert "groupPolicy" not in wa
    assert "groupAllowFrom" not in wa


@pytest.mark.integration
def test_slack_block_unchanged_when_whatsapp_disabled(tmp_path: Path) -> None:
    """The Slack tenant JSON shape is unchanged from pre-Phase-2.

    Acceptance gate from the plan: ``Slack rendering must continue to
    work unchanged (Slack tenant block JSON is byte-identical pre and
    post your changes when WhatsApp is disabled)``. We assert against
    the expected literal Slack tenant shape rather than comparing two
    rendered files because the surrounding JSON also depends on
    OPENCLAW_ADMIN_TOKEN and OLLAMA_API_KEY which are unrelated.
    """
    script, env = _prepare_sandbox(tmp_path)
    # WHATSAPP_ENABLED_BASEWORM intentionally unset.

    config = _run_entrypoint(script, env)

    slack = config["channels"]["slack"]
    assert slack == {
        "enabled": True,
        "mode": "socket",
        "dmPolicy": "pairing",
        "accounts": {
            "baseworm": {
                "appToken": "xapp-test-app-token",
                "botToken": "xoxb-test-bot-token",
                "groupPolicy": "open",
                "allowBots": True,
            }
        },
    }
