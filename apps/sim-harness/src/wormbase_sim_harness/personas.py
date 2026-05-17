"""Persona registry — Pydantic models + YAML loader.

A persona is a (display_name, icon_emoji, role, voice_hint) bundle keyed
by a short id (e.g. ``alice``). Slack's ``chat.postMessage`` accepts
``username`` + ``icon_emoji`` overrides per call when the bot's app has
the ``chat:write.customize`` scope, so a single Slack app can post as
many personas without provisioning multiple bot users.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

# Slack icon_emoji wants ``:colon-form:`` (bare emoji name in colons).
# We don't probe the workspace; we only validate the syntactic shape.
_EMOJI_RE = re.compile(r"^:[a-z0-9_+\-]+:$")


class Persona(BaseModel):
    """A scripted persona that the harness can post as."""

    id: str = Field(..., min_length=1)
    display_name: str = Field(..., min_length=1)
    icon_emoji: str = Field(..., min_length=3)
    role: str = Field(..., min_length=1)
    voice_hint: str = Field(default="")

    @field_validator("icon_emoji")
    @classmethod
    def _check_emoji(cls, v: str) -> str:
        if not _EMOJI_RE.match(v):
            raise ValueError(
                f"icon_emoji must be in colon form (e.g. ':woman:'); got {v!r}"
            )
        return v


class PersonaRegistry(BaseModel):
    """A mapping of persona id -> Persona, with helpers."""

    personas: dict[str, Persona]

    @classmethod
    def from_yaml(cls, path: str | Path) -> PersonaRegistry:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or "personas" not in raw:
            raise ValueError(
                "personas.yml must be a mapping with a top-level 'personas' key"
            )
        block = raw["personas"]
        if not isinstance(block, dict) or not block:
            raise ValueError("'personas' block must be a non-empty mapping")

        built: dict[str, Persona] = {}
        for pid, body in block.items():
            if not isinstance(body, dict):
                raise ValueError(f"persona '{pid}' must be a mapping")
            built[pid] = Persona.model_validate({"id": pid, **body})
        return cls(personas=built)

    def __iter__(self) -> Any:
        return iter(self.personas.values())

    def __len__(self) -> int:
        return len(self.personas)

    def get(self, pid: str) -> Persona:
        try:
            return self.personas[pid]
        except KeyError as exc:
            raise KeyError(f"unknown persona id: {pid!r}") from exc

    def has(self, pid: str) -> bool:
        return pid in self.personas


__all__ = ["Persona", "PersonaRegistry"]
