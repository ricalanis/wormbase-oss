#!/usr/bin/env bash
# Fails CI if a file under one of the egress-surface globs is present
# without referencing the silent-mode gate. Suppress false positives
# with the magic comment `# silent-mode: not-an-egress` somewhere in
# the file.

set -euo pipefail

GLOBS=(
  "packages/channel-adapters/src/wormbase_channel_adapters/*.py"
  "apps/channel-adapter/src/wormbase_channel_adapter/dm.py"
  "apps/worm-core/src/wormbase_core/write_actions.py"
  "apps/voice-agent/src/wormbase_voice_agent/app.py"
)

fail=0
for pattern in "${GLOBS[@]}"; do
  for file in $pattern; do
    [[ -f "$file" ]] || continue
    if grep -qE "# silent-mode: not-an-egress" "$file"; then
      continue
    fi
    if ! grep -qE "is_silent_mode_enabled|SilentModeChannelAdapter" "$file"; then
      echo "silent-mode coverage: $file does not reference the silent-mode gate" >&2
      echo "  add the gate, or mark with: # silent-mode: not-an-egress" >&2
      fail=1
    fi
  done
done

# Gate 6 (openclaw embedded agent) lives in a shell entrypoint, not
# Python. The egress is implicit — openclaw replies because we declare
# channel→agent bindings. Guard: the entrypoint must consult
# WORMBASE_SILENT_MODE somewhere so it can omit the bindings.
SHELL_GATES=(
  "infra/openclaw/entrypoint.sh"
)
for file in "${SHELL_GATES[@]}"; do
  [[ -f "$file" ]] || continue
  if grep -qE "# silent-mode: not-an-egress" "$file"; then
    continue
  fi
  if ! grep -qE "WORMBASE_SILENT_MODE" "$file"; then
    echo "silent-mode coverage: $file does not consult WORMBASE_SILENT_MODE" >&2
    echo "  add the gate (see plan §Task 11), or mark with: # silent-mode: not-an-egress" >&2
    fail=1
  fi
done

exit $fail
