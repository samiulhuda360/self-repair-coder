from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from repaircoder.config import Settings
from repaircoder.llm import CacheMiss, Completion, DiskCache, OpenAICompatLLM, ReplayLLM, make_llm

MESSAGES = [{"role": "user", "content": "write add(a, b)"}]


class FakeClient:
    def __init__(self, failures: int = 0) -> None:
        self.requests: list[dict[str, Any]] = []
        self.failures = failures
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        if self.failures:
            self.failures -= 1
            error = RuntimeError("rate limited")
            error.status_code = 429  # type: ignore[attr-defined]
            raise error
        message = SimpleNamespace(content="```python\ndef add(a, b):\n    return a + b\n```")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=SimpleNamespace(prompt_tokens=12, completion_tokens=8))


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_disk_cache_round_trip(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path)
    key = DiskCache.key("m", MESSAGES)
    assert cache.get(key) is None
    cache.put(key, Completion("hello", 3, 4, 1.25))
    hit = cache.get(key)
    assert hit == Completion("hello", 3, 4, 1.25, cached=True)
    assert DiskCache.key("other-model", MESSAGES) != key


def test_replay_answers_from_cache_or_raises(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path)
    replay = ReplayLLM("m", cache)
    with pytest.raises(CacheMiss):
        replay.complete(MESSAGES)
    cache.put(DiskCache.key("m", MESSAGES), Completion("hi", 1, 1, 0.1))
    assert replay.complete(MESSAGES).text == "hi"


def test_live_client_caches_and_records_usage(settings: Settings) -> None:
    client = FakeClient()
    llm = OpenAICompatLLM(replace(settings, api_key="test-key-not-real"), DiskCache(settings.cache_dir), client=client)
    first = llm.complete(MESSAGES)
    second = llm.complete(MESSAGES)
    assert len(client.requests) == 1
    assert client.requests[0]["temperature"] == 0 and client.requests[0]["model"] == settings.model
    assert (first.prompt_tokens, first.completion_tokens, first.cached) == (12, 8, False)
    assert second.cached and second.text == first.text


def test_live_client_spaces_calls(settings: Settings) -> None:
    clock = FakeClock()
    llm = OpenAICompatLLM(settings, DiskCache(settings.cache_dir), client=FakeClient(), clock=clock.time, sleep=clock.sleep)
    llm.complete([{"role": "user", "content": "one"}])
    clock.now += 1.0
    llm.complete([{"role": "user", "content": "two"}])
    assert clock.sleeps == [pytest.approx(1.5)]


def test_live_client_retries_rate_limits(settings: Settings) -> None:
    clock = FakeClock()
    client = FakeClient(failures=2)
    llm = OpenAICompatLLM(settings, DiskCache(settings.cache_dir), client=client, clock=clock.time, sleep=clock.sleep)
    assert "def add" in llm.complete(MESSAGES).text
    assert len(client.requests) == 3
    assert clock.sleeps == [30.0, 60.0]


def test_min_interval_cannot_go_below_2_5_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_MIN_INTERVAL", "0.1")
    assert Settings.from_env().min_interval_s == 2.5


def test_make_llm_without_key_is_replay(settings: Settings) -> None:
    assert isinstance(make_llm(settings), ReplayLLM)
