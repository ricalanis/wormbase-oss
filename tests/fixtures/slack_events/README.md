# `tests/fixtures/slack_events/`

Recorded Slack event payloads for replay. Each file is one OpenClaw
session JSONL (the same format `apps/channel-adapter/parser.py` parses
in production).

## Format

One JSON object per line; `type: "session"` header line, then any number
of `type: "message"` lines (role: user / assistant / toolResult).

See `apps/channel-adapter/tests/conftest.py::make_inbound_line` for the
canonical builders. To capture from a real run:

```bash
cp ~/.openclaw/agents/main/sessions/<id>.jsonl \
   tests/fixtures/slack_events/<scenario-name>.jsonl
```

## Convention

- `<scenario>_inbound_only.jsonl` — only user messages (no replies)
- `<scenario>_full_turn.jsonl`    — inbound + assistant text reply
- `<scenario>_with_tools.jsonl`   — inbound + tool calls + replies
- `mention_<channel>.jsonl`       — @worm mention events
- `file_share_<filename>.jsonl`   — file_share Slack events
- `pii_<kind>.jsonl`              — text containing SSN/email/CC for PII gate

The integration tests bind-mount this directory (read-only) into the
test channel-adapter container; the adapter tails it as if it were the
live OpenClaw sessions volume.
