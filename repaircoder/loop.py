"""The generate -> test -> repair loop."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from . import prompts
from .llm import LLM, Completion
from .sandbox import SandboxResult, run_tests
from .tasks import Task

AttemptKind = Literal["generate", "fix", "repair"]


@dataclass(frozen=True)
class Attempt:
    number: int
    kind: AttemptKind
    code: str
    result: SandboxResult
    completion: Completion

    @property
    def passed(self) -> bool:
        return self.result.all_passed


@dataclass
class RunResult:
    task: Task
    tests: list[str]
    attempts: list[Attempt] = field(default_factory=list)
    baseline: SandboxResult | None = None
    tests_written_by_model: bool = False
    test_writing: Completion | None = None
    wall_time_s: float = 0.0

    @property
    def solved(self) -> bool:
        return bool(self.attempts) and self.attempts[-1].passed

    @property
    def first_try_passed(self) -> bool:
        return bool(self.attempts) and self.attempts[0].passed

    @property
    def final_code(self) -> str:
        return self.attempts[-1].code if self.attempts else ""

    def completions(self) -> list[Completion]:
        found = [a.completion for a in self.attempts]
        return [self.test_writing, *found] if self.test_writing else found

    @property
    def prompt_tokens(self) -> int:
        return sum(c.prompt_tokens for c in self.completions())

    @property
    def completion_tokens(self) -> int:
        return sum(c.completion_tokens for c in self.completions())

    @property
    def model_latency_s(self) -> float:
        return round(sum(c.latency_s for c in self.completions()), 3)


Listener = Callable[[str, object], None]


def solve(
    task: Task,
    llm: LLM,
    max_repairs: int = 3,
    timeout_s: float = 5.0,
    on_event: Listener | None = None,
) -> RunResult:
    """Generate (or fix) code for `task`, run it against the tests, and repair until they pass or the budget ends.

    Only `task.tests` are shown to the model. `task.hidden_tests` are kept back for scoring.
    """
    emit = on_event or (lambda _kind, _payload: None)
    started = time.perf_counter()
    run = RunResult(task=task, tests=list(task.tests))

    if not run.tests:
        completion = llm.complete(prompts.write_tests_messages(task.prompt, task.entry_point))
        run.tests = prompts.parse_tests(completion.text)
        run.tests_written_by_model = True
        run.test_writing = completion
        emit("tests", run.tests)
        if not run.tests:
            run.wall_time_s = round(time.perf_counter() - started, 3)
            return run

    if task.mode == "fix" and task.starter_code:
        run.baseline = run_tests(task.starter_code, run.tests, timeout_s)
        emit("baseline", run.baseline)
        messages = prompts.fix_messages(task.prompt, task.entry_point, run.tests, task.starter_code, run.baseline)
        kind: AttemptKind = "fix"
    else:
        messages = prompts.generate_messages(task.prompt, task.entry_point, run.tests)
        kind = "generate"

    for number in range(1, max_repairs + 2):
        completion = llm.complete(messages)
        code = prompts.extract_code(completion.text, task.entry_point)
        result = run_tests(code, run.tests, timeout_s)
        attempt = Attempt(number, kind, code, result, completion)
        run.attempts.append(attempt)
        emit("attempt", attempt)
        if result.all_passed:
            break
        messages = prompts.repair_messages(task.prompt, task.entry_point, run.tests, code, result)
        kind = "repair"

    run.wall_time_s = round(time.perf_counter() - started, 3)
    return run
