"""Central configuration. Everything tunable comes from environment variables
(loaded from a .env file in the repo root if present), so nothing secret or
deployment-specific is hard-coded."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")

IST = ZoneInfo("Asia/Kolkata")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class LLMTier:
    """One model tier. 'fast' is used for bulk work (classification,
    extraction); 'deep' only where reasoning matters (narrative analysis)."""
    base_url: str
    api_key: str
    model: str
    reasoning_effort: str = ""   # "low"/"medium"/"high" for thinking models; "" = provider default
    timeout: float = 120.0

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.model and self.base_url)


GEMINI_OPENAI_URL = "https://generativelanguage.googleapis.com/v1beta/openai"


def _tier(prefix: str, default_model: str, effort: str = "", timeout: float = 120.0) -> LLMTier:
    return LLMTier(
        base_url=_env(f"{prefix}_BASE_URL", GEMINI_OPENAI_URL).rstrip("/"),
        api_key=_env(f"{prefix}_API_KEY", _env("GEMINI_API_KEY")),
        model=_env(f"{prefix}_MODEL", default_model),
        reasoning_effort=_env(f"{prefix}_REASONING_EFFORT", effort),
        timeout=float(_env(f"{prefix}_TIMEOUT", str(timeout))),
    )


DB_PATH = Path(_env("FINN_DB", str(REPO_ROOT / "data" / "finn.db")))
PORTFOLIO_PATH = Path(_env("FINN_PORTFOLIO", str(REPO_ROOT / "data" / "portfolio.json")))
SNAPSHOT_PATH = Path(_env("FINN_SNAPSHOT", str(REPO_ROOT / "data" / "snapshot.json.gz")))
DOC_DIR = Path(_env("FINN_DOC_DIR", str(DB_PATH.parent / "docs")))   # cached PDFs
STATIC_DIR = Path(_env("FINN_STATIC", str(REPO_ROOT / "backend" / "static")))

LLM_FAST = _tier("FINN_FAST", "gemini-flash-lite-latest")
# Thinking models can take minutes on long transcripts: keep reasoning short, wait longer.
LLM_DEEP = _tier("FINN_DEEP", "gemini-flash-latest", effort="low", timeout=300.0)

# Background refresh interval (minutes). 0 disables the scheduler.
REFRESH_MINUTES = int(_env("FINN_REFRESH_MINUTES", "30") or 0)
# How many days of announcements to backfill on each refresh.
ANNOUNCEMENT_LOOKBACK_DAYS = int(_env("FINN_LOOKBACK_DAYS", "10"))

# New (uncached) research builds allowed per hour, so a public deployment can't
# exhaust the model quota. 0 = unlimited.
MAX_BUILDS_PER_HOUR = int(_env("FINN_MAX_BUILDS_PER_HOUR", "6") or 0)
