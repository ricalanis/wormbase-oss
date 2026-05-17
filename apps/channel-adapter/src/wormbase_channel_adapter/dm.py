"""Resource-conversation DM helpers.

W5.A2 — when ``StatementToOwnerReactivity`` fires, it needs to send the
owner a DM carrying the statement plus the pinned resources. This module
provides the formatter + send wrapper. The send is delegated to whatever
``ChannelAdapter`` the worm has currently authenticated; we don't reach
for slack-bolt or other low-level SDKs here.

Why a thin helper, not a method on ``LedgerWriter``? Because the DM is
primarily an *outbound channel* concern (open the DM, post the message,
get back a ts) — the ledger entry is written by the registry's PEVR
cycle, not here. The split keeps responsibilities tight: this module
formats + sends; the registry records.

The module also exposes the Jinja template used for the body. Keeping it
in code (vs a separate template file) lets the body and the data shape
evolve together, with one ``test_template_renders`` to keep them in
lockstep.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger("wormbase_channel_adapter.dm")


# ---------------------------------------------------------------------------
# DM body template
# ---------------------------------------------------------------------------

# We use Jinja2 so the template is editable without escaping ladder hell.
# Render-once here, no inheritance / partials; the template is short.
_DM_TEMPLATE_SOURCE = """\
:pushpin: Heads up — saw a statement about *{{ topic.label }}* you might want to weigh in on:

> {{ statement_text }}
> — {{ speaker_label }} in {{ channel_label }}{% if statement_ts %}, {{ statement_ts }}{% endif %}

{% if has_resources %}*Pinned resources you own:*
{% if resources.kpis %}{% for k in resources.kpis %}• KPI: {{ k.label }}{% if k.unit %} ({{ k.unit }}){% endif %}
{% endfor %}{% endif %}{% if resources.sources %}{% for s in resources.sources %}• Source: {{ s.label }} ({{ s.status }})
{% endfor %}{% endif %}{% if resources.decisions %}{% for d in resources.decisions %}• Decision: {{ d.decision_at[:10] if d.decision_at else "" }} — {{ d.decision_text }}
{% endfor %}{% endif %}{% if resources.processes %}{% for p in resources.processes %}• Process: {{ p.process_name }}{% if p.step_count %} ({{ p.step_count }} steps){% endif %}
{% endfor %}{% endif %}{% if resources.data_products %}{% for d in resources.data_products %}• Data product: {{ d.name }} ({{ d.kind }})
{% endfor %}{% endif %}{% else %}_No pinned resources yet for this topic — the worm will surface them as the lake builds._
{% endif %}
Reply here to discuss; this thread is captured as a decision artifact in /trace.\
"""


def _get_template():
    """Lazy import so jinja isn't required at module-load time.

    This keeps the import graph clean for environments that import the
    channel-adapter package for type-hint / parsing purposes only.
    """
    from jinja2 import Environment, BaseLoader

    return Environment(
        loader=BaseLoader(),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    ).from_string(_DM_TEMPLATE_SOURCE)


def render_dm_body(
    *,
    topic: dict[str, Any],
    statement_text: str,
    speaker_label: str,
    channel_label: str,
    statement_ts: str | None,
    resources: dict[str, Any],
) -> str:
    """Render the resource-conversation DM body.

    Args:
        topic: ``{kind, id, label, ...}`` from topic_extractor.Topic.
        statement_text: the raw chat statement we're flagging.
        speaker_label: ``@bob`` or "Bob (slack)" — display name.
        channel_label: where the statement happened (``#revenue``,
            ``#dms`` etc.). Surfaced verbatim.
        statement_ts: ISO timestamp string of the statement, or None.
        resources: dict from ``ResourceBundle.to_payload()`` — five
            keys (kpis, sources, decisions, processes, data_products),
            each a list. Empty lists render as no entries.

    Returns the formatted message body (markdown / Slack-mrkdwn).
    """
    has_resources = any(
        resources.get(k) for k in (
            "kpis", "sources", "decisions", "processes", "data_products",
        )
    )
    return _get_template().render(
        topic=topic,
        statement_text=statement_text,
        speaker_label=speaker_label,
        channel_label=channel_label,
        statement_ts=statement_ts or "",
        resources=resources,
        has_resources=has_resources,
    ).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Send protocol — what the helper expects from the channel adapter
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DMRef:
    """Result of a send_resource_conversation_dm call.

    Mirrors :class:`MessageRef` from the channel-adapters package without
    forcing this module to depend on that package's types — wormbase
    callers can map the platform/ts back to whatever they need.
    """

    platform: str
    platform_channel_id: str
    platform_message_id: str


@runtime_checkable
class DMSender(Protocol):
    """Minimum surface required from a channel adapter to send a DM.

    The :class:`ChannelAdapter` Protocol in
    ``packages/channel-adapters`` provides a richer set of methods. Here
    we only need ``open_dm`` (to resolve a Person → DM channel ref) and
    ``send`` (to post the body). Two methods so tests can fake the
    surface without implementing the entire ChannelAdapter Protocol.
    """

    async def open_dm(self, platform_user_id: str) -> str:
        """Resolve / open a DM channel for the given platform_user_id.

        Returns the platform-native channel id (e.g. Slack ``D012345``).
        """
        ...

    async def send_dm(
        self,
        platform_channel_id: str,
        text: str,
        *,
        blocks: list[dict[str, Any]] | None = None,
    ) -> str:
        """Post ``text`` to a DM channel; return the platform_message_id."""
        ...


# ---------------------------------------------------------------------------
# Send entrypoint
# ---------------------------------------------------------------------------


async def send_resource_conversation_dm(
    sender: DMSender,
    *,
    owner_platform_id: str,
    topic: dict[str, Any],
    statement: dict[str, Any],
    resources: dict[str, Any],
) -> DMRef:
    """Format + send the resource-conversation DM. Returns ``DMRef``.

    Args:
        sender: a :class:`DMSender` (real ChannelAdapter wrapper or test
            mock).
        owner_platform_id: the Person's platform_user_id (e.g. Slack U-id).
        topic: ``Topic.to_dict()``-shaped dict.
        statement: ``{text, speaker_label, channel_label, ts}`` describing
            the original statement.
        resources: ``ResourceBundle.to_payload()``-shaped dict.

    Caller is responsible for writing the ledger entry that records the
    PEVR cycle — this helper only handles the wire-side send so the
    ledger write can carry the resulting platform_message_id +
    platform_channel_id as receipts.

    Failure modes: ``open_dm`` and ``send_dm`` may raise; we propagate
    so the registry's dispatch loop catches and logs (the per-fire
    error path in ``ReactivityRegistry.dispatch``).
    """
    body = render_dm_body(
        topic=topic,
        statement_text=str(statement.get("text") or ""),
        speaker_label=str(statement.get("speaker_label") or ""),
        channel_label=str(statement.get("channel_label") or ""),
        statement_ts=statement.get("ts"),
        resources=resources,
    )
    channel_id = await sender.open_dm(owner_platform_id)
    message_id = await sender.send_dm(channel_id, body)
    platform = ""
    if hasattr(sender, "platform"):
        platform = str(getattr(sender, "platform") or "")
    return DMRef(
        platform=platform or "unknown",
        platform_channel_id=channel_id,
        platform_message_id=message_id,
    )


__all__ = [
    "DMRef",
    "DMSender",
    "render_dm_body",
    "send_resource_conversation_dm",
]
