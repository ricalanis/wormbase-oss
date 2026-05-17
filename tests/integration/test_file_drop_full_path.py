"""L5 integration: a real files_upload_v2 must produce emit_file_received.

Two layers of coverage:

1. **In-process verification** — drives the channel-adapter's
   ``GlobalLogCapture.on_channel_admit`` directly with a stub Slack
   client that returns a file_share message owned by our own bot
   (the sim-harness path: bot uploads on behalf of personas because
   Slack does not allow per-call user attribution on uploads).
   This locks in the C1 fix at the production code path.

2. **Live-wire smoke** — executes a real `files_upload_v2` call against
   a Slack workspace and polls the ledger for `emit_file_received`.
   Skipped when Docker compose stack is not running (env var
   ``WORMBASE_INTEGRATION_LIVE_SLACK=1`` enables it). This is the gate
   the demo runs through.

The first layer protects against regressions of the C1 root cause; the
second layer is the end-to-end wire-truth check.
"""

from __future__ import annotations

import os
import time
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from wormbase_ledger import InMemoryLedger
from wormbase_channel_adapter.service import GlobalLogCapture
from wormbase_channel_adapter.tenant import tenant_to_company_uuid


pytestmark = pytest.mark.asyncio


def _stub_slack_with_file_message(
    *,
    bot_id: str = "B0SELF",
    bot_user_id: str = "U0BOTUSER",
    msg_user: str = "U0BOTUSER",
    msg_bot_id: str | None = "B0SELF",
    file_id: str = "F0FILE001",
    ts: str = "1777152782.000099",
) -> AsyncMock:
    """SlackClient stub that returns a file_share msg attributed to the bot.

    This mirrors the Slack response shape sim-harness's `files_upload_v2`
    produces: the bot is the file owner because the bot token is the
    only path through which sim can attribute uploads.
    """
    stub = AsyncMock()
    stub.fetch_latest_message = AsyncMock(return_value={
        "ts": ts,
        "subtype": "file_share",
        "user": msg_user,
        "bot_id": msg_bot_id,
        "text": "sales-q3.csv",
        "files": [
            {
                "id": file_id,
                "name": "sales-q3.csv",
                "mimetype": "text/csv",
                "size": 4096,
                "url_private": f"https://files.example.com/{file_id}.csv",
            },
        ],
    })
    stub.bot_id = bot_id
    stub.bot_user_id = bot_user_id
    return stub


@pytest.fixture
def company_id() -> UUID:
    return tenant_to_company_uuid("baseworm")


async def test_files_upload_by_bot_emits_file_received(
    company_id: UUID,
) -> None:
    """C1 fix: a sim-harness file upload (bot-owned) must produce an
    ``emit_file_received`` ledger entry.

    Pre-fix: the chat-level echo guard suppressed the entire fan-out,
    including file_received. Post-fix: file_received fires regardless
    of who uploaded the file (chat-level echo is still suppressed for
    the bot's own outbound messages).
    """
    ledger = InMemoryLedger()
    slack = _stub_slack_with_file_message()
    capture = GlobalLogCapture(ledger=ledger, company_id=company_id, slack=slack)

    await capture.on_channel_admit("C0DROP")

    rows = await ledger.fetch(company_id)
    file_rows = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "channel_adapter.emit_file_received"
    ]
    assert len(file_rows) == 1, (
        f"expected 1 emit_file_received entry; got {len(file_rows)}. "
        f"Rows: {[(r['kind'], r['payload'].get('tool')) for r in rows]}"
    )
    args = file_rows[0]["payload"]["args"]
    assert args["slack_file_id"] == "F0FILE001"
    assert args["file_name"] == "sales-q3.csv"
    assert args["mimetype"] == "text/csv"


async def test_files_upload_by_real_user_emits_file_received(
    company_id: UUID,
) -> None:
    """Sanity: a real user uploading a file (no bot_id on the msg) also
    fires file_received plus a chat_received for the caption."""
    ledger = InMemoryLedger()
    slack = _stub_slack_with_file_message(
        bot_id="B0SELF",
        bot_user_id="U0BOTUSER",
        msg_user="U0HUMAN",
        msg_bot_id=None,
        file_id="F0HUMAN001",
    )
    capture = GlobalLogCapture(ledger=ledger, company_id=company_id, slack=slack)

    await capture.on_channel_admit("C0DROP")

    rows = await ledger.fetch(company_id)
    chat_rows = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "channel_adapter.emit_chat_received"
    ]
    file_rows = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "channel_adapter.emit_file_received"
    ]
    assert len(chat_rows) == 1
    assert len(file_rows) == 1


# ---------------------------------------------------------------------------
# Live-wire layer: real Slack + docker-compose. Gated behind an env flag so
# the contract layer above keeps protecting CI when the wire isn't up.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("WORMBASE_INTEGRATION_LIVE_SLACK") != "1",
    reason=(
        "live Slack integration off by default. "
        "Set WORMBASE_INTEGRATION_LIVE_SLACK=1 with a running compose "
        "stack and SLACK_BOT_TOKEN_BASEWORM in env to enable."
    ),
)
async def test_live_files_upload_lands_in_ledger() -> None:
    """End-to-end on the real wire. See module docstring."""
    bot_token = os.environ.get("SLACK_BOT_TOKEN_BASEWORM")
    channel_id = os.environ.get("WORMBASE_INTEGRATION_TEST_CHANNEL", "C0B06MCSLQ1")
    dsn = os.environ.get(
        "WORMBASE_LEDGER_DSN",
        "postgresql+asyncpg://wormbase:wormbase@localhost:5432/wormbase",
    )
    if not bot_token:
        pytest.skip("SLACK_BOT_TOKEN_BASEWORM not set")

    from pathlib import Path

    from slack_sdk.web.async_client import AsyncWebClient
    from wormbase_ledger import Ledger

    csv_path = Path(__file__).resolve().parents[2] / "apps/sim-harness/fixtures/sales-q3.csv"
    if not csv_path.is_file():
        pytest.skip(f"fixture missing: {csv_path}")

    client = AsyncWebClient(token=bot_token)
    company_id = tenant_to_company_uuid("baseworm")
    ledger = Ledger(dsn)
    try:
        resp = await client.files_upload_v2(
            channel=channel_id,
            file=str(csv_path),
            title="sales-q3.csv",
        )
        data: dict[str, Any] = getattr(resp, "data", resp)  # type: ignore[assignment]
        assert data.get("ok") is True, f"upload not ok: {data!r}"
        file_id = data["file"]["id"]
        deadline = time.monotonic() + 10.0
        found = False
        while time.monotonic() < deadline:
            rows = await ledger.fetch(company_id)
            for r in rows[-50:]:
                if (
                    r["kind"] == "execute"
                    and r["payload"].get("tool") == "channel_adapter.emit_file_received"
                    and r["payload"]["args"].get("slack_file_id") == file_id
                ):
                    found = True
                    break
            if found:
                break
            time.sleep(0.5)
        assert found, (
            f"emit_file_received for file_id={file_id} did not land "
            f"in the ledger within 10s (live-wire C1 regression)"
        )
    finally:
        await ledger.dispose()
