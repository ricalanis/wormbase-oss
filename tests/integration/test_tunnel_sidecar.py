"""L5 integration: cloudflared quick-tunnel sidecar (W1.A2).

Smoke test: `make tunnel` brings up the cloudflared sidecar, the
helpers resolve a `https://*.trycloudflare.com` URL within 30s, the URL
serves a 200 from the dashboard service, the URL is upserted into
.env.tunnel, and `make tunnel-down` cleans up.

The test is **opt-in** — it requires Docker + outbound network access
to Cloudflare's edge. CI sets `WORMBASE_INTEGRATION_TUNNEL=1` to enable
it; on a developer machine without Docker (or behind a captive
firewall) the test is skipped.

This is the wire-side counterpart to the file-shape unit checks; it
asserts the actual handshake works end to end.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_TUNNEL_FILE = REPO_ROOT / ".env.tunnel"

TRYCLOUDFLARE_URL_RE = re.compile(
    r"WORMBASE_DASHBOARD_URL=(https://[a-zA-Z0-9-]+\.trycloudflare\.com)"
)


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        rc = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        return rc.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


_RUN_TUNNEL_TEST = (
    os.environ.get("WORMBASE_INTEGRATION_TUNNEL") == "1" and _docker_available()
)

pytestmark = pytest.mark.skipif(
    not _RUN_TUNNEL_TEST,
    reason=(
        "tunnel-sidecar smoke requires Docker + outbound network; "
        "set WORMBASE_INTEGRATION_TUNNEL=1 to enable"
    ),
)


def _run(cmd: list[str], *, check: bool = True, timeout: int = 90) -> subprocess.CompletedProcess[str]:
    """Run a subprocess in REPO_ROOT, returning the completed process."""
    return subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=check,
        timeout=timeout,
    )


@pytest.fixture(scope="module")
def tunnel_lifecycle() -> str:
    """Bring up `make tunnel`, yield the URL, tear down on exit.

    Module-scoped so the (~30-60s) tunnel boot only runs once even if
    we add more assertions later. The teardown always fires, even if
    the test body raises.
    """
    # Pre-clean any leftover .env.tunnel from a previous run so the
    # assertion below isn't a stale-cache false pass.
    if ENV_TUNNEL_FILE.exists():
        ENV_TUNNEL_FILE.unlink()

    try:
        _run(["make", "tunnel"], timeout=180)
    except subprocess.CalledProcessError as exc:
        # Surface cloudflared's stderr for triage; the make wrapper
        # mostly proxies it.
        pytest.fail(
            "make tunnel failed:\n"
            f"  rc={exc.returncode}\n"
            f"  stdout={exc.stdout}\n"
            f"  stderr={exc.stderr}"
        )

    url = _read_dashboard_url_from_env_tunnel()
    try:
        yield url
    finally:
        # Best-effort teardown — never fail the test on cleanup.
        try:
            _run(["make", "tunnel-down"], check=False, timeout=60)
        except subprocess.TimeoutExpired:
            pass


def _read_dashboard_url_from_env_tunnel() -> str:
    assert ENV_TUNNEL_FILE.exists(), (
        f".env.tunnel was not produced by `make tunnel`; "
        f"expected at {ENV_TUNNEL_FILE}"
    )
    text = ENV_TUNNEL_FILE.read_text()
    match = TRYCLOUDFLARE_URL_RE.search(text)
    assert match is not None, (
        ".env.tunnel did not contain a WORMBASE_DASHBOARD_URL line "
        "matching trycloudflare.com pattern; got:\n" + text
    )
    return match.group(1)


def test_tunnel_url_is_well_formed(tunnel_lifecycle: str) -> None:
    """The tunnel URL conforms to the trycloudflare.com pattern."""
    url = tunnel_lifecycle
    assert url.startswith("https://")
    assert url.endswith(".trycloudflare.com")
    # Hostname slug shape — cloudflared uses 3-4 hyphenated lowercase tokens.
    host = url.removeprefix("https://").removesuffix(".trycloudflare.com")
    assert re.fullmatch(r"[a-z0-9-]+", host), f"unexpected slug: {host}"


def test_tunnel_url_serves_dashboard_with_200(tunnel_lifecycle: str) -> None:
    """The tunnel URL serves the dashboard root with HTTP 200.

    Allow up to 60s of retry — pnpm install on the dashboard's first
    boot can lag behind the tunnel's readiness.
    """
    url = tunnel_lifecycle
    deadline = time.monotonic() + 60.0
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(url + "/", headers={"User-Agent": "wormbase-tunnel-test"})
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                if resp.status == 200:
                    return
                last_err = AssertionError(
                    f"unexpected HTTP {resp.status} from tunnel URL {url}"
                )
        except (urllib.error.URLError, TimeoutError) as exc:
            last_err = exc
        time.sleep(2)
    raise AssertionError(
        f"tunnel URL {url} never served HTTP 200 within 60s; last error: {last_err!r}"
    )


def test_make_tunnel_down_cleans_up_env_file(tunnel_lifecycle: str) -> None:  # noqa: ARG001
    """After `make tunnel-down`, .env.tunnel is gone and the container is removed.

    We invoke tunnel-down inline (the fixture's teardown also runs it,
    but module-scoped teardown happens AFTER this test, so we run it
    again here. tunnel-down is idempotent.)
    """
    _run(["make", "tunnel-down"], check=False, timeout=60)
    assert not ENV_TUNNEL_FILE.exists(), (
        ".env.tunnel should be removed by `make tunnel-down`"
    )
    # The compose service should be gone. `compose ps -q tunnel` returns
    # empty when the container is removed.
    rc = _run(
        ["docker", "compose", "--project-directory", ".", "-f", "infra/docker-compose.yml",
         "--profile", "oauth", "ps", "-q", "tunnel"],
        check=False,
    )
    assert rc.stdout.strip() == "", (
        f"tunnel container still present after tunnel-down: {rc.stdout!r}"
    )
