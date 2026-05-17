# > AUTHORED 2026-05-04: O-A2 Install dataclass contract test.
# >
# > Pins that wormbase-chat-presence exports a frozen dataclass `Install`
# > with the wire-side install fields lifecycle factories actually read
# > (id, platform, installer_person_id, bot_user_id). The dataclass mirrors
# > the projection_installs row shape (CLAUDE.md §4) for the read fields;
# > the full ledger-projected row carries more (oauth_grant, installed_at,
# > status, scopes), which stay projection-only.
# >
# > Replaces the SimpleNamespace duck-typing called out in factory.py:33.
"""Contract: chat-presence exports a typed Install dataclass."""
from __future__ import annotations

from dataclasses import is_dataclass
from uuid import uuid4

from wormbase_chat_presence import Install


def test_install_is_dataclass_with_required_fields() -> None:
    assert is_dataclass(Install)
    company = uuid4()
    inst = Install(id=company, platform="slack")
    assert inst.id == company
    assert inst.platform == "slack"


def test_install_optional_fields_default_to_none() -> None:
    inst = Install(id=uuid4(), platform="slack")
    assert inst.installer_person_id is None
    assert inst.bot_user_id is None


def test_install_is_frozen() -> None:
    inst = Install(id=uuid4(), platform="slack")
    try:
        inst.platform = "discord"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("Install must be frozen")
