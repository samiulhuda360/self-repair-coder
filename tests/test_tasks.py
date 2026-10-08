import pytest

from repaircoder.sandbox import run_tests
from repaircoder.tasks import Task, load_benchmark, split_tests

TASKS = load_benchmark()


def test_split_tests() -> None:
    block = "\n# comment\nassert f(1) == 1\nassert f(\n    2) == 2\n\nc = C(); assert c.x == 0\n"
    assert split_tests(block) == ["assert f(1) == 1", "assert f(\n    2) == 2", "c = C(); assert c.x == 0"]


def test_benchmark_shape() -> None:
    ids = [t.id for t in TASKS]
    assert len(ids) == len(set(ids)) == 35
    assert sum(t.mode == "fix" for t in TASKS) == 6
    for task in TASKS:
        assert task.tests and task.hidden_tests and task.reference, task.id
        assert not set(task.tests) & set(task.hidden_tests), task.id


@pytest.mark.parametrize("task", TASKS, ids=lambda t: t.id)
def test_reference_solution_passes_every_test(task: Task) -> None:
    assert task.reference is not None
    result = run_tests(task.reference, task.all_tests)
    assert result.all_passed, [(o.test, o.error) for o in result.failures()]


@pytest.mark.parametrize("task", [t for t in TASKS if t.mode == "fix"], ids=lambda t: t.id)
def test_broken_starter_code_fails_a_visible_test(task: Task) -> None:
    assert task.starter_code is not None
    assert not run_tests(task.starter_code, task.tests).all_passed
