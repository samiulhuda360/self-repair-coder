"""Run history in SQLite, so past runs can be reopened from the web UI."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .loop import Attempt, RunResult
from .sandbox import SandboxResult

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    mode TEXT NOT NULL,
    entry_point TEXT NOT NULL,
    prompt TEXT NOT NULL,
    solved INTEGER NOT NULL,
    attempts INTEGER NOT NULL,
    tokens INTEGER NOT NULL,
    model_latency_s REAL NOT NULL,
    final_code TEXT NOT NULL,
    detail TEXT NOT NULL
)
"""


def result_to_dict(result: SandboxResult) -> dict[str, Any]:
    return {
        "passed": result.passed,
        "total": result.total,
        "all_passed": result.all_passed,
        "timed_out": result.timed_out,
        "load_error": result.load_error,
        "duration_s": result.duration_s,
        "outcomes": [{"test": o.test, "passed": o.passed, "error": o.error} for o in result.outcomes],
    }


def attempt_to_dict(attempt: Attempt) -> dict[str, Any]:
    c = attempt.completion
    return {
        "number": attempt.number,
        "kind": attempt.kind,
        "code": attempt.code,
        "result": result_to_dict(attempt.result),
        "prompt_tokens": c.prompt_tokens,
        "completion_tokens": c.completion_tokens,
        "latency_s": c.latency_s,
        "cached": c.cached,
    }


def run_to_dict(run: RunResult) -> dict[str, Any]:
    return {
        "mode": run.task.mode,
        "entry_point": run.task.entry_point,
        "prompt": run.task.prompt,
        "tests": run.tests,
        "tests_written_by_model": run.tests_written_by_model,
        "baseline": result_to_dict(run.baseline) if run.baseline else None,
        "attempts": [attempt_to_dict(a) for a in run.attempts],
        "solved": run.solved,
        "final_code": run.final_code,
        "prompt_tokens": run.prompt_tokens,
        "completion_tokens": run.completion_tokens,
        "model_latency_s": run.model_latency_s,
        "wall_time_s": run.wall_time_s,
    }


class HistoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(SCHEMA)
        self._conn.commit()

    def add(self, run: RunResult) -> int:
        detail = run_to_dict(run)
        cursor = self._conn.execute(
            "INSERT INTO runs (created_at, mode, entry_point, prompt, solved, attempts, tokens, model_latency_s, final_code, detail)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now(UTC).isoformat(timespec="seconds"),
                run.task.mode,
                run.task.entry_point,
                run.task.prompt,
                int(run.solved),
                len(run.attempts),
                run.prompt_tokens + run.completion_tokens,
                run.model_latency_s,
                run.final_code,
                json.dumps(detail),
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid or 0)

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, created_at, mode, entry_point, prompt, solved, attempts, tokens, model_latency_s FROM runs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [{**dict(row), "solved": bool(row["solved"])} for row in rows]

    def get(self, run_id: int) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT id, created_at, detail FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return {"id": row["id"], "created_at": row["created_at"], **json.loads(row["detail"])}

    def delete(self, run_id: int) -> bool:
        cursor = self._conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
        self._conn.commit()
        return cursor.rowcount > 0
