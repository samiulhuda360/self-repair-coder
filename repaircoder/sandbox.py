"""Run candidate code against assert-style tests in a separate, time-limited Python process.

Isolation used:
- a fresh `python -I` interpreter (no user site-packages, no PYTHON* env vars, no script dir on sys.path);
- a throwaway working directory and a minimal environment;
- a wall-clock timeout, after which the process is killed;
- on Linux and macOS, CPU, memory, file-size and process-count limits;
- sockets are disabled inside the harness.

This contains broken code (infinite loops, crashes, runaway memory). It is not a security boundary for
hostile code; run the service inside a container for that.
"""

from __future__ import annotations

import contextlib
import functools
import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

RUNNER = Path(__file__).with_name("_runner.py")
MEMORY_LIMIT_BYTES = 512 * 1024 * 1024
FILE_LIMIT_BYTES = 1024 * 1024
PROCESS_LIMIT = 256


@dataclass(frozen=True)
class TestOutcome:
    __test__ = False  # not a pytest test class

    index: int
    test: str
    passed: bool
    error: str | None = None


@dataclass(frozen=True)
class SandboxResult:
    outcomes: list[TestOutcome] = field(default_factory=list)
    load_error: str | None = None
    timed_out: bool = False
    stderr: str = ""
    duration_s: float = 0.0

    @property
    def passed(self) -> int:
        return sum(1 for o in self.outcomes if o.passed)

    @property
    def total(self) -> int:
        return len(self.outcomes)

    @property
    def all_passed(self) -> bool:
        return self.load_error is None and not self.timed_out and self.total > 0 and self.passed == self.total

    def failures(self) -> list[TestOutcome]:
        return [o for o in self.outcomes if not o.passed]


def _limit_resources(cpu_seconds: int) -> None:  # pragma: no cover - only runs on POSIX in the child
    if sys.platform != "win32":
        import resource

        limits = [
            (resource.RLIMIT_CPU, cpu_seconds),
            (resource.RLIMIT_AS, MEMORY_LIMIT_BYTES),
            (resource.RLIMIT_FSIZE, FILE_LIMIT_BYTES),
            (resource.RLIMIT_NPROC, PROCESS_LIMIT),
        ]
        for kind, value in limits:
            with contextlib.suppress(ValueError, OSError):  # some platforms (e.g. macOS for RLIMIT_AS) refuse a limit
                resource.setrlimit(kind, (value, value))


def _child_env() -> dict[str, str]:
    env = {"PYTHONIOENCODING": "utf-8", "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"}
    for name in ("SYSTEMROOT", "PATH"):  # Windows needs SYSTEMROOT to start Python at all
        if name in os.environ:
            env[name] = os.environ[name]
    return env


def run_tests(code: str, tests: list[str], timeout_s: float = 5.0) -> SandboxResult:
    """Execute `code`, then each test, in a child process. Never raises for bad candidate code."""
    with tempfile.TemporaryDirectory(prefix="repaircoder-") as tmp:
        workdir = Path(tmp)
        (workdir / "solution.py").write_text(code, encoding="utf-8")
        (workdir / "tests.json").write_text(json.dumps(tests), encoding="utf-8")
        results_path = workdir / "results.jsonl"
        command = [sys.executable, "-I", str(RUNNER), "solution.py", "tests.json", "results.jsonl"]
        preexec: Callable[[], None] | None = None
        if os.name == "posix":
            preexec = functools.partial(_limit_resources, max(1, int(timeout_s) + 1))

        started = time.perf_counter()
        timed_out = False
        stderr = ""
        try:
            proc = subprocess.run(
                command,
                cwd=workdir,
                env=_child_env(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
                preexec_fn=preexec,
            )
            stderr = proc.stderr[-2000:]
        except subprocess.TimeoutExpired:
            timed_out = True
        duration = time.perf_counter() - started

        records = []
        if results_path.exists():
            for line in results_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    records.append(json.loads(line))

    load_error = next((r["error"] for r in records if r["kind"] == "load_error"), None)
    done = {r["index"]: r for r in records if r["kind"] == "test"}
    outcomes: list[TestOutcome] = []
    for index, test in enumerate(tests):
        record = done.get(index)
        if record is not None:
            outcomes.append(TestOutcome(index, test, bool(record["passed"]), record.get("error")))
        elif load_error is not None:
            outcomes.append(TestOutcome(index, test, False, f"not run: {load_error}"))
        elif timed_out:
            outcomes.append(TestOutcome(index, test, False, f"timed out after {timeout_s:g}s"))
        else:
            outcomes.append(TestOutcome(index, test, False, "harness crashed: " + (stderr.strip().splitlines() or ["?"])[-1]))
    return SandboxResult(outcomes, load_error, timed_out, stderr, round(duration, 3))
