"""SQLite storage. Plain sqlite3 with a small schema — no ORM, so every query
is visible and easy to reason about.

Timestamps are stored as UTC ISO-8601 strings ("2026-11-14T13:00:12Z"), which
sort and compare correctly as text."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    symbol       TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    sector       TEXT,
    bse_code     TEXT,
    financial    INTEGER NOT NULL DEFAULT 0,   -- banks/NBFCs: EBITDA not meaningful
    in_portfolio INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS prices (
    symbol TEXT NOT NULL,
    date   TEXT NOT NULL,          -- trading date, YYYY-MM-DD (exchange local)
    open REAL, high REAL, low REAL, close REAL,
    volume INTEGER,
    source TEXT NOT NULL,          -- 'yahoo' | 'snapshot'
    PRIMARY KEY (symbol, date)
);

CREATE TABLE IF NOT EXISTS announcements (
    id             TEXT PRIMARY KEY,   -- '<source>:<exchange id>'
    symbol         TEXT NOT NULL,
    source         TEXT NOT NULL,      -- 'nse' | 'bse' | 'snapshot'
    published_at   TEXT NOT NULL,      -- UTC ISO
    subject        TEXT NOT NULL,      -- exchange's own subject/category line
    body           TEXT,               -- exchange's short description
    attachment_url TEXT,
    category       TEXT,
    sub_type       TEXT,
    classified_by  TEXT,               -- 'rule:<id>' | 'llm:<model>' | 'default'
    priority       INTEGER,
    tier           TEXT,               -- 'high' | 'medium' | 'routine'
    summary        TEXT,               -- one-line summary (LLM) when useful
    enrichment     TEXT,               -- JSON blob (results table, appointee profile…)
    fetched_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ann_time ON announcements(published_at);
CREATE INDEX IF NOT EXISTS ix_ann_symbol ON announcements(symbol, published_at);

CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,         -- 'price' | 'volume' | 'announcement'
    symbol      TEXT NOT NULL,
    ref         TEXT,                  -- trading date or announcement id
    message     TEXT NOT NULL,
    value       REAL,
    threshold   REAL,
    created_at  TEXT NOT NULL,
    seen        INTEGER NOT NULL DEFAULT 0,
    dedupe_key  TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL                -- JSON
);

CREATE TABLE IF NOT EXISTS source_status (
    source        TEXT PRIMARY KEY,    -- 'nse' | 'bse' | 'yahoo' | 'llm'
    last_ok       TEXT,
    last_error    TEXT,
    last_error_at TEXT,
    detail        TEXT
);

CREATE TABLE IF NOT EXISTS llm_cache (
    key        TEXT PRIMARY KEY,       -- sha256 of (task, prompt version, model, input)
    task       TEXT NOT NULL,
    model      TEXT NOT NULL,
    response   TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_calls (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    task              TEXT NOT NULL,
    model             TEXT NOT NULL,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    cached            INTEGER NOT NULL,
    latency_ms        INTEGER,
    ok                INTEGER NOT NULL,
    error             TEXT,
    created_at        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    id          TEXT PRIMARY KEY,      -- sha1 of url (stable)
    symbol      TEXT NOT NULL,
    kind        TEXT NOT NULL,         -- 'results' | 'transcript' | 'presentation'
    period_end  TEXT,                  -- quarter end the document reports on (YYYY-MM-DD)
    title       TEXT,
    url         TEXT NOT NULL,
    source      TEXT NOT NULL,         -- 'nse'
    filed_at    TEXT,                  -- UTC ISO
    sha256      TEXT,
    pages       INTEGER,
    text_pages  INTEGER,               -- pages with extractable text (0 → scanned)
    local_path  TEXT,
    status      TEXT NOT NULL DEFAULT 'found',   -- found | downloaded | failed
    error       TEXT
);
CREATE INDEX IF NOT EXISTS ix_docs_symbol ON documents(symbol, kind, period_end);

CREATE TABLE IF NOT EXISTS doc_pages (
    doc_id  TEXT NOT NULL,
    page_no INTEGER NOT NULL,          -- 1-based, as a reader would cite it
    text    TEXT NOT NULL,
    PRIMARY KEY (doc_id, page_no)
);

CREATE TABLE IF NOT EXISTS extractions (
    doc_id     TEXT NOT NULL,
    task       TEXT NOT NULL,          -- 'results' | 'guidance'
    version    TEXT NOT NULL,
    data       TEXT NOT NULL,          -- JSON
    created_at TEXT NOT NULL,
    PRIMARY KEY (doc_id, task, version)
);

CREATE TABLE IF NOT EXISTS dossiers (
    symbol     TEXT PRIMARY KEY,
    status     TEXT NOT NULL,          -- queued | running | ready | failed
    step       TEXT,
    progress   TEXT,                   -- JSON list of {step, state, detail}
    data       TEXT,                   -- JSON dossier
    error      TEXT,
    doc_fingerprint TEXT,              -- hash of the document set used → rebuild only when it changes
    started_at TEXT,
    built_at   TEXT
);
"""

_lock = threading.Lock()
LOCK_TIMEOUT = 30  # seconds a connection waits for another writer to finish
_initialised: set[str] = set()


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("naive datetime")
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=LOCK_TIMEOUT, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # readers don't block the writer
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def connect(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    path = Path(path or config.DB_PATH)
    conn = _connect(path)
    try:
        key = str(path)
        if key not in _initialised:
            with _lock:
                conn.executescript(SCHEMA)
                _initialised.add(key)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---- settings -------------------------------------------------------------

DEFAULT_SETTINGS: dict[str, Any] = {
    # A day's price move beyond ±price_move_pct triggers an alert.
    "price_move_pct": 4.0,
    # Volume above volume_multiple × trailing average triggers an alert.
    "volume_multiple": 2.0,
    "volume_lookback_days": 20,
    # Announcement categories the investor wants alerts for.
    "watched_categories": ["results", "M&A", "management_change", "fund_raise",
                           "litigation", "credit_rating", "pledging"],
    # Announcements at or above this priority score raise an alert.
    "announcement_alert_min_priority": 70,
    "last_seen_at": None,
}


def get_settings(conn: sqlite3.Connection) -> dict[str, Any]:
    out = dict(DEFAULT_SETTINGS)
    for row in conn.execute("SELECT key, value FROM settings"):
        out[row["key"]] = json.loads(row["value"])
    return out


def put_settings(conn: sqlite3.Connection, values: dict[str, Any]) -> None:
    for k, v in values.items():
        if k not in DEFAULT_SETTINGS:
            raise KeyError(f"unknown setting {k}")
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (k, json.dumps(v)),
        )


# ---- source status --------------------------------------------------------

def mark_source(conn: sqlite3.Connection, source: str, ok: bool,
                error: str | None = None, detail: str | None = None) -> None:
    now = utcnow()
    conn.execute("INSERT OR IGNORE INTO source_status(source) VALUES(?)", (source,))
    if ok:
        conn.execute("UPDATE source_status SET last_ok=?, detail=? WHERE source=?",
                     (now, detail, source))
    else:
        conn.execute("UPDATE source_status SET last_error=?, last_error_at=?, detail=? "
                     "WHERE source=?", ((error or "")[:500], now, detail, source))


def source_status(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT * FROM source_status ORDER BY source")]
