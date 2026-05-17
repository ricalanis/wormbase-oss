"""Scenario YAML loader.

A scenario is a sequence of beats. Each beat declares ``at`` (seconds
since run start) plus one of:

* ``say`` — persona posts text in the channel.
* ``drop`` — persona uploads a file (with optional caption).
* ``dm``  — persona DMs the worm directly (E1: install-arc beat 4b).
* ``wait_for`` — pause the engine until a ledger entry with
  ``payload.tool == <tool_name>`` lands (E1: install-arc beats 1, 2,
  6, 7). Optional ``count`` (default 1) and ``timeout_s`` fields.

``improv: true`` asks the LLM to riff on the seed line in-character;
otherwise the literal ``say`` is used verbatim.
"""

from __future__ import annotations

from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, Field, model_validator

from wormbase_sim_harness.personas import PersonaRegistry


class FileDrop(BaseModel):
    """A file to upload, with an optional caption posted as a follow-up."""

    file: str = Field(..., min_length=1)
    caption: str | None = None


class DirectMessage(BaseModel):
    """A direct message from a persona to the worm.

    ``to`` is the readable handle (e.g. ``"@WormBase"``) that the engine
    resolves to a real DM channel via ``conversations.open`` between the
    persona's bot account and the worm's bot user. ``text`` is the
    literal message body — improv is not applied to DMs because the
    install-arc beats need verbatim credentials.
    """

    to: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)


class WaitFor(BaseModel):
    """Pause the engine until a ledger entry with a given tool lands.

    ``tool`` matches ``payload.tool`` on ``execute`` rows in the ledger.
    ``count`` is the number of matching rows the beat is satisfied by
    (default 1; e.g. ``emit_domain_registered`` ×4 in beat 2).
    ``timeout_s`` bounds the wait (default 30s); on timeout the beat
    raises so the scenario fails loudly rather than silently hanging.

    The ``tool`` field accepts either a literal payload-tool string
    (``emit_install_completed``) or a synthetic dashboard-event prefix
    (``dashboard:tenant_switched``). Dashboard events are intentionally
    not real ledger entries — they're matched against rows whose
    payload tool is ``dashboard.<event>`` so a future dashboard hook
    can write them with no scenario change.
    """

    tool: str = Field(..., min_length=1)
    count: int = Field(default=1, ge=1)
    timeout_s: float = Field(default=30.0, gt=0)


class Beat(BaseModel):
    """One scripted action."""

    at: float = Field(..., ge=0)
    persona: str | None = None
    say: str | None = None
    drop: FileDrop | None = None
    dm: DirectMessage | None = None
    wait_for: WaitFor | str | None = None
    timeout_s: float | None = None
    count: int | None = None
    improv: bool = False

    @model_validator(mode="after")
    def _normalize_and_check(self) -> Self:
        # Coerce a bare string ``wait_for: emit_x`` into a WaitFor model
        # and fold the sibling ``timeout_s`` / ``count`` fields in. This
        # lets scenario authors write the ergonomic shorthand:
        #
        #   - at: 0
        #     wait_for: emit_install_completed
        #     timeout_s: 30
        #
        # in addition to the structured form.
        if isinstance(self.wait_for, str):
            self.wait_for = WaitFor(
                tool=self.wait_for,
                count=self.count or 1,
                timeout_s=self.timeout_s if self.timeout_s is not None else 30.0,
            )
        elif isinstance(self.wait_for, WaitFor):
            # If the caller used the structured form, sibling timeout_s /
            # count are extras and must not silently override.
            if self.timeout_s is not None or self.count is not None:
                raise ValueError(
                    "use either the bare 'wait_for: <tool>' shorthand "
                    "(with sibling 'timeout_s' / 'count') OR the "
                    "structured 'wait_for: {tool, count, timeout_s}' "
                    "form, not both"
                )

        # Exactly one of {say|drop|dm|wait_for} per beat.
        kinds = [
            ("say", self.say is not None),
            ("drop", self.drop is not None),
            ("dm", self.dm is not None),
            ("wait_for", self.wait_for is not None),
        ]
        present = [k for k, p in kinds if p]
        if not present:
            raise ValueError("beat must declare one of: say, drop, dm, wait_for")
        if len(present) > 1 and not (
            # 'drop' may carry a follow-up 'say' in the same beat.
            set(present) == {"say", "drop"}
        ):
            raise ValueError(
                f"beat must declare exactly one of say|drop|dm|wait_for; "
                f"got: {present}"
            )

        # Persona is required for all persona-driven beats; wait_for is
        # engine-driven and forbids persona.
        if self.wait_for is None and not self.persona:
            raise ValueError("persona is required for say|drop|dm beats")
        if self.wait_for is not None and self.persona:
            raise ValueError("wait_for beats must not declare a persona")

        if self.improv and self.say is None:
            # improv needs a seed line.
            raise ValueError("'improv: true' requires a 'say' seed line")
        return self


class Scenario(BaseModel):
    """A named sequence of beats."""

    name: str = Field(..., min_length=1)
    description: str = ""
    default_channel: str = Field(..., min_length=1)
    beats: list[Beat] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_monotonic(self) -> Self:
        last = -1.0
        for i, beat in enumerate(self.beats):
            if beat.at < last:
                raise ValueError(
                    f"beat {i} (at={beat.at}) violates monotonic non-decreasing 'at'"
                )
            last = beat.at
        return self

    @classmethod
    def from_yaml(cls, path: str | Path) -> Scenario:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"scenario {path} must be a YAML mapping")
        return cls.model_validate(raw)

    def validate_against(self, registry: PersonaRegistry) -> None:
        """Raise if any persona-driven beat references an unknown persona id."""
        for i, beat in enumerate(self.beats):
            if beat.persona is None:
                # wait_for beats are engine-driven — no persona to check.
                continue
            if not registry.has(beat.persona):
                raise ValueError(
                    f"beat {i} references unknown persona {beat.persona!r}; "
                    f"known: {sorted(registry.personas)}"
                )


def list_scenarios(scenarios_dir: str | Path) -> list[str]:
    """Return scenario file stems found under ``scenarios_dir``."""
    p = Path(scenarios_dir)
    if not p.is_dir():
        return []
    return sorted(
        f.stem for f in p.iterdir() if f.suffix in {".yml", ".yaml"} and f.is_file()
    )


__all__ = [
    "Beat",
    "DirectMessage",
    "FileDrop",
    "Scenario",
    "WaitFor",
    "list_scenarios",
]
