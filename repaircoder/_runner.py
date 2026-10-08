"""Test harness that runs inside the sandbox subprocess.

Usage: python -I _runner.py SOLUTION_FILE TESTS_JSON RESULTS_JSONL

Loads the candidate solution, then runs each assert-style test on its own and appends one JSON line per test
to RESULTS_JSONL, so a timeout still leaves the results of the tests that finished. Uses only the standard
library, because it runs with an isolated interpreter.
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import socket
import sys
import traceback
from typing import Any

MAX_DETAIL = 400


def _no_network(*_args: Any, **_kwargs: Any) -> Any:
    raise PermissionError("network access is disabled in the sandbox")


def _short(value: Any) -> str:
    text = repr(value)
    return text if len(text) <= MAX_DETAIL else text[:MAX_DETAIL] + "..."


def _last_line(exc: BaseException, source_lines: list[str] | None = None) -> str:
    """One-line error summary, pointing at the solution line that failed when there is one."""
    if isinstance(exc, SyntaxError):
        where = f"line {exc.lineno}: {(exc.text or '').strip()}" if exc.lineno else "unknown line"
        return f"{type(exc).__name__}: {exc.msg} ({where})"[:MAX_DETAIL]
    summary = traceback.format_exception_only(type(exc), exc)[-1].strip()
    if source_lines:
        frames = [f for f in traceback.extract_tb(exc.__traceback__) if f.filename == "solution.py" and f.lineno]
        if frames:
            lineno = frames[-1].lineno or 0
            code = source_lines[lineno - 1].strip() if 0 < lineno <= len(source_lines) else ""
            summary += f" (solution.py line {lineno}: {code})"
    return summary[:MAX_DETAIL]


def _explain_assert(test: str, namespace: dict[str, Any]) -> str | None:
    """For `assert a == b`, report what `a` actually evaluated to."""
    try:
        tree = ast.parse(test)
    except SyntaxError:
        return None
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.Assert):
        return None
    check = tree.body[0].test
    if not (isinstance(check, ast.Compare) and len(check.ops) == 1 and isinstance(check.ops[0], ast.Eq)):
        return None
    try:
        got = eval(compile(ast.Expression(check.left), "<test>", "eval"), dict(namespace))
        expected = eval(compile(ast.Expression(check.comparators[0]), "<test>", "eval"), dict(namespace))
    except BaseException:  # noqa: BLE001 - any error here just means no extra detail
        return None
    return f"expected {_short(expected)}, got {_short(got)}"


def raises(error: type[BaseException], func: Any, *args: Any, **kwargs: Any) -> bool:
    """Test helper: True when func(*args, **kwargs) raises `error`."""
    try:
        func(*args, **kwargs)
    except error:
        return True
    return False


def main() -> int:
    solution_file, tests_file, results_file = sys.argv[1:4]
    socket.socket = _no_network  # type: ignore[assignment,misc]
    socket.create_connection = _no_network
    with open(tests_file, encoding="utf-8") as fh:
        tests: list[str] = json.load(fh)
    with open(solution_file, encoding="utf-8") as fh:
        source = fh.read()
    lines = source.splitlines()

    with open(results_file, "a", encoding="utf-8") as out:

        def emit(record: dict[str, Any]) -> None:
            out.write(json.dumps(record) + "\n")
            out.flush()

        namespace: dict[str, Any] = {"__name__": "solution"}
        captured = io.StringIO()
        try:
            with contextlib.redirect_stdout(captured):
                exec(compile(source, "solution.py", "exec"), namespace)
        except BaseException as exc:  # noqa: BLE001 - a broken solution must never crash the harness
            emit({"kind": "load_error", "error": _last_line(exc, lines)})
            return 0

        for index, test in enumerate(tests):
            try:
                with contextlib.redirect_stdout(captured):
                    exec(compile(test, f"test_{index}", "exec"), {**namespace, "raises": raises})
                emit({"kind": "test", "index": index, "passed": True})
            except AssertionError as exc:
                detail = _explain_assert(test, {**namespace, "raises": raises}) or _last_line(exc)
                emit({"kind": "test", "index": index, "passed": False, "error": f"AssertionError: {detail}"})
            except BaseException as exc:  # noqa: BLE001
                emit({"kind": "test", "index": index, "passed": False, "error": _last_line(exc, lines)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
