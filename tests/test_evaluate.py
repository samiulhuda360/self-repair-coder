from pathlib import Path

from conftest import ScriptedLLM, fenced

from repaircoder.evaluate import render_markdown, run_benchmark, save_results
from repaircoder.tasks import Task

SQUARE = Task("square", "Return x squared.", "square", ["assert square(3) == 9"], ["assert square(-2) == 4"])
NEG = Task("neg", "Return -x.", "neg", ["assert neg(2) == -2"], ["assert neg(0) == 0"])


def test_first_try_versus_repair_and_hidden_tests() -> None:
    llm = ScriptedLLM(
        fenced("def square(x):\n    return x + x\n"),  # fails the visible test
        fenced("def square(x):\n    return x * x\n"),  # repaired
        fenced("def neg(x):\n    return -2 if x == 2 else 1\n"),  # passes the visible test, fails the hidden one
    )
    scores, summary = run_benchmark([SQUARE, NEG], llm, max_repairs=2)
    assert [s.attempts for s in scores] == [2, 1]
    assert scores[0].full_pass_by_attempt == [False, True]
    assert scores[1].visible_pass_by_attempt == [True] and scores[1].full_pass_by_attempt == [False]
    assert summary["first_try_pass_rate"] == 0.0
    assert summary["with_repair_pass_rate"] == 50.0
    assert summary["visible_tests_with_repair"] == 100.0
    assert summary["pass_rate_by_attempt_budget"] == {1: 0.0, 2: 50.0, 3: 50.0}
    assert summary["repaired_tasks"] == ["square"] and summary["unsolved_tasks"] == ["neg"]
    assert summary["model_calls"] == 3 and summary["total_tokens"] == 450


def test_results_are_written(tmp_path: Path) -> None:
    llm = ScriptedLLM(fenced("def square(x):\n    return x * x\n"))
    scores, summary = run_benchmark([SQUARE], llm)
    save_results(scores, summary, "scripted", tmp_path)
    assert (tmp_path / "results.json").exists()
    markdown = (tmp_path / "results.md").read_text(encoding="utf-8")
    assert "| Pass rate, first try | 100.0% |" in markdown
    assert markdown == render_markdown(scores, summary, "scripted")
