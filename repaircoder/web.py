"""FastAPI app: a single-page UI plus a JSON API that streams each attempt as it happens."""

from __future__ import annotations

import json
import queue
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from .config import Settings
from .history import HistoryStore, attempt_to_dict, result_to_dict
from .llm import LLM, CacheMiss, ReplayLLM, make_llm
from .loop import Attempt, solve
from .sandbox import SandboxResult
from .tasks import Task, load_benchmark, split_tests

STATIC = Path(__file__).with_name("static")


class SolveRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=4000)
    entry_point: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", max_length=80)
    tests: str = Field(default="", max_length=8000)
    mode: Literal["generate", "fix"] = "generate"
    starter_code: str | None = Field(default=None, max_length=20000)
    max_repairs: int = Field(default=3, ge=0, le=5)


def create_app(llm: LLM | None = None, store: HistoryStore | None = None, settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    model = llm or make_llm(settings)
    history = store or HistoryStore(settings.history_db)
    app = FastAPI(title="self-repair-coder", version="1.0.0")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        return {"mode": "replay" if isinstance(model, ReplayLLM) else "live", "model": model.model}

    @app.get("/api/examples")
    def examples() -> list[dict[str, Any]]:
        return [
            {
                "id": t.id,
                "mode": t.mode,
                "prompt": t.prompt,
                "entry_point": t.entry_point,
                "tests": "\n".join(t.tests),
                "starter_code": (t.starter_code or "").strip("\n"),
            }
            for t in load_benchmark()
        ]

    @app.post("/api/solve")
    def solve_endpoint(request: SolveRequest) -> StreamingResponse:
        if request.mode == "fix" and not (request.starter_code or "").strip():
            raise HTTPException(422, "Fix mode needs the code to fix.")
        task = Task(
            id="adhoc",
            prompt=request.prompt.strip(),
            entry_point=request.entry_point,
            tests=split_tests(request.tests),
            mode=request.mode,
            starter_code=(request.starter_code.strip("\n") + "\n") if request.mode == "fix" and request.starter_code else None,
        )
        events: queue.Queue[dict[str, Any] | None] = queue.Queue()

        def on_event(kind: str, payload: object) -> None:
            if kind == "attempt" and isinstance(payload, Attempt):
                events.put({"event": "attempt", **attempt_to_dict(payload)})
            elif kind == "baseline" and isinstance(payload, SandboxResult):
                events.put({"event": "baseline", "result": result_to_dict(payload)})
            elif kind == "tests":
                events.put({"event": "tests", "tests": payload})

        def worker() -> None:
            try:
                run = solve(task, model, max_repairs=request.max_repairs, timeout_s=settings.sandbox_timeout_s, on_event=on_event)
                run_id = history.add(run) if run.attempts else None
                events.put(
                    {
                        "event": "done",
                        "id": run_id,
                        "solved": run.solved,
                        "attempts": len(run.attempts),
                        "tests": run.tests,
                        "prompt_tokens": run.prompt_tokens,
                        "completion_tokens": run.completion_tokens,
                        "model_latency_s": run.model_latency_s,
                        "wall_time_s": run.wall_time_s,
                    }
                )
            except CacheMiss as exc:
                events.put({"event": "error", "message": str(exc)})
            except Exception as exc:  # noqa: BLE001 - surface model/API errors to the UI
                events.put({"event": "error", "message": f"{type(exc).__name__}: {exc}"[:300]})
            finally:
                events.put(None)

        threading.Thread(target=worker, daemon=True).start()

        def stream() -> Iterator[str]:
            while (item := events.get()) is not None:
                yield json.dumps(item) + "\n"

        return StreamingResponse(stream(), media_type="application/x-ndjson")

    @app.get("/api/history")
    def history_list() -> list[dict[str, Any]]:
        return history.list()

    @app.get("/api/history/{run_id}")
    def history_get(run_id: int) -> dict[str, Any]:
        found = history.get(run_id)
        if found is None:
            raise HTTPException(404, "No such run")
        return found

    @app.delete("/api/history/{run_id}")
    def history_delete(run_id: int) -> dict[str, bool]:
        if not history.delete(run_id):
            raise HTTPException(404, "No such run")
        return {"deleted": True}

    return app
