"""Task definitions and the benchmark loader."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .config import ROOT

BENCHMARK_FILE = ROOT / "benchmark" / "tasks.toml"

Mode = Literal["generate", "fix"]


def split_tests(block: str) -> list[str]:
    """One test per line; an indented line continues the test above it. Blank and comment lines are skipped.
    Several statements can share a line with semicolons: `c = Counter(); c.add(1); assert c.total == 1`."""
    tests: list[str] = []
    for raw in block.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] in " \t" and tests:
            tests[-1] += "\n" + line
        else:
            tests.append(line.strip())
    return tests


@dataclass(frozen=True)
class Task:
    id: str
    prompt: str
    entry_point: str
    tests: list[str]
    hidden_tests: list[str] = field(default_factory=list)
    mode: Mode = "generate"
    starter_code: str | None = None
    reference: str | None = None

    @property
    def all_tests(self) -> list[str]:
        return [*self.tests, *self.hidden_tests]


def load_benchmark(path: Path = BENCHMARK_FILE) -> list[Task]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    tasks = []
    for item in data["task"]:
        mode: Mode = "fix" if item.get("starter_code") else "generate"
        tasks.append(
            Task(
                id=item["id"],
                prompt=item["prompt"].strip(),
                entry_point=item["entry_point"],
                tests=split_tests(item["tests"]),
                hidden_tests=split_tests(item.get("hidden_tests", "")),
                mode=mode,
                starter_code=item.get("starter_code"),
                reference=item.get("reference"),
            )
        )
    return tasks
