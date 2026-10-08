"""Runtime settings, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
DEFAULT_MODEL = "gemini-flash-lite-latest"


@dataclass(frozen=True)
class Settings:
    api_key: str | None
    base_url: str
    model: str
    cache_dir: Path
    min_interval_s: float
    sandbox_timeout_s: float
    max_repairs: int
    history_db: Path

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        return cls(
            api_key=env.get("AI_API_KEY") or None,
            base_url=env.get("AI_BASE_URL", DEFAULT_BASE_URL),
            model=env.get("AI_MODEL", DEFAULT_MODEL),
            cache_dir=Path(env.get("REPAIRCODER_CACHE", str(ROOT / "cache" / "llm"))),
            min_interval_s=max(2.5, float(env.get("AI_MIN_INTERVAL", "2.5"))),
            sandbox_timeout_s=float(env.get("SANDBOX_TIMEOUT", "5")),
            max_repairs=int(env.get("MAX_REPAIRS", "3")),
            history_db=Path(env.get("REPAIRCODER_DB", str(ROOT / "data" / "history.sqlite3"))),
        )
