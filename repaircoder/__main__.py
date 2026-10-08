"""Command line: solve, fix, bench, demo and serve."""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

from .config import ROOT, Settings
from .evaluate import TaskScore, render_markdown, run_benchmark, save_results
from .llm import CacheMiss, ReplayLLM, make_llm
from .loop import Attempt, RunResult, solve
from .tasks import Task, load_benchmark, split_tests

DEMO_TASK = "parse_duration"


def _print_attempt(kind: str, payload: object) -> None:
    if kind == "tests" and isinstance(payload, list):
        print(f"The model wrote {len(payload)} tests from the description:")
        for test in payload:
            print(f"    {test}")
    if kind == "attempt" and isinstance(payload, Attempt):
        a = payload
        c = a.completion
        status = "PASS" if a.passed else "FAIL"
        source = "recorded" if c.cached else "live"
        print(
            f"Attempt {a.number} ({a.kind}): {status} {a.result.passed}/{a.result.total} tests | "
            f"{c.total_tokens} tokens | {c.latency_s:.1f} s model ({source}) | {a.result.duration_s:.2f} s sandbox"
        )
        if a.result.load_error:
            print(f"    x the module failed to load: {a.result.load_error}")
            return
        for outcome in a.result.failures()[:4]:
            print(f"    x {outcome.test}\n      {outcome.error}")


def _print_summary(run: RunResult, show_code: bool = True) -> None:
    if show_code and run.attempts:
        print("\nFinal code:\n" + "-" * 60 + "\n" + run.final_code.rstrip() + "\n" + "-" * 60)
    verdict = "Solved" if run.solved else "Not solved"
    print(
        f"{verdict} in {len(run.attempts)} attempt(s): {run.prompt_tokens + run.completion_tokens} tokens, "
        f"{run.model_latency_s:.1f} s in the model, {run.wall_time_s:.1f} s total."
    )


def _read_tests(args: argparse.Namespace) -> list[str]:
    tests: list[str] = list(args.test or [])
    if args.tests:
        tests += split_tests(Path(args.tests).read_text(encoding="utf-8"))
    return tests


def cmd_solve(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    task = Task(id="cli", prompt=args.prompt, entry_point=args.entry, tests=_read_tests(args))
    run = solve(task, make_llm(settings), max_repairs=args.max_repairs, timeout_s=settings.sandbox_timeout_s, on_event=_print_attempt)
    _print_summary(run)
    if args.out and run.attempts:
        Path(args.out).write_text(run.final_code, encoding="utf-8")
        print(f"Wrote {args.out}")
    return 0 if run.solved else 1


def cmd_fix(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    code = Path(args.file).read_text(encoding="utf-8")
    task = Task(id="cli", prompt=args.prompt, entry_point=args.entry, tests=_read_tests(args), mode="fix", starter_code=code)
    if not task.tests:
        print("Fix mode needs tests (--test or --tests) to show what is broken.", file=sys.stderr)
        return 2

    def on_event(kind: str, payload: object) -> None:
        if kind == "baseline":
            print(f"Your code: {getattr(payload, 'passed', 0)}/{getattr(payload, 'total', 0)} tests pass")
        _print_attempt(kind, payload)

    run = solve(task, make_llm(settings), max_repairs=args.max_repairs, timeout_s=settings.sandbox_timeout_s, on_event=on_event)
    _print_summary(run)
    if args.write and run.solved:
        Path(args.file).write_text(run.final_code, encoding="utf-8")
        print(f"Updated {args.file}")
    return 0 if run.solved else 1


def cmd_bench(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    llm = make_llm(settings)
    tasks = load_benchmark()
    if args.only:
        wanted = set(args.only.split(","))
        tasks = [t for t in tasks if t.id in wanted]

    def progress(score: TaskScore) -> None:
        trail = " -> ".join("pass" if ok else "fail" for ok in score.full_pass_by_attempt)
        print(f"  {score.task_id:<22} {score.mode:<9} {trail}")

    print(f"Running {len(tasks)} tasks with {llm.model} ({'replay' if isinstance(llm, ReplayLLM) else 'live'}), up to {args.max_repairs} repairs")
    scores, summary = run_benchmark(tasks, llm, max_repairs=args.max_repairs, timeout_s=settings.sandbox_timeout_s, progress=progress)
    print()
    print(render_markdown(scores, summary, llm.model).split("| Task |")[0].strip())
    if not args.only:
        save_results(scores, summary, llm.model, Path(args.out))
        print(f"\nSaved {args.out}/results.json and results.md")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    task = next(t for t in load_benchmark() if t.id == args.task)
    llm = make_llm(settings)
    print(f"Task ({task.id}):\n{task.prompt}\n")
    print("Tests the assistant must pass:")
    for test in task.tests:
        print(f"    {test}")
    print()
    run = solve(task, llm, max_repairs=3, timeout_s=settings.sandbox_timeout_s, on_event=_print_attempt)
    _print_summary(run, show_code=args.code)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .web import create_app

    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="warning")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="repaircoder", description="Turn a plain-English task into tested Python code.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("solve", help="write code for a task and repair it until the tests pass")
    p.add_argument("prompt", help="what the code should do")
    p.add_argument("--entry", required=True, help="function or class name to implement")
    p.add_argument("--test", action="append", help="an assert statement (repeatable)")
    p.add_argument("--tests", help="file of assert statements, one per line")
    p.add_argument("--max-repairs", type=int, default=3)
    p.add_argument("--out", help="write the final code to this file")
    p.set_defaults(func=cmd_solve)

    p = sub.add_parser("fix", help="fix a broken Python file against tests")
    p.add_argument("file")
    p.add_argument("--entry", required=True)
    p.add_argument("--prompt", required=True, help="what the code is meant to do")
    p.add_argument("--test", action="append")
    p.add_argument("--tests")
    p.add_argument("--max-repairs", type=int, default=3)
    p.add_argument("--write", action="store_true", help="overwrite the file with the fixed code")
    p.set_defaults(func=cmd_fix)

    p = sub.add_parser("bench", help="run the benchmark")
    p.add_argument("--max-repairs", type=int, default=3)
    p.add_argument("--only", help="comma-separated task ids")
    p.add_argument("--out", default=str(ROOT / "eval"))
    p.set_defaults(func=cmd_bench)

    p = sub.add_parser("demo", help="run one benchmark task and show each attempt")
    p.add_argument("--task", default=DEMO_TASK)
    p.add_argument("--code", action="store_true", help="print the final code")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("serve", help="start the web UI")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except CacheMiss as exc:
        print(f"{exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
