"""Block E (cache half) — :class:`SqliteInferenceCache` /
:class:`NullInferenceCache` / :func:`make_cache_key`."""
from __future__ import annotations

from pathlib import Path

import pytest

from wormbase_inference.cache import (
    InferenceCache,
    NullInferenceCache,
    SqliteInferenceCache,
    make_cache_key,
)


def test_make_cache_key_is_deterministic() -> None:
    a = make_cache_key(
        model="kimi-k2.6:cloud",
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.0,
    )
    b = make_cache_key(
        model="kimi-k2.6:cloud",
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.0,
    )
    assert a == b
    assert len(a) == 64  # sha256 hex


def test_make_cache_key_differs_on_any_input() -> None:
    base = dict(model="m", messages=[{"role": "user", "content": "hi"}], temperature=0.0)
    k = make_cache_key(**base)  # type: ignore[arg-type]
    assert k != make_cache_key(**{**base, "model": "n"})  # type: ignore[arg-type]
    assert k != make_cache_key(  # type: ignore[arg-type]
        **{**base, "messages": [{"role": "user", "content": "ho"}]}
    )
    assert k != make_cache_key(**{**base, "temperature": 0.5})  # type: ignore[arg-type]


def test_null_cache_is_protocol_compatible() -> None:
    c = NullInferenceCache()
    assert isinstance(c, InferenceCache)
    assert c.get("any") is None
    c.put("any", "v", model="m")
    assert c.get("any") is None  # never stored
    assert c.invalidate_all() == 0


def test_sqlite_cache_stores_and_returns(tmp_path: Path) -> None:
    cache = SqliteInferenceCache(tmp_path / "x.sqlite")
    assert cache.get("k") is None
    cache.put("k", "the answer", model="kimi-k2.6:cloud")
    assert cache.get("k") == "the answer"
    cache.close()


def test_sqlite_cache_overwrites_on_put(tmp_path: Path) -> None:
    cache = SqliteInferenceCache(tmp_path / "y.sqlite")
    cache.put("k", "v1", model="m")
    cache.put("k", "v2", model="m")
    assert cache.get("k") == "v2"
    cache.close()


def test_sqlite_cache_invalidate_all_returns_count(tmp_path: Path) -> None:
    cache = SqliteInferenceCache(tmp_path / "z.sqlite")
    cache.put("a", "1", model="m")
    cache.put("b", "2", model="m")
    cache.put("c", "3", model="m")
    n = cache.invalidate_all()
    assert n == 3
    assert cache.get("a") is None
    cache.close()


def test_sqlite_cache_creates_parent_dirs(tmp_path: Path) -> None:
    nested = tmp_path / "deeper" / "and" / "deeper" / "cache.sqlite"
    cache = SqliteInferenceCache(nested)
    assert nested.exists()
    cache.close()


def test_sqlite_cache_invalidate_on_empty_returns_zero(tmp_path: Path) -> None:
    cache = SqliteInferenceCache(tmp_path / "empty.sqlite")
    assert cache.invalidate_all() == 0
    cache.close()


@pytest.mark.parametrize(
    "extra_a,extra_b,should_match",
    [
        (None, {}, True),                      # None ≡ empty dict
        ({"k": "v"}, {"k": "v"}, True),        # same extra
        ({"k": "v"}, {"k": "w"}, False),       # different value
        ({"k": "v"}, {"j": "v"}, False),       # different key
        ({"a": "1", "b": "2"}, {"b": "2", "a": "1"}, True),  # order-insensitive
    ],
)
def test_make_cache_key_respects_extra(
    extra_a: dict[str, str] | None,
    extra_b: dict[str, str],
    should_match: bool,
) -> None:
    base = dict(model="m", messages=[{"role": "u", "content": "x"}], temperature=0.0)
    k1 = make_cache_key(**base, extra=extra_a)  # type: ignore[arg-type]
    k2 = make_cache_key(**base, extra=extra_b)  # type: ignore[arg-type]
    assert (k1 == k2) is should_match
