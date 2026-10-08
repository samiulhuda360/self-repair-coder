from conftest import ScriptedLLM, fenced

from repaircoder.loop import solve
from repaircoder.tasks import Task

TASK = Task(
    id="t",
    prompt="Write clamp(x, lo, hi) that limits x to the range lo..hi.",
    entry_point="clamp",
    tests=["assert clamp(5, 0, 3) == 3", "assert clamp(-1, 0, 3) == 0", "assert clamp(2, 0, 3) == 2"],
)
WRONG = "def clamp(x, lo, hi):\n    return min(x, hi)\n"
RIGHT = "def clamp(x, lo, hi):\n    return max(lo, min(x, hi))\n"


def test_first_try_success_uses_one_call() -> None:
    llm = ScriptedLLM(fenced(RIGHT))
    run = solve(TASK, llm)
    assert run.solved and run.first_try_passed
    assert len(run.attempts) == 1 and len(llm.calls) == 1
    assert run.attempts[0].kind == "generate"
    assert "assert clamp(5, 0, 3) == 3" in llm.calls[0][-1]["content"]


def test_failure_is_sent_back_and_repaired() -> None:
    llm = ScriptedLLM(fenced(WRONG), fenced(RIGHT))
    run = solve(TASK, llm)
    assert run.solved and not run.first_try_passed
    assert [a.kind for a in run.attempts] == ["generate", "repair"]
    repair_prompt = llm.calls[1][-1]["content"]
    assert "return min(x, hi)" in repair_prompt
    assert "expected 0, got -1" in repair_prompt
    assert run.prompt_tokens == 200 and run.completion_tokens == 100 and run.model_latency_s == 1.0


def test_repair_budget_is_respected() -> None:
    llm = ScriptedLLM(*[fenced(WRONG)] * 10)
    run = solve(TASK, llm, max_repairs=2)
    assert not run.solved
    assert len(run.attempts) == 3 and len(llm.calls) == 3


def test_zero_repairs_means_a_single_attempt() -> None:
    run = solve(TASK, ScriptedLLM(fenced(WRONG), fenced(RIGHT)), max_repairs=0)
    assert len(run.attempts) == 1 and not run.solved


def test_fix_mode_runs_the_broken_code_first() -> None:
    task = Task(id="f", prompt=TASK.prompt, entry_point="clamp", tests=TASK.tests, mode="fix", starter_code=WRONG)
    llm = ScriptedLLM(fenced(RIGHT))
    run = solve(task, llm)
    assert run.baseline is not None and run.baseline.passed == 2
    assert run.attempts[0].kind == "fix" and run.solved
    assert "1 of 3 failed" in llm.calls[0][-1]["content"]


def test_model_writes_tests_when_none_are_given() -> None:
    task = Task(id="w", prompt=TASK.prompt, entry_point="clamp", tests=[])
    written = "```python\nassert clamp(5, 0, 3) == 3\nassert clamp(1, 0, 3) == 1\n```"
    events: list[str] = []
    run = solve(task, ScriptedLLM(written, fenced(RIGHT)), on_event=lambda kind, _payload: events.append(kind))
    assert run.tests_written_by_model and run.tests == ["assert clamp(5, 0, 3) == 3", "assert clamp(1, 0, 3) == 1"]
    assert run.solved and events == ["tests", "attempt"]
    assert run.prompt_tokens == 200


def test_no_usable_tests_stops_early() -> None:
    task = Task(id="w", prompt=TASK.prompt, entry_point="clamp", tests=[])
    run = solve(task, ScriptedLLM("I cannot write tests."))
    assert run.tests == [] and run.attempts == [] and not run.solved
