"""Block H — smoke test for ``scripts/refresh_inference_cache.py``.

The script lives in repo-root ``scripts/`` so it imports cleanly under
its own ``uv run`` invocation. We don't invoke it as a subprocess here
(that would require a live ledger DSN); we exercise the wipe path
directly via the script's helpers.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from wormbase_inference.cache import SqliteInferenceCache

# Repo root: packages/inference-router/tests → ../../..
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "refresh_inference_cache.py"


def _load_script_module():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(
        "refresh_inference_cache_script", _SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_refresh_script_module_loads() -> None:
    mod = _load_script_module()
    assert callable(mod.main)
    assert callable(mod._wipe_cache)


def test_refresh_script_wipes_existing_cache(tmp_path: Path) -> None:
    cache = SqliteInferenceCache(tmp_path / "x.sqlite")
    cache.put("a", "1", model="m")
    cache.put("b", "2", model="m")
    cache.close()

    mod = _load_script_module()
    n = mod._wipe_cache(tmp_path / "x.sqlite")
    assert n == 2

    # Subsequent invocation finds zero rows.
    n2 = mod._wipe_cache(tmp_path / "x.sqlite")
    assert n2 == 0


def test_refresh_script_main_no_ledger_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mod = _load_script_module()
    monkeypatch.setenv("WORMBASE_INFERENCE_CACHE_PATH", str(tmp_path / "y.sqlite"))
    rc = mod.main(["--no-ledger"])
    assert rc == 0
    # Cache file exists post-wipe (auto-created during invalidate_all).
    assert (tmp_path / "y.sqlite").exists()


def test_tenant_to_company_uuid_is_deterministic() -> None:
    mod = _load_script_module()
    a = mod._tenant_to_company_uuid("baseworm")
    b = mod._tenant_to_company_uuid("baseworm")
    assert a == b
    # Different slug → different uuid.
    assert a != mod._tenant_to_company_uuid("other")
