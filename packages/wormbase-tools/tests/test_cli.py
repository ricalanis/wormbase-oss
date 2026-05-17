"""Smoke tests for the ``wormbase-tools`` CLI surface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from click.testing import CliRunner

from wormbase_tools.cli import main


def _runner() -> CliRunner:
    """CliRunner factory tolerant of Click 8.0/8.3+ API differences.

    Click 8.3 removed the ``mix_stderr`` kwarg; the CliRunner now keeps
    streams separate by default. Older Click had ``mix_stderr=False`` to
    achieve the same. This factory produces a runner that exposes
    ``result.stdout`` and ``result.stderr`` distinctly on either.
    """
    try:
        return CliRunner(mix_stderr=False)  # type: ignore[call-arg]
    except TypeError:
        return CliRunner()


def test_cli_replay_prints_value_and_exits_0(
    synthetic_kpi_snapshot: dict[str, Any]
) -> None:
    runner = _runner()
    res = runner.invoke(
        main,
        [
            "replay",
            str(synthetic_kpi_snapshot["path"]),
            "--tenant",
            synthetic_kpi_snapshot["company_id"],
            "--to",
            synthetic_kpi_snapshot["kpi_id"],
        ],
    )
    assert res.exit_code == 0, f"stderr: {res.stderr}"
    # stdout is reserved for the value — it must parse cleanly as a number.
    value = res.stdout.strip()
    assert float(value) == synthetic_kpi_snapshot["expected_value"]


def test_cli_replay_json_flag_emits_structured_result(
    synthetic_kpi_snapshot: dict[str, Any]
) -> None:
    runner = _runner()
    res = runner.invoke(
        main,
        [
            "replay",
            str(synthetic_kpi_snapshot["path"]),
            "--tenant",
            synthetic_kpi_snapshot["company_id"],
            "--to",
            synthetic_kpi_snapshot["kpi_id"],
            "--json",
        ],
    )
    assert res.exit_code == 0
    parsed = json.loads(res.stdout)
    assert parsed["kpi_id"] == synthetic_kpi_snapshot["kpi_id"]
    assert parsed["value"] == synthetic_kpi_snapshot["expected_value"]
    assert parsed["terminal_hash"] == synthetic_kpi_snapshot["terminal_hash_hex"]


def test_cli_replay_exits_1_on_chain_break(broken_chain_snapshot: Path) -> None:
    runner = _runner()
    res = runner.invoke(
        main,
        [
            "replay",
            str(broken_chain_snapshot),
            "--to",
            "any",
        ],
    )
    assert res.exit_code == 1
    # Diagnostic must go to stderr in pseudo-diff format.
    assert "@@" in res.stderr
    # Stdout must stay clean (auditor scripts pipe stdout to diff).
    assert res.stdout.strip() == ""


def test_cli_replay_exits_1_on_missing_kpi(
    synthetic_kpi_snapshot: dict[str, Any]
) -> None:
    runner = _runner()
    res = runner.invoke(
        main,
        [
            "replay",
            str(synthetic_kpi_snapshot["path"]),
            "--to",
            "kpi_does_not_exist",
        ],
    )
    assert res.exit_code == 1
    assert "@@" in res.stderr


def test_cli_replay_help_lists_required_flags() -> None:
    runner = CliRunner()
    res = runner.invoke(main, ["replay", "--help"])
    assert res.exit_code == 0
    assert "--tenant" in res.output
    assert "--to" in res.output
    assert "SNAPSHOT" in res.output


def test_cli_top_level_help() -> None:
    runner = CliRunner()
    res = runner.invoke(main, ["--help"])
    assert res.exit_code == 0
    assert "replay" in res.output


def test_cli_replay_timing_writes_to_stderr(
    synthetic_kpi_snapshot: dict[str, Any]
) -> None:
    runner = _runner()
    res = runner.invoke(
        main,
        [
            "replay",
            str(synthetic_kpi_snapshot["path"]),
            "--to",
            synthetic_kpi_snapshot["kpi_id"],
            "--timing",
        ],
    )
    assert res.exit_code == 0
    assert "replay:" in res.stderr
    assert "ms" in res.stderr
    # Stdout still bare value (no leakage).
    float(res.stdout.strip())

def test_cli_mcp_connect_prints_snippet_with_token() -> None:
    runner = _runner()
    res = runner.invoke(
        main,
        [
            'mcp', 'connect', 'https://demo.example.com/mcp',
            '--token', 'test-bearer-token-xyz',
        ],
    )
    assert res.exit_code == 0, f'stderr: {res.stderr}'
    parsed = json.loads(res.stdout)
    assert 'mcpServers' in parsed
    assert 'wormbase' in parsed['mcpServers']
    server = parsed['mcpServers']['wormbase']
    assert server['transport'] == 'http'
    assert server['url'] == 'https://demo.example.com/mcp'
    assert server['headers']['Authorization'] == 'Bearer test-bearer-token-xyz'


def test_cli_mcp_connect_uses_env_var_when_no_flag(monkeypatch) -> None:
    monkeypatch.setenv('WORMBASE_LEDGER_API_TOKEN', 'env-token-abc')
    runner = _runner()
    res = runner.invoke(
        main,
        ['mcp', 'connect', 'http://localhost:9911/mcp'],
    )
    assert res.exit_code == 0
    parsed = json.loads(res.stdout)
    auth = parsed['mcpServers']['wormbase']['headers']['Authorization']
    assert auth == 'Bearer env-token-abc'


def test_cli_mcp_connect_exits_1_when_no_token(monkeypatch) -> None:
    monkeypatch.delenv('WORMBASE_LEDGER_API_TOKEN', raising=False)
    runner = _runner()
    res = runner.invoke(
        main,
        ['mcp', 'connect', 'https://demo.example.com/mcp'],
    )
    assert res.exit_code == 1
    assert 'no token provided' in res.stderr


def test_cli_mcp_connect_writes_to_out_file(tmp_path) -> None:
    runner = _runner()
    out = tmp_path / 'snippet.json'
    res = runner.invoke(
        main,
        [
            'mcp', 'connect', 'https://demo.example.com/mcp',
            '--token', 'tok', '--out', str(out),
        ],
    )
    assert res.exit_code == 0
    parsed = json.loads(out.read_text(encoding='utf-8'))
    assert parsed['mcpServers']['wormbase']['url'] == 'https://demo.example.com/mcp'


def test_cli_mcp_connect_supports_custom_config_key() -> None:
    runner = _runner()
    res = runner.invoke(
        main,
        [
            'mcp', 'connect', 'https://demo.example.com/mcp',
            '--token', 'tok', '--name', 'worm-prod',
        ],
    )
    assert res.exit_code == 0
    parsed = json.loads(res.stdout)
    assert 'worm-prod' in parsed['mcpServers']
    assert 'wormbase' not in parsed['mcpServers']


def test_build_claude_desktop_snippet_matches_panel_shape() -> None:
    """Lock in shape parity with apps/dashboard/components/mcp/ConnectClaudeDesktopPanel.tsx::buildSnippet."""
    from wormbase_tools.cli import build_claude_desktop_snippet

    snippet = build_claude_desktop_snippet(
        config_key='wormbase',
        url='https://x.example.com/mcp',
        token='abc',
    )
    parsed = json.loads(snippet)
    assert parsed == {
        'mcpServers': {
            'wormbase': {
                'transport': 'http',
                'url': 'https://x.example.com/mcp',
                'headers': {'Authorization': 'Bearer abc'},
            }
        }
    }

