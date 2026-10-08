from __future__ import annotations

from pathlib import Path

import pytest

from repaircoder.config import Settings
from repaircoder.llm import Completion, Message


class ScriptedLLM:
    """A fake model that returns canned replies in order and records every prompt."""

    model = "scripted-test-model"

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.calls: list[list[Message]] = []

    def complete(self, messages: list[Message]) -> Completion:
        self.calls.append(messages)
        text = self.replies.pop(0) if self.replies else "```python\npass\n```"
        return Completion(text=text, prompt_tokens=100, completion_tokens=50, latency_s=0.5)


def fenced(code: str) -> str:
    return f"Here you go:\n```python\n{code.strip()}\n```\n"


@pytest.fixture(autouse=True)
def no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never call a real model."""
    monkeypatch.delenv("AI_API_KEY", raising=False)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        api_key=None,
        base_url="http://localhost.invalid/v1",
        model="scripted-test-model",
        cache_dir=tmp_path / "cache",
        min_interval_s=2.5,
        sandbox_timeout_s=5.0,
        max_repairs=3,
        history_db=tmp_path / "history.sqlite3",
    )
