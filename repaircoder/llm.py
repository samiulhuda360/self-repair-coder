"""Chat-model clients: a live OpenAI-compatible client with a disk cache, and a replay-only client.

Every response is cached on disk under a hash of (model, messages). With no API key the replay client
answers from that cache, so the recorded demo and benchmark still run offline.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from .config import Settings

Message = dict[str, str]

RATE_LIMIT_RETRIES = 3
RATE_LIMIT_BACKOFF_S = 30.0


@dataclass(frozen=True)
class Completion:
    text: str
    prompt_tokens: int
    completion_tokens: int
    latency_s: float
    cached: bool = False

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LLM(Protocol):
    model: str

    def complete(self, messages: list[Message]) -> Completion: ...


class CacheMiss(RuntimeError):
    """Raised by the replay client when a prompt has never been answered before."""


class DiskCache:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    @staticmethod
    def key(model: str, messages: list[Message]) -> str:
        blob = json.dumps({"model": model, "messages": messages}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def get(self, key: str) -> Completion | None:
        path = self._path(key)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return Completion(
            text=data["text"],
            prompt_tokens=data["prompt_tokens"],
            completion_tokens=data["completion_tokens"],
            latency_s=data["latency_s"],
            cached=True,
        )

    def put(self, key: str, completion: Completion) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        data = asdict(completion)
        data.pop("cached")
        self._path(key).write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


class ReplayLLM:
    """Answers only from the disk cache. Used when no API key is set, and in tests."""

    def __init__(self, model: str, cache: DiskCache) -> None:
        self.model = model
        self.cache = cache

    def complete(self, messages: list[Message]) -> Completion:
        hit = self.cache.get(DiskCache.key(self.model, messages))
        if hit is None:
            raise CacheMiss("No recorded answer for this prompt. Set AI_API_KEY to call the model live.")
        return hit


class OpenAICompatLLM:
    """Live client for any OpenAI-compatible endpoint, with a disk cache and a minimum gap between calls."""

    def __init__(
        self,
        settings: Settings,
        cache: DiskCache,
        client: Any | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model = settings.model
        self.cache = cache
        self.min_interval_s = settings.min_interval_s
        self._clock = clock
        self._sleep = sleep
        self._last_call: float | None = None
        self._lock = threading.Lock()
        if client is None:
            from openai import OpenAI

            client = OpenAI(api_key=settings.api_key, base_url=settings.base_url, max_retries=2, timeout=60)
        self._client: Any = client

    def _wait_turn(self) -> None:
        if self._last_call is not None:
            gap = self._clock() - self._last_call
            if gap < self.min_interval_s:
                self._sleep(self.min_interval_s - gap)
        self._last_call = self._clock()

    def complete(self, messages: list[Message]) -> Completion:
        key = DiskCache.key(self.model, messages)
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        with self._lock:
            for retry in range(RATE_LIMIT_RETRIES + 1):
                self._wait_turn()
                started = time.perf_counter()
                try:
                    response = self._client.chat.completions.create(model=self.model, messages=messages, temperature=0)
                    break
                except Exception as exc:
                    if getattr(exc, "status_code", None) != 429 or retry == RATE_LIMIT_RETRIES:
                        raise
                    self._sleep(RATE_LIMIT_BACKOFF_S * (retry + 1))
            latency = time.perf_counter() - started
        usage = getattr(response, "usage", None)
        completion = Completion(
            text=response.choices[0].message.content or "",
            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            latency_s=round(latency, 3),
        )
        self.cache.put(key, completion)
        return completion


def make_llm(settings: Settings | None = None) -> LLM:
    """Live client when AI_API_KEY is set, otherwise replay from the recorded cache."""
    settings = settings or Settings.from_env()
    cache = DiskCache(settings.cache_dir)
    if settings.api_key:
        return OpenAICompatLLM(settings, cache)
    return ReplayLLM(settings.model, cache)
