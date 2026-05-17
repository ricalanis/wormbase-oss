"""Tests for OffsetState — file-backed crash-resume bookkeeping."""

from __future__ import annotations

from pathlib import Path

from wormbase_channel_adapter.state import OffsetState


class TestOffsetState:
    def test_missing_file_yields_zero_offsets(self, tmp_path: Path) -> None:
        s = OffsetState(tmp_path / "state.json")
        s.load()
        assert s.get("any-session") == 0

    def test_set_then_save_then_load_roundtrips(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        s = OffsetState(path)
        s.set("sess-A", 1234)
        s.set("sess-B", 5678)
        s.save()

        s2 = OffsetState(path)
        s2.load()
        assert s2.get("sess-A") == 1234
        assert s2.get("sess-B") == 5678
        assert s2.get("missing") == 0

    def test_save_is_atomic(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        s = OffsetState(path)
        s.set("x", 10)
        s.save()
        # No leftover .tmp files.
        leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".state.")]
        assert leftovers == []

    def test_corrupt_file_resets_offsets(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        path.write_text("not json{")
        s = OffsetState(path)
        s.load()
        assert s.items() == {}

    def test_wrong_version_resets_offsets(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        path.write_text('{"version": 999, "offsets": {"x": 1}}')
        s = OffsetState(path)
        s.load()
        assert s.items() == {}

    def test_save_creates_parent_dir(self, tmp_path: Path) -> None:
        nested = tmp_path / "deep" / "nested" / "state.json"
        s = OffsetState(nested)
        s.set("x", 1)
        s.save()
        assert nested.exists()
