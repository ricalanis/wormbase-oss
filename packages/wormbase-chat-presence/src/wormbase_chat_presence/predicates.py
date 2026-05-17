"""Chat-worm-private W5a-style predicates.

`MentionsWorm` matches when the entry indicates the worm has been mentioned.
Used by MentionResponseReactivity. Two paths:

* Slack / Discord / Teams / default: case-insensitive substring search of
  the configured ``handle`` (e.g. ``"@worm"``) in the message text. The
  Slack adapter renders the bot's display-name that contains the handle,
  so the substring check is the canonical Slack mention test.
* WhatsApp: WhatsApp does NOT carry a stable user handle; mentions live
  in Baileys' ``message.extendedTextMessage.contextInfo.mentionedJid``
  array (a list of ``<phone>@s.whatsapp.net`` jids). The bot's identity
  on WhatsApp is its own phone-derived jid. ``MentionsWorm`` resolves
  the bot's phone via :func:`resolve_whatsapp_bot_phone`, which scans
  in precedence order tenant-suffix → company-id-suffix → no-suffix.
  See that function for the full contract.

`DataKeywordMatch` matches when the entry's text contains a known data-source
keyword. Used by SourceMentionedReactivity. Keywords are mirrored verbatim
from wormbase_core.relevance._DATA_SOURCE_KEYWORDS so the migration from
the legacy gate to the new Reactivity is byte-equivalent for chat events.

Both predicates implement `ReactivityPredicate` Protocol structurally —
they do NOT inherit from wormbase_reactivities.predicates._PredicateBase
(private). Composition uses the explicit And()/Or() classes from
wormbase_reactivities.predicates rather than operator overloading.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from wormbase_reactivities.protocol import ReactivityContext


# Source-of-truth lives in wormbase_chat_presence.relevance after Block C1.
# Re-exported here so existing imports (`from wormbase_chat_presence.predicates
# import _DATA_SOURCE_KEYWORDS`) continue to work without code changes.
from wormbase_chat_presence.relevance import _DATA_SOURCE_KEYWORDS


# WhatsApp jid suffixes — Baileys/WhatsApp Web canonical:
#   ``@s.whatsapp.net`` is a 1:1 (DM) jid
#   ``@g.us``           is a group jid
# Channel ids carrying either suffix originate on WhatsApp; everything
# else (Slack ``C0AV...``, Discord, Teams, etc.) routes through the
# default text-substring path.
_WA_JID_SUFFIXES = ("@s.whatsapp.net", "@g.us")


def _entry_chat_args(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Return the chat-event args dict, or None if entry isn't a chat event.

    Centralized so both the text path and the WhatsApp path share the
    same chat-event recognition rules.
    """
    if entry.get("kind") != "execute":
        return None
    payload = entry.get("payload") or {}
    tool = payload.get("tool")
    if tool not in (
        "emit_chat_received",
        "channel_adapter.emit_chat_received",
    ):
        return None
    args = payload.get("args")
    if not isinstance(args, dict):
        return None
    return args


def _entry_text(entry: dict[str, Any]) -> str:
    """Pull message text out of a chat-shaped entry. Returns "" on miss."""
    args = _entry_chat_args(entry)
    if args is None:
        return ""
    return str(args.get("text") or "")


def _is_whatsapp_args(args: dict[str, Any]) -> bool:
    """Infer platform=='whatsapp' from a chat_received args dict.

    The canonical ChatReceivedPayload schema does NOT carry a ``platform``
    field, so we infer from ``channel_id`` shape. WhatsApp jids always
    end in ``@s.whatsapp.net`` (DM) or ``@g.us`` (group); Slack channel
    ids never do. If a future writer surfaces ``args["platform"]``
    explicitly, that takes precedence.
    """
    explicit = args.get("platform")
    if isinstance(explicit, str):
        return explicit == "whatsapp"
    channel_id = args.get("channel_id")
    if not isinstance(channel_id, str):
        return False
    return channel_id.endswith(_WA_JID_SUFFIXES)


def resolve_whatsapp_bot_phone(
    *,
    tenant_id: str | None = None,
    company_id: str | UUID | None = None,
) -> str | None:
    """Resolve the WhatsApp bot phone number.

    Single resolver contract used by both ``MentionsWorm`` (chat-presence)
    and ``WhatsAppChannelAdapter`` (channel-adapters), pinned to byte-
    equivalent behavior by ``tests/contract/test_whatsapp_bot_phone_env_resolver.py``.
    Per CLAUDE.md §1.5 rule 3, the two packages may not import from each
    other; this helper is duplicated module-locally in both, with the
    contract test enforcing equivalence.

    Precedence (returns first non-empty match, stripping a leading ``+``):

    1. ``WORMBASE_WHATSAPP_BOT_PHONE_<TENANT_UPPER>`` — when ``tenant_id``
       is given. Tenant slug is upper-cased verbatim (no other transform).
    2. ``WORMBASE_WHATSAPP_BOT_PHONE_<COMPANY_ID_UPPER>`` — when
       ``company_id`` is given. UUID is stringified and upper-cased,
       PRESERVING dashes (matches the existing B1 convention pinned by
       ``test_whatsapp_mention_e2e.py``; do not change without coordinated
       env-var rotation).
    3. ``WORMBASE_WHATSAPP_BOT_PHONE`` — single-tenant fallback (no suffix).

    Returns ``None`` if all three are unset OR if the first non-empty
    match is whitespace-only after stripping ``+``. Callers treat ``None``
    as "we don't know who we are, so no mention can match" / "fall back
    to a sentinel bucket key".

    Single-tenant deployments set just (3). Multi-tenant deployments set
    (1) per-tenant or (2) per-company-id, whichever the operator prefers.
    Setting both (1) and (2) is supported (precedence picks (1) first)
    and intentionally back-compatible with deployments that already set
    both today.
    """
    if tenant_id:
        tenant_key = str(tenant_id).upper()
        scoped = os.environ.get(
            f"WORMBASE_WHATSAPP_BOT_PHONE_{tenant_key}",
        )
        normalized = _normalize_phone(scoped)
        if normalized is not None:
            return normalized
    if company_id is not None:
        company_key = str(company_id).upper()
        scoped = os.environ.get(
            f"WORMBASE_WHATSAPP_BOT_PHONE_{company_key}",
        )
        normalized = _normalize_phone(scoped)
        if normalized is not None:
            return normalized
    fallback = os.environ.get("WORMBASE_WHATSAPP_BOT_PHONE")
    return _normalize_phone(fallback)


def _normalize_phone(raw: str | None) -> str | None:
    """Strip surrounding whitespace + leading '+'; treat empties as None.

    Order matters: whitespace must be stripped FIRST so values like
    ``"   +  "`` (whitespace-padded plus sign with no digits) collapse
    to the empty string and are treated as unset, not as a literal "+"
    phone number. Test pin:
    ``tests/contract/test_whatsapp_bot_phone_env_resolver.py::test_whitespace_only_value_treated_as_unset``.
    """
    if not raw:
        return None
    cleaned = raw.strip().lstrip("+").strip()
    if not cleaned:
        return None
    return cleaned


def _resolve_bot_phone(context: ReactivityContext) -> str | None:
    """Look up the WhatsApp bot phone from env, scoped by ReactivityContext.

    Thin wrapper over :func:`resolve_whatsapp_bot_phone` that pulls
    ``company_id`` off the context. The chat-presence predicate path
    does not have a tenant-slug in scope at match-time, only the
    company UUID, so only paths (2) and (3) of the precedence chain
    activate here in practice.
    """
    company_id = getattr(context, "company_id", None)
    return resolve_whatsapp_bot_phone(company_id=company_id)


def _extract_mentioned_jids(args: dict[str, Any]) -> list[str]:
    """Pull the mentionedJid array out of a chat_received args dict.

    Tries two paths in order:

    1. ``args["mentioned_jids"]`` — a forward-compatible normalized key.
       The current ChatReceivedPayload schema does NOT carry this field
       (writer drops the raw Baileys payload at the channel-adapter
       boundary), so this path activates only once a follow-on
       workstream extends ChatReceivedPayload to plumb mentions through.
    2. ``args["payload"]["message"]["extendedTextMessage"]["contextInfo"]["mentionedJid"]``
       — the canonical Baileys nesting. Same caveat: requires the writer
       to preserve ``InfraEvent.payload`` into args, which is also a
       follow-on. Until then this path returns ``[]`` for live ledger
       entries; tests exercise it by seeding ``args.payload`` directly.

    Both reads are defensive: any non-list, missing key, or non-dict
    intermediate returns ``[]``.
    """
    direct = args.get("mentioned_jids")
    if isinstance(direct, list):
        return [j for j in direct if isinstance(j, str)]

    payload = args.get("payload")
    if not isinstance(payload, dict):
        return []
    message = payload.get("message")
    if not isinstance(message, dict):
        return []
    ext = message.get("extendedTextMessage")
    if not isinstance(ext, dict):
        return []
    ctx_info = ext.get("contextInfo")
    if not isinstance(ctx_info, dict):
        return []
    jids = ctx_info.get("mentionedJid")
    if not isinstance(jids, list):
        return []
    return [j for j in jids if isinstance(j, str)]


@dataclass(frozen=True)
class MentionsWorm:
    """Match when the entry indicates the worm has been mentioned.

    Behavior branches by inferred platform:

    * Slack (default) — case-insensitive substring of ``handle`` in the
      message text. Mirrors the legacy
      ``RulesBasedRelevanceGate._mention_handle in text.lower()`` check.
    * WhatsApp — read mentionedJid from the chat_received args (either
      a normalized ``mentioned_jids`` list or the canonical Baileys
      nesting under ``payload.message.extendedTextMessage.contextInfo``)
      and match against the bot's phone-based jid resolved via
      :func:`resolve_whatsapp_bot_phone` (precedence: tenant-suffix →
      company-id-suffix → no-suffix fallback). If the env is unset for
      a WhatsApp event, the predicate returns False — we cannot decide
      whether a jid means "us" without knowing our own phone.

    Frozen + hashable so existing And()/Or() composition (which relies
    on dataclass-generated __hash__/__eq__) keeps working unchanged.
    """

    handle: str = "@worm"

    async def match(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> bool:
        args = _entry_chat_args(entry)
        if args is None:
            return False
        if _is_whatsapp_args(args):
            return self._match_whatsapp(args, context)
        return self._match_default(args)

    def _match_default(self, args: dict[str, Any]) -> bool:
        text = str(args.get("text") or "")
        if not text or not self.handle:
            return False
        return self.handle.lower() in text.lower()

    def _match_whatsapp(
        self, args: dict[str, Any], context: ReactivityContext,
    ) -> bool:
        bot_phone = _resolve_bot_phone(context)
        if not bot_phone:
            return False
        # ``resolve_whatsapp_bot_phone`` already strips leading '+';
        # the explicit ``lstrip('+')`` here is redundant but defensive
        # (any future caller wiring a non-normalized value still works).
        bot_jid = f"{bot_phone.lstrip('+')}@s.whatsapp.net"
        return bot_jid in _extract_mentioned_jids(args)


@dataclass
class DataKeywordMatch:
    """Match when the entry's text contains a known data-source keyword.

    Keywords are case-insensitive substring matched. Keep aligned with
    `_DATA_SOURCE_KEYWORDS` in `wormbase_chat_presence.relevance` (Block C).
    The match returns True on the first hit; the hit keyword is recoverable
    via the package-level `match_keyword(text)` helper if needed for
    downstream args.
    """

    async def match(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> bool:
        text = _entry_text(entry).lower()
        if not text:
            return False
        return any(kw in text for kw in _DATA_SOURCE_KEYWORDS)


def match_keyword(text: str) -> str | None:
    """Return the first matched data-source keyword in `text`, lower-cased.

    Mirror of wormbase_core.relevance._detect_data_source_mention. Used by
    SourceMentionedReactivity to pass the keyword as an arg into the lifted
    flow (preserves the existing keyword → archetype mapping in flows.py).
    """
    if not text:
        return None
    lower = text.lower()
    for kw in _DATA_SOURCE_KEYWORDS:
        if kw in lower:
            return kw
    return None


__all__ = [
    "DataKeywordMatch",
    "MentionsWorm",
    "match_keyword",
    "resolve_whatsapp_bot_phone",
]
