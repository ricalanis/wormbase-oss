"""SetupDmDriver — DM driver primitives for the per-tenant onboarding script.

Per D4 + spike s C6: the chat-worm-side of setup_conversation.py.
Includes:
  - SetupStep, SetupScript      — YAML-script value types
  - load_script, load_script_for_pack — YAML loader
  - DmAdapter Protocol          — DM-platform shim
  - ParsedAnswer, parse_answer  — answer parser
  - parse_mentions              — @-mention extractor

The orchestration loop (_TenantSession, SetupConversationLoop) STAYS in
worm-core because it calls write_actions.advance_setup_step +
complete_setup. The split is at setup_conversation.py:53 (the
wormbase_core.write_actions import).

Bodies copied verbatim from apps/worm-core/src/wormbase_core/setup_conversation.py
lines 1-241 (the import line for write_actions is at 53; everything above
that line is chat-worm-portable; this module excludes the worm-core
imports).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Protocol

import yaml


# ---------------------------------------------------------------------------
# YAML script types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SetupStep:
    """One step in a setup conversation."""

    id: str
    bot_says: str
    on_answer: str
    expects: str | None = None
    options: tuple[str, ...] = ()
    next: str | None = None


@dataclass(frozen=True)
class SetupScript:
    """A loaded YAML conversation script."""

    domain_pack: str
    steps: tuple[SetupStep, ...]

    def first(self) -> SetupStep:
        return self.steps[0]

    def by_id(self, step_id: str) -> SetupStep | None:
        for s in self.steps:
            if s.id == step_id:
                return s
        return None

    def next_after(self, step_id: str) -> SetupStep | None:
        cur = self.by_id(step_id)
        if cur is None or cur.next is None:
            return None
        return self.by_id(cur.next)


def load_script(path: str | Path) -> SetupScript:
    """Load a YAML script into a SetupScript."""
    p = Path(path)
    with p.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"setup script {p} root is not a mapping")
    pack = str(data.get("domain_pack") or p.stem.split("-")[0])
    raw_steps = data.get("steps") or []
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError(f"setup script {p} has no steps")
    steps: list[SetupStep] = []
    for raw in raw_steps:
        if not isinstance(raw, dict):
            raise ValueError(f"step in {p} is not a mapping: {raw!r}")
        opts_raw = raw.get("options") or ()
        opts = tuple(str(o) for o in opts_raw) if isinstance(opts_raw, list) else ()
        steps.append(
            SetupStep(
                id=str(raw["id"]),
                bot_says=str(raw["bot_says"]).strip(),
                on_answer=str(raw["on_answer"]),
                expects=str(raw["expects"]) if raw.get("expects") else None,
                options=opts,
                next=str(raw["next"]) if raw.get("next") else None,
            ),
        )
    return SetupScript(domain_pack=pack, steps=tuple(steps))


# O-B4: YAMLs ship as package data inside this package. Resolved via
# importlib.resources rather than fragile parent-traversal from __file__.
# The previous implementation walked five parents up to apps/worm-core/
# setup_conversations/, which broke any time the package was installed
# outside the workspace (wheel install, editable install in a venv with
# a different layout, etc.).
_DEFAULT_SCRIPT_PACKAGE = "wormbase_chat_presence.setup_conversations"


def _load_default(pack: str) -> Path:
    """Resolve ``<pack>-default.yml`` from the package's bundled data.

    Falls back to ``saas-default.yml`` when the pack-specific file is
    missing. Returns a ``Path`` because ``load_script`` accepts paths
    and ``importlib.resources.files(...).joinpath(...)`` returns a
    ``Traversable`` that ``Path`` semantics work over for read access
    on filesystem-backed packages.
    """
    root = resources.files(_DEFAULT_SCRIPT_PACKAGE)
    candidate = root.joinpath(f"{pack}-default.yml")
    if not candidate.is_file():
        candidate = root.joinpath("saas-default.yml")
    return Path(str(candidate))


def load_script_for_pack(
    pack: str, *, script_dir: Path | None = None,
) -> SetupScript:
    """Load the YAML for ``pack`` (saas | marketplace | fintech).

    Falls back to saas-default when ``pack`` doesn't have a dedicated
    file. Custom packs are accepted via ``script_dir`` for tests.
    """
    if script_dir is not None:
        candidate = script_dir / f"{pack}-default.yml"
        if not candidate.exists():
            candidate = script_dir / "saas-default.yml"
        return load_script(candidate)
    return load_script(_load_default(pack))


# ---------------------------------------------------------------------------
# Adapter Protocol — Slack DM driver, dependency-injected for tests.
# ---------------------------------------------------------------------------


class DmAdapter(Protocol):
    """Minimum surface needed to drive a 1:1 setup conversation.

    Production wiring (cli.py): SlackChannelAdapter satisfies this via
    ``conversations_open`` + ``chat_postMessage`` + ``conversations_history``.
    Tests pass an in-memory mock.
    """

    async def open_dm(self, platform_user_id: str) -> str: ...

    async def post_message(self, channel_id: str, text: str) -> str: ...

    async def fetch_replies(
        self, channel_id: str, *, since_seq: int,
    ) -> list[dict[str, Any]]: ...


# ---------------------------------------------------------------------------
# Answer parsing — pure functions for unit-test coverage.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParsedAnswer:
    """Result of parsing one installer DM reply against a step's expects."""

    ok: bool
    value: Any = None
    error: str | None = None


def parse_answer(step: SetupStep, raw_text: str) -> ParsedAnswer:
    """Parse a raw DM reply per ``step.expects``.

    one_of  → must match ``options`` case-insensitively.
    free_text → any non-empty string after strip.
    No expects (final step) → always ok.
    """
    text = (raw_text or "").strip()
    if step.expects is None:
        return ParsedAnswer(ok=True, value=text)
    if step.expects == "one_of":
        if not step.options:
            return ParsedAnswer(ok=False, error="step has no options")
        norm = text.lower()
        for opt in step.options:
            if opt.lower() == norm:
                return ParsedAnswer(ok=True, value=opt)
        return ParsedAnswer(
            ok=False,
            error=f"answer must be one of {list(step.options)}; got {text!r}",
        )
    if step.expects == "free_text":
        if not text:
            return ParsedAnswer(ok=False, error="answer must not be empty")
        return ParsedAnswer(ok=True, value=text)
    return ParsedAnswer(ok=False, error=f"unknown expects: {step.expects}")


_MENTION_RE = re.compile(r"<@(?P<id>[A-Za-z0-9_]+)>|@(?P<at>[A-Za-z0-9_.-]+)")


def parse_mentions(raw_text: str) -> list[str]:
    """Extract platform_user_ids / display_names from an invite-admins reply.

    Slack mention shape ``<@UABC123>`` is parsed canonically; bare
    ``@bob`` mentions fall back to display_name (the discovery loop
    resolves them later).

    Returns the deduplicated list in first-seen order. ``skip`` and
    empty strings yield ``[]``.
    """
    text = (raw_text or "").strip().lower()
    if not text or text == "skip":
        return []
    seen: list[str] = []
    for m in _MENTION_RE.finditer(raw_text):
        token = m.group("id") or m.group("at")
        if token and token not in seen:
            seen.append(token)
    return seen


__all__ = [
    "DmAdapter",
    "ParsedAnswer",
    "SetupScript",
    "SetupStep",
    "load_script",
    "load_script_for_pack",
    "parse_answer",
    "parse_mentions",
]
