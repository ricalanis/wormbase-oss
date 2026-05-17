"""make_chat_reactivities returns the four-instance list."""
from __future__ import annotations

from uuid import uuid4

from wormbase_chat_presence.factory import make_chat_reactivities
from wormbase_reactivities.protocol import Reactivity


def test_make_chat_reactivities_returns_four() -> None:
    install = type("Install", (), {"id": uuid4(), "platform": "slack"})()
    reactivities = make_chat_reactivities(install=install, mention_handle="@worm")

    assert len(reactivities) == 4
    ids = {r.id for r in reactivities}
    assert ids == {
        "chat_received",
        "mention_response",
        "interjection_budget",
        "source_mentioned",
    }
    for r in reactivities:
        assert isinstance(r, Reactivity)
