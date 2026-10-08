import json
from typing import Any

from conftest import ScriptedLLM, fenced
from fastapi.testclient import TestClient

from repaircoder.config import Settings
from repaircoder.history import HistoryStore
from repaircoder.llm import LLM, DiskCache, ReplayLLM
from repaircoder.web import create_app

BODY = {"prompt": "Write inc(x) that returns x + 1.", "entry_point": "inc", "tests": "assert inc(1) == 2\nassert inc(-1) == 0"}


def client_for(llm: LLM, settings: Settings) -> TestClient:
    return TestClient(create_app(llm=llm, store=HistoryStore(settings.history_db), settings=settings))


def events(response_text: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in response_text.splitlines() if line.strip()]


def test_index_status_and_examples(settings: Settings) -> None:
    client = client_for(ScriptedLLM(), settings)
    assert "Self-Repair Coder" in client.get("/").text
    assert client.get("/api/status").json() == {"mode": "live", "model": "scripted-test-model"}
    examples = client.get("/api/examples").json()
    assert len(examples) == 35 and {"id", "prompt", "entry_point", "tests", "mode"} <= set(examples[0])


def test_solve_streams_attempts_and_saves_history(settings: Settings) -> None:
    llm = ScriptedLLM(fenced("def inc(x):\n    return x\n"), fenced("def inc(x):\n    return x + 1\n"))
    client = client_for(llm, settings)
    stream = events(client.post("/api/solve", json=BODY).text)
    assert [e["event"] for e in stream] == ["attempt", "attempt", "done"]
    assert stream[0]["result"]["passed"] == 0 and stream[1]["result"]["all_passed"]
    done = stream[-1]
    assert done["solved"] and done["attempts"] == 2
    rows = client.get("/api/history").json()
    assert rows[0]["id"] == done["id"] and rows[0]["solved"] and rows[0]["entry_point"] == "inc"
    detail = client.get(f"/api/history/{done['id']}").json()
    assert detail["final_code"].strip() == "def inc(x):\n    return x + 1"
    assert client.delete(f"/api/history/{done['id']}").json() == {"deleted": True}
    assert client.get(f"/api/history/{done['id']}").status_code == 404


def test_fix_mode_sends_baseline_first(settings: Settings) -> None:
    client = client_for(ScriptedLLM(fenced("def inc(x):\n    return x + 1\n")), settings)
    body = {**BODY, "mode": "fix", "starter_code": "def inc(x):\n    return x - 1\n"}
    stream = events(client.post("/api/solve", json=body).text)
    assert [e["event"] for e in stream] == ["baseline", "attempt", "done"]
    assert stream[0]["result"]["passed"] == 0


def test_validation(settings: Settings) -> None:
    client = client_for(ScriptedLLM(), settings)
    assert client.post("/api/solve", json={**BODY, "mode": "fix"}).status_code == 422
    assert client.post("/api/solve", json={**BODY, "entry_point": "not valid"}).status_code == 422


def test_replay_miss_is_reported_not_crashed(settings: Settings) -> None:
    client = client_for(ReplayLLM("m", DiskCache(settings.cache_dir)), settings)
    assert client.get("/api/status").json()["mode"] == "replay"
    stream = events(client.post("/api/solve", json=BODY).text)
    assert stream[-1]["event"] == "error" and "AI_API_KEY" in stream[-1]["message"]
