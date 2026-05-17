"""Local Python notebook kernel — runs YAML-cell notebooks in a sandboxed subprocess.

Day-one kernel only (PRD §16.5): ``python_local``. Each cell runs in a
single persistent Python subprocess via a tiny stdin/stdout JSON protocol;
state lives across cells in one ``run`` call. Resource caps:

- 30 s wall-clock per run (default; override via ``timeout_s``)
- 512 MB RSS via ``resource.setrlimit(RLIMIT_AS, ...)`` (best-effort; may
  be ignored on macOS for some Python builds — that's fine for dev)

Cell hashes are sha256 over ``cell.source + sorted(input_hashes)``;
``kernel_state_hash`` summarises the post-run state-keys for determinism
gating.

Errors don't raise: a cell that throws lands as ``status="error"`` in the
per-cell output, and the run as a whole is ``status="error"``. The caller
writes the error result via ``run_notebook(... status='error')`` so the
ledger captures the failure.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import textwrap
from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Cell + RunResult dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Cell:
    """A single notebook cell.

    ``kind`` ∈ {"code", "markdown"}. SQL kernels (``python_pandas`` /
    ``sql_postgres``) are not implemented in this block; passing a "sql"
    cell raises ``NotImplementedError`` from the kernel.
    """

    kind: str
    source: str
    language: str = "python"


@dataclass(frozen=True)
class CellOutput:
    """Per-cell run result.

    ``stdout`` / ``stderr`` are captured strings. ``value`` is the
    last-expression value if the cell ends in an expression (None
    otherwise). ``status`` ∈ {"ok", "error"}; on error ``error`` carries
    the exception class + message.
    """

    kind: str
    status: str
    stdout: str = ""
    stderr: str = ""
    value: Any = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "status": self.status,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "value": self.value,
            "error": self.error,
        }


@dataclass(frozen=True)
class RunResult:
    """The full result of a notebook run.

    ``status`` is the overall run status ("ok" if every cell was ok, else
    "error"). ``cell_hashes`` and ``cell_outputs`` are aligned by index.
    ``kernel_state_hash`` is sha256 over the sorted state-key names —
    deterministic across replays.
    """

    status: str
    cell_outputs: list[CellOutput]
    cell_hashes: list[str]
    kernel_state_hash: str
    duration_ms: int


# ---------------------------------------------------------------------------
# Cell hashing
# ---------------------------------------------------------------------------


def _cell_hash(source: str, input_hashes: list[str]) -> str:
    """sha256 over (source + sorted_input_hashes)."""
    h = hashlib.sha256()
    h.update(source.encode("utf-8"))
    for ih in sorted(input_hashes):
        h.update(b"|")
        h.update(ih.encode("utf-8"))
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Sandbox subprocess driver
# ---------------------------------------------------------------------------


_RUNNER_SCRIPT = textwrap.dedent("""
    import ast
    import io
    import json
    import sys
    import resource

    # Best-effort RSS cap (512MB). RLIMIT_AS may be unsupported on some
    # platforms; we ignore failures.
    try:
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    except (OSError, ValueError):
        pass

    GLOBALS = {"__name__": "__main__"}

    def _run_cell(source):
        sout = io.StringIO()
        serr = io.StringIO()
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = sout, serr
        try:
            tree = ast.parse(source, mode="exec")
            value = None
            if tree.body and isinstance(tree.body[-1], ast.Expr):
                last_expr = tree.body[-1]
                tree.body = tree.body[:-1]
                if tree.body:
                    code_obj = compile(tree, "<cell>", "exec")
                    exec(code_obj, GLOBALS)
                expr_obj = compile(ast.Expression(last_expr.value), "<cell>", "eval")
                value = eval(expr_obj, GLOBALS)
            else:
                code_obj = compile(tree, "<cell>", "exec")
                exec(code_obj, GLOBALS)
            try:
                json.dumps(value)
            except (TypeError, ValueError):
                value = repr(value)
            return {
                "status": "ok",
                "stdout": sout.getvalue(),
                "stderr": serr.getvalue(),
                "value": value,
                "error": None,
            }
        except BaseException as exc:
            return {
                "status": "error",
                "stdout": sout.getvalue(),
                "stderr": serr.getvalue(),
                "value": None,
                "error": f"{type(exc).__name__}: {exc}",
            }
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr

    def main():
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            req = json.loads(line)
            cmd = req.get("cmd")
            if cmd == "run":
                result = _run_cell(req["source"])
                sys.stdout.write(json.dumps(result) + "\\n")
                sys.stdout.flush()
            elif cmd == "state_keys":
                keys = sorted(k for k in GLOBALS if not k.startswith("_"))
                sys.stdout.write(json.dumps({"keys": keys}) + "\\n")
                sys.stdout.flush()
            elif cmd == "exit":
                return

    main()
""")


class LocalPythonKernel:
    """Run a list of cells in a persistent Python subprocess.

    State (variables, imports) survives across cells within a single run.
    Each ``run`` call spawns a fresh subprocess so two independent runs
    don't share state.
    """

    def __init__(self, *, timeout_s: int = 30) -> None:
        self.timeout_s = timeout_s

    async def run(
        self,
        cells: list[Cell],
        *,
        input_hashes: list[str] | None = None,
    ) -> RunResult:
        """Run cells; never raises (errors land in CellOutput.status)."""
        loop = asyncio.get_running_loop()
        started = loop.time()

        # Validate cell kinds up front.
        for cell in cells:
            if cell.kind not in ("code", "markdown"):
                raise NotImplementedError(
                    f"cell kind {cell.kind!r} not supported by python_local "
                    "kernel; sql cells require sql_postgres / python_pandas",
                )

        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            _RUNNER_SCRIPT,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        cell_outputs: list[CellOutput] = []
        cell_hashes: list[str] = []
        prior_hashes: list[str] = list(input_hashes or [])
        overall_status = "ok"

        try:
            for cell in cells:
                ch = _cell_hash(cell.source, prior_hashes)
                cell_hashes.append(ch)
                prior_hashes.append(ch)

                if cell.kind == "markdown":
                    cell_outputs.append(
                        CellOutput(kind="markdown", status="ok", value=cell.source),
                    )
                    continue

                req = json.dumps({"cmd": "run", "source": cell.source}) + "\n"
                try:
                    assert proc.stdin is not None
                    proc.stdin.write(req.encode("utf-8"))
                    await proc.stdin.drain()
                    raw = await asyncio.wait_for(
                        proc.stdout.readline(),
                        timeout=self.timeout_s,
                    )
                except asyncio.TimeoutError:
                    overall_status = "error"
                    cell_outputs.append(
                        CellOutput(
                            kind="code",
                            status="error",
                            error=f"timeout after {self.timeout_s}s",
                        ),
                    )
                    break

                if not raw:
                    # Subprocess crashed (segfault, RSS cap fired) — read
                    # whatever stderr we can and bail.
                    overall_status = "error"
                    cell_outputs.append(
                        CellOutput(
                            kind="code",
                            status="error",
                            error="kernel subprocess died",
                        ),
                    )
                    break

                payload = json.loads(raw.decode("utf-8").strip())
                status = payload.get("status", "error")
                cell_outputs.append(
                    CellOutput(
                        kind="code",
                        status=status,
                        stdout=payload.get("stdout", ""),
                        stderr=payload.get("stderr", ""),
                        value=payload.get("value"),
                        error=payload.get("error"),
                    ),
                )
                if status != "ok":
                    overall_status = "error"
                    # Continue running remaining cells anyway — Jupyter
                    # parity. They'll likely also fail but the user sees
                    # all errors at once.

            # Collect kernel state for the state_hash.
            try:
                assert proc.stdin is not None
                proc.stdin.write((json.dumps({"cmd": "state_keys"}) + "\n").encode("utf-8"))
                await proc.stdin.drain()
                raw = await asyncio.wait_for(
                    proc.stdout.readline(),
                    timeout=2.0,
                )
                state = json.loads(raw.decode("utf-8").strip()) if raw else {"keys": []}
            except (asyncio.TimeoutError, json.JSONDecodeError, AssertionError):
                state = {"keys": []}

            kernel_state_hash = hashlib.sha256(
                "|".join(state.get("keys", [])).encode("utf-8"),
            ).hexdigest()

        finally:
            try:
                if proc.stdin is not None and not proc.stdin.is_closing():
                    proc.stdin.write((json.dumps({"cmd": "exit"}) + "\n").encode("utf-8"))
                    await proc.stdin.drain()
                    proc.stdin.close()
            except (BrokenPipeError, ConnectionResetError):
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()

        duration_ms = int((loop.time() - started) * 1000)
        return RunResult(
            status=overall_status,
            cell_outputs=cell_outputs,
            cell_hashes=cell_hashes,
            kernel_state_hash=kernel_state_hash,
            duration_ms=duration_ms,
        )


# Convenience: deserialize cells from JSON dict shape (the wire format).


def cells_from_dicts(items: list[dict[str, Any]]) -> list[Cell]:
    out: list[Cell] = []
    for item in items:
        kind = item.get("kind", "code")
        source = item.get("source", "")
        language = item.get("language", "python")
        out.append(Cell(kind=kind, source=source, language=language))
    return out


__all__ = [
    "Cell",
    "CellOutput",
    "LocalPythonKernel",
    "RunResult",
    "cells_from_dicts",
]
