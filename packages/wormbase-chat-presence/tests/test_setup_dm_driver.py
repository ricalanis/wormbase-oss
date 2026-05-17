"""SetupDmDriver tests (Block G3 / D4 spike s C6 split).

Covers the chat-worm-side primitives lifted from
apps/worm-core/src/wormbase_core/setup_conversation.py:1-241:

  - YAML script loader parses each pack file correctly.
  - Answer parsing (one_of / free_text).
  - Mention parser (Slack-bracket, bare @, skip).

Orchestration-loop tests (SetupConversationLoop) stay in worm-core's
tests/test_setup_conversation.py because they require the
write_actions integration that lives in worm-core.
"""

from __future__ import annotations

from wormbase_chat_presence.setup_dm_driver import (
    SetupStep,
    load_script_for_pack,
    parse_answer,
    parse_mentions,
)


def test_default_script_dir_resolves_via_importlib_resources() -> None:
    """O-B4: load_script_for_pack must resolve YAMLs via importlib.resources,
    not via fragile parent-traversal relative to setup_dm_driver.__file__.

    No script_dir kwarg — must use the package's bundled data.
    """
    script = load_script_for_pack("saas")
    assert script.domain_pack == "saas"
    assert len(script.steps) > 0


# ---------------------------------------------------------------------------
# YAML loader
# ---------------------------------------------------------------------------


def test_load_saas_default_has_5_steps() -> None:
    script = load_script_for_pack("saas")
    assert script.domain_pack == "saas"
    assert len(script.steps) == 5
    ids = [s.id for s in script.steps]
    assert ids == [
        "domain_pack",
        "classification_default",
        "invite_admins",
        "first_kpi",
        "done",
    ]


def test_load_marketplace_has_5_steps() -> None:
    script = load_script_for_pack("marketplace")
    assert script.domain_pack == "marketplace"
    assert len(script.steps) == 5


def test_load_fintech_has_5_steps_and_classification_options() -> None:
    script = load_script_for_pack("fintech")
    assert script.domain_pack == "fintech"
    classification = script.by_id("classification_default")
    assert classification is not None
    assert classification.options == ("confidential", "regulated")


def test_load_unknown_pack_falls_back_to_saas() -> None:
    script = load_script_for_pack("nonexistent_pack")
    assert script.domain_pack == "saas"


def test_script_navigation_chains_through_to_done() -> None:
    script = load_script_for_pack("saas")
    cur: SetupStep | None = script.first()
    visited: list[str] = []
    while cur is not None:
        visited.append(cur.id)
        cur = script.next_after(cur.id) if cur.next else None
    assert visited == [
        "domain_pack",
        "classification_default",
        "invite_admins",
        "first_kpi",
        "done",
    ]


# ---------------------------------------------------------------------------
# Answer parsing
# ---------------------------------------------------------------------------


def test_parse_answer_one_of_accepts_canonical() -> None:
    step = SetupStep(
        id="x",
        bot_says="?",
        on_answer="noop",
        expects="one_of",
        options=("saas", "marketplace"),
    )
    assert parse_answer(step, "saas").ok
    assert parse_answer(step, "saas").value == "saas"


def test_parse_answer_one_of_is_case_insensitive() -> None:
    step = SetupStep(
        id="x",
        bot_says="?",
        on_answer="noop",
        expects="one_of",
        options=("saas", "marketplace"),
    )
    assert parse_answer(step, "SaaS").ok


def test_parse_answer_one_of_rejects_unknown() -> None:
    step = SetupStep(
        id="x",
        bot_says="?",
        on_answer="noop",
        expects="one_of",
        options=("saas", "marketplace"),
    )
    p = parse_answer(step, "consumer")
    assert not p.ok
    assert "saas" in (p.error or "")


def test_parse_answer_free_text_strips_whitespace() -> None:
    step = SetupStep(
        id="x", bot_says="?", on_answer="noop", expects="free_text",
    )
    p = parse_answer(step, "  Q3 net revenue  ")
    assert p.ok
    assert p.value == "Q3 net revenue"


def test_parse_answer_free_text_rejects_empty() -> None:
    step = SetupStep(
        id="x", bot_says="?", on_answer="noop", expects="free_text",
    )
    p = parse_answer(step, "   ")
    assert not p.ok


def test_parse_mentions_parses_slack_brackets() -> None:
    text = "<@UBOB> and <@UCAROL> please"
    assert parse_mentions(text) == ["UBOB", "UCAROL"]


def test_parse_mentions_parses_at_handle() -> None:
    assert parse_mentions("@bob @carol") == ["bob", "carol"]


def test_parse_mentions_skip() -> None:
    assert parse_mentions("skip") == []
    assert parse_mentions("") == []
