import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Every test gets a fresh SQLite file and no LLM key."""
    from finn import config
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "SNAPSHOT_PATH", tmp_path / "snapshot.json")
    monkeypatch.setattr(config, "LLM_FAST", config.LLMTier("http://x", "", ""))
    monkeypatch.setattr(config, "REFRESH_MINUTES", 0)
    yield tmp_path


def nse_items(now: datetime) -> list[dict]:
    """Synthetic NSE payload with timestamps placed relative to `now` (IST)."""
    raw = (FIX / "nse_announcements_sample.json").read_text()
    offsets = {"__T1__": 2, "__T2__": 5, "__T3__": 30, "__T4__": 40, "__T5__": 60, "__T6__": 70}
    for k, hrs in offsets.items():
        raw = raw.replace(k, (now - timedelta(hours=hrs)).strftime("%Y-%m-%d %H:%M:%S"))
    raw = raw.replace("__T7_ANDT__", (now - timedelta(hours=3)).strftime("%d-%b-%Y %H:%M:%S"))
    return json.loads(raw)


def bse_payload() -> dict:
    return json.loads((FIX / "bse_announcements_sample.json").read_text())
