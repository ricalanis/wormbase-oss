"""Per-file byte-offset state for crash-resume.

We persist a small JSON document that maps ``session_id`` (the JSONL
filename without extension) to the byte offset we have already consumed
through. On restart we open each file, ``seek`` to the saved offset, and
resume reading.

The file format is intentionally trivial::

    {"version": 1, "offsets": {"<session-uuid>": 1234, ...}}

If the file is missing or corrupt, we treat all sessions as fresh — but
that means ledger entries for already-seen lines may be re-emitted, so
the integration deployment MUST mount a writable state directory. The
default state path is ``./state.json`` relative to the working dir,
overridable via env var.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

_STATE_VERSION = 1


class OffsetState:
    """File-backed offset bookkeeping.

    Operations are intentionally synchronous + cheap: writes happen on
    every line we successfully process, but the JSON is small enough
    (one int per session) that the cost is negligible. Higher-volume
    deployments can batch writes or swap the backing store for sqlite
    behind the same interface.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)
        self._offsets: dict[str, int] = {}
        self._loaded = False

    def load(self) -> None:
        """Read the state file from disk; tolerant of missing/corrupt input."""
        if not self._path.exists():
            self._offsets = {}
            self._loaded = True
            return
        try:
            data = json.loads(self._path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            self._offsets = {}
            self._loaded = True
            return
        if not isinstance(data, dict) or data.get("version") != _STATE_VERSION:
            self._offsets = {}
            self._loaded = True
            return
        offsets = data.get("offsets", {})
        if not isinstance(offsets, dict):
            self._offsets = {}
        else:
            self._offsets = {str(k): int(v) for k, v in offsets.items() if isinstance(v, int)}
        self._loaded = True

    def get(self, session_id: str) -> int:
        if not self._loaded:
            self.load()
        return self._offsets.get(session_id, 0)

    def set(self, session_id: str, offset: int) -> None:
        if not self._loaded:
            self.load()
        self._offsets[session_id] = int(offset)

    def save(self) -> None:
        """Atomic write: tmp + os.replace so we never see a half-written file."""
        if not self._loaded:
            self.load()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        body = json.dumps(
            {"version": _STATE_VERSION, "offsets": self._offsets},
            sort_keys=True,
        )
        # Write to a sibling tmp file then rename.
        fd, tmp = tempfile.mkstemp(
            prefix=".state.",
            suffix=".json.tmp",
            dir=str(self._path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(body)
            os.replace(tmp, self._path)
        except Exception:
            # Best-effort cleanup; never raise from the rename path.
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def items(self) -> dict[str, int]:
        """Snapshot of the current offsets (caller-owned copy)."""
        if not self._loaded:
            self.load()
        return dict(self._offsets)
