"""Tests for the local Python notebook kernel (F2)."""

from __future__ import annotations

import pytest

from wormbase_core.notebook_kernel import (
    Cell,
    LocalPythonKernel,
    cells_from_dicts,
)


@pytest.mark.asyncio
async def test_kernel_runs_simple_code_cell() -> None:
    kernel = LocalPythonKernel()
    result = await kernel.run([Cell(kind="code", source="1 + 1")])
    assert result.status == "ok"
    assert result.cell_outputs[0].value == 2
    assert result.cell_outputs[0].status == "ok"
    assert len(result.cell_hashes) == 1


@pytest.mark.asyncio
async def test_kernel_runs_two_cells_state_persists() -> None:
    kernel = LocalPythonKernel()
    result = await kernel.run(
        [
            Cell(kind="code", source="x = 5"),
            Cell(kind="code", source="x * 2"),
        ]
    )
    assert result.status == "ok"
    assert result.cell_outputs[1].value == 10


@pytest.mark.asyncio
async def test_kernel_captures_stdout() -> None:
    kernel = LocalPythonKernel()
    result = await kernel.run([Cell(kind="code", source="print('hello')")])
    assert result.status == "ok"
    assert "hello" in result.cell_outputs[0].stdout


@pytest.mark.asyncio
async def test_kernel_marks_error_on_raise() -> None:
    kernel = LocalPythonKernel()
    result = await kernel.run([Cell(kind="code", source="raise ValueError('boom')")])
    assert result.status == "error"
    assert result.cell_outputs[0].status == "error"
    assert "ValueError" in (result.cell_outputs[0].error or "")


@pytest.mark.asyncio
async def test_kernel_markdown_cell_passes_through() -> None:
    kernel = LocalPythonKernel()
    result = await kernel.run([Cell(kind="markdown", source="# Hello")])
    assert result.status == "ok"
    assert result.cell_outputs[0].value == "# Hello"
    assert result.cell_outputs[0].kind == "markdown"


@pytest.mark.asyncio
async def test_kernel_timeout_returns_error_not_raise() -> None:
    kernel = LocalPythonKernel(timeout_s=1)
    result = await kernel.run(
        [Cell(kind="code", source="import time\ntime.sleep(5)")]
    )
    assert result.status == "error"
    assert "timeout" in (result.cell_outputs[0].error or "").lower()


@pytest.mark.asyncio
async def test_kernel_sql_cell_raises_not_implemented() -> None:
    kernel = LocalPythonKernel()
    with pytest.raises(NotImplementedError):
        await kernel.run([Cell(kind="sql", source="SELECT 1")])


@pytest.mark.asyncio
async def test_cell_hashes_are_stable_across_runs() -> None:
    """Same source + same prior hashes → same cell hash."""
    kernel = LocalPythonKernel()
    cells = [
        Cell(kind="code", source="x = 1"),
        Cell(kind="code", source="y = x + 1"),
    ]
    a = await kernel.run(cells)
    b = await kernel.run(cells)
    assert a.cell_hashes == b.cell_hashes


@pytest.mark.asyncio
async def test_kernel_state_hash_is_deterministic() -> None:
    kernel = LocalPythonKernel()
    cells = [Cell(kind="code", source="alpha = 1\nbeta = 2")]
    a = await kernel.run(cells)
    b = await kernel.run(cells)
    assert a.kernel_state_hash == b.kernel_state_hash


def test_cells_from_dicts_decodes_kind_source_language() -> None:
    cells = cells_from_dicts(
        [
            {"kind": "code", "source": "x = 1", "language": "python"},
            {"kind": "markdown", "source": "# H"},
        ]
    )
    assert cells[0].kind == "code"
    assert cells[0].source == "x = 1"
    assert cells[1].kind == "markdown"
