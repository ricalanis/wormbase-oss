"""Filesystem-backed audio storage for the demo build.

For the Thursday demo we persist audio blobs as files under a configurable
directory (``/tmp/voice-audio`` by default). The ``audio_ref`` written into
the ledger is the absolute filesystem path. In production this is swapped
for S3 or MinIO with KMS encryption — see the README's migration plan.

The module is intentionally tiny: ledger entries reference the path, and
``write_blob`` is best-effort (a storage failure must not break a turn).
The voice-agent's audit layer always writes the ledger entry; the
``audio_ref`` is set to ``None`` when storage fails so the chain stays
intact (per design-doc §8 risk #3).
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_AUDIO_DIR = Path(os.environ.get("WORMBASE_VOICE_AUDIO_DIR", "/tmp/voice-audio"))


@dataclass(frozen=True)
class StoredAudio:
    """Result of ``write_blob`` — either a real path + hash, or ``None``."""

    path: str
    sha256: str
    size_bytes: int


class AudioStore:
    """Filesystem-backed blob store.

    Each blob lands at ``<root>/<turn_id>.<ext>``; ``turn_id`` is provided by
    the caller (typically the ledger ref_id or the ElevenLabs conversation
    turn id). The store creates ``<root>`` lazily.
    """

    def __init__(self, root: Path | str | None = None) -> None:
        self._root = Path(root) if root is not None else DEFAULT_AUDIO_DIR

    @property
    def root(self) -> Path:
        return self._root

    def _ensure_root(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)

    def path_for(self, turn_id: str, ext: str = "wav") -> Path:
        ext = ext.lstrip(".").lower() or "wav"
        # Sanitize turn_id — refuse path separators so we never escape root.
        safe = turn_id.replace("/", "_").replace("\\", "_")
        return self._root / f"{safe}.{ext}"

    def write_blob(
        self, turn_id: str, blob: bytes, *, ext: str = "wav"
    ) -> StoredAudio:
        """Write ``blob`` under ``turn_id`` and return a ``StoredAudio`` record.

        Raises if the write fails — callers in :mod:`audit` are expected to
        wrap this in a best-effort try/except so a storage outage doesn't
        500 the ElevenLabs webhook (see design-doc §8 risk #3).
        """
        self._ensure_root()
        target = self.path_for(turn_id, ext)
        target.write_bytes(blob)
        digest = hashlib.sha256(blob).hexdigest()
        return StoredAudio(path=str(target), sha256=digest, size_bytes=len(blob))


__all__ = ["AudioStore", "DEFAULT_AUDIO_DIR", "StoredAudio"]
