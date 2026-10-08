"""Benchmark: first-try pass rate versus pass rate with self-repair, plus tokens and latency."""

from __future__ import annotations

import json
import statistics
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .llm import LLM
from .loop import RunResult, solve
from .sandbox import run_tests
from .tasks import Task


@dataclass
class TaskScore:
    task_id: str
    mode: str
    attempts: int
    visible_pass_by_attempt: list[bool]
    full_pass_by_attempt: list[bool]
    prompt_tokens: int
    completion_tokens: int
    model_latency_s: float
    wall_time_s: float
    cached: bool

    def full_pass_within(self, k: int) -> bool:
        """Passed every test (visible and hidden) using at most k attempts."""
        seen = self.full_pass_by_attempt[:k]
        return bool(seen) and seen[-1]


def score_run(run: RunResult, timeout_s: float) -> TaskScore:
    full = [run_tests(a.code, run.task.all_tests, timeout_s).all_passed for a in run.attempts]
    return TaskScore(
        task_id=run.task.id,
        mode=run.task.mode,
        attempts=len(run.attempts),
        visible_pass_by_attempt=[a.passed for a in run.attempts],
        full_pass_by_attempt=full,
        prompt_tokens=run.prompt_tokens,
        completion_tokens=run.completion_tokens,
        model_latency_s=run.model_latency_s,
        wall_time_s=run.wall_time_s,
        cached=all(c.cached for c in run.completions()),
    )


def _rate(hits: int, total: int) -> float:
    return round(100 * hits / total, 1) if total else 0.0


def summarise(scores: list[TaskScore], max_repairs: int) -> dict[str, Any]:
    n = len(scores)
    budgets = list(range(1, max_repairs + 2))
    curve = {k: _rate(sum(s.full_pass_within(k) for s in scores), n) for k in budgets}
    by_mode: dict[str, dict[str, Any]] = {}
    for mode in sorted({s.mode for s in scores}):
        subset = [s for s in scores if s.mode == mode]
        by_mode[mode] = {
            "tasks": len(subset),
            "first_try": _rate(sum(s.full_pass_within(1) for s in subset), len(subset)),
            "with_repair": _rate(sum(s.full_pass_within(max_repairs + 1) for s in subset), len(subset)),
        }
    calls = [s.attempts for s in scores]
    tokens = [s.prompt_tokens + s.completion_tokens for s in scores]
    latency = [s.model_latency_s for s in scores]
    return {
        "tasks": n,
        "max_repairs": max_repairs,
        "first_try_pass_rate": curve[1],
        "with_repair_pass_rate": curve[max_repairs + 1],
        "visible_tests_first_try": _rate(sum(s.visible_pass_by_attempt[0] for s in scores if s.attempts), n),
        "visible_tests_with_repair": _rate(sum(s.visible_pass_by_attempt[-1] for s in scores if s.attempts), n),
        "pass_rate_by_attempt_budget": curve,
        "by_mode": by_mode,
        "repaired_tasks": [s.task_id for s in scores if not s.full_pass_within(1) and s.full_pass_within(max_repairs + 1)],
        "unsolved_tasks": [s.task_id for s in scores if not s.full_pass_within(max_repairs + 1)],
        "model_calls": sum(calls),
        "mean_calls_per_task": round(statistics.mean(calls), 2) if calls else 0,
        "total_tokens": sum(tokens),
        "mean_tokens_per_task": round(statistics.mean(tokens)) if tokens else 0,
        "mean_model_latency_s_per_task": round(statistics.mean(latency), 2) if latency else 0,
        "median_model_latency_s_per_task": round(statistics.median(latency), 2) if latency else 0,
    }


def run_benchmark(
    tasks: list[Task],
    llm: LLM,
    max_repairs: int = 3,
    timeout_s: float = 5.0,
    progress: Callable[[TaskScore], None] | None = None,
) -> tuple[list[TaskScore], dict[str, Any]]:
    scores = []
    for task in tasks:
        run = solve(task, llm, max_repairs=max_repairs, timeout_s=timeout_s)
        score = score_run(run, timeout_s)
        scores.append(score)
        if progress:
            progress(score)
    return scores, summarise(scores, max_repairs)


def render_markdown(scores: list[TaskScore], summary: dict[str, Any], model: str) -> str:
    k = summary["max_repairs"] + 1
    lines = [
        f"# Benchmark results ({model})",
        "",
        f"{summary['tasks']} tasks. A task counts as passed only when the final code passes the visible tests "
        "and the hidden tests the assistant never saw.",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Pass rate, first try | {summary['first_try_pass_rate']}% |",
        f"| Pass rate, with self-repair (up to {summary['max_repairs']} repairs) | {summary['with_repair_pass_rate']}% |",
        f"| Visible tests passed, first try / with repair | {summary['visible_tests_first_try']}% / {summary['visible_tests_with_repair']}% |",
        f"| Model calls (mean per task) | {summary['model_calls']} ({summary['mean_calls_per_task']}) |",
        f"| Tokens (mean per task) | {summary['total_tokens']} ({summary['mean_tokens_per_task']}) |",
        f"| Model latency per task, mean / median | {summary['mean_model_latency_s_per_task']} s / {summary['median_model_latency_s_per_task']} s |",
        "",
        "Pass rate by attempt budget: "
        + ", ".join(f"{b} attempt{'s' if int(b) > 1 else ''}: {r}%" for b, r in summary["pass_rate_by_attempt_budget"].items()),
        "",
        "| Task | Mode | Attempts | First try | Final | Tokens | Model latency (s) |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in scores:
        lines.append(
            f"| {s.task_id} | {s.mode} | {s.attempts} | {'pass' if s.full_pass_within(1) else 'fail'} | "
            f"{'pass' if s.full_pass_within(k) else 'fail'} | {s.prompt_tokens + s.completion_tokens} | {s.model_latency_s} |"
        )
    return "\n".join(lines) + "\n"


def save_results(scores: list[TaskScore], summary: dict[str, Any], model: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {"model": model, "summary": summary, "tasks": [s.__dict__ for s in scores]}
    (out_dir / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (out_dir / "results.md").write_text(render_markdown(scores, summary, model), encoding="utf-8")
