"""FastAPI application: JSON API under /api, built frontend served at /."""
from __future__ import annotations

import logging
import re
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, db, llm
from .pipeline import alerts as alert_rules
from .pipeline import ingest
from .pipeline.classify import CATEGORIES
from .portfolio import sync_companies
from .text import headline

log = logging.getLogger("finn")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")


# ---- background refresh ---------------------------------------------------------

def _scheduler(stop: threading.Event):
    if config.REFRESH_MINUTES <= 0:
        return
    stop.wait(5)
    while not stop.is_set():
        try:
            log.info("scheduled refresh: %s", ingest.refresh())
        except Exception:
            log.exception("scheduled refresh failed")
        stop.wait(config.REFRESH_MINUTES * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    with db.connect() as conn:
        sync_companies(conn)
        ingest.rescore_all(conn, db.get_settings(conn))   # priority table may have changed
    snap = ingest.load_snapshot_if_empty()
    if snap:
        log.info("loaded snapshot: %s", snap)
    stop = threading.Event()
    t = threading.Thread(target=_scheduler, args=(stop,), daemon=True)
    t.start()
    yield
    stop.set()


app = FastAPI(title="FINN", lifespan=lifespan)


# ---- helpers ------------------------------------------------------------------------

WINDOWS = {"24h": timedelta(hours=24), "3d": timedelta(days=3), "7d": timedelta(days=7), "30d": timedelta(days=30)}


def _resolve_window(key: str, start: str | None, end: str | None, settings: dict) -> tuple[datetime, datetime, str]:
    now = datetime.now(timezone.utc)
    if key == "custom":
        if not start:
            raise HTTPException(400, "custom window needs 'from'")
        try:
            s = datetime.fromisoformat(start.replace("Z", "+00:00"))
            e = datetime.fromisoformat(end.replace("Z", "+00:00")) if end else now
        except ValueError:
            raise HTTPException(400, "dates must be ISO-8601")
        if s.tzinfo is None:
            s = s.replace(tzinfo=config.IST)
        if e.tzinfo is None:
            e = e.replace(tzinfo=config.IST)
        return s, e, "Custom range"
    if key == "since_last":
        last = settings.get("last_seen_at")
        if last:
            return db.parse_utc(last), now, "Since you last looked"
        return now - WINDOWS["24h"], now, "Last 24 hours"
    if key not in WINDOWS:
        raise HTTPException(400, f"window must be one of {list(WINDOWS)} / since_last / custom")
    labels = {"24h": "Last 24 hours", "3d": "Last 3 days", "7d": "Last 7 days", "30d": "Last 30 days"}
    return now - WINDOWS[key], now, labels[key]


def _data_mode(conn) -> dict:
    st = {r["source"]: r for r in db.source_status(conn)}
    live = any(st.get(s, {}).get("last_ok") for s in ("nse", "bse"))
    snap = st.get("snapshot")
    if live:
        return {"mode": "live"}
    if snap and snap.get("last_ok"):
        return {"mode": "snapshot", "detail": snap.get("detail")}
    return {"mode": "empty"}


def _ann_row(r, names: dict[str, str]) -> dict:
    d = dict(r)
    d["company"] = names.get(d["symbol"], d["symbol"])
    d["headline"] = headline(d["subject"], d["body"], d["summary"])
    d.pop("enrichment", None)
    return d


# ---- endpoints ----------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"ok": True, "time": db.utcnow(), "llm_fast": config.LLM_FAST.enabled, "llm_deep": config.LLM_DEEP.enabled}


@app.get("/api/feed")
def feed(window: str = "24h", start: str | None = Query(None, alias="from"),
         end: str | None = Query(None, alias="to")):
    with db.connect() as conn:
        settings = db.get_settings(conn)
        s, e, label = _resolve_window(window, start, end, settings)
        names = {r["symbol"]: r["name"] for r in conn.execute("SELECT symbol, name FROM companies")}
        rows = conn.execute(
            "SELECT a.* FROM announcements a JOIN companies c ON c.symbol=a.symbol AND c.in_portfolio=1 "
            "WHERE a.published_at >= ? AND a.published_at <= ? ORDER BY a.priority DESC, a.published_at DESC",
            (db.to_utc_iso(s), db.to_utc_iso(e))).fetchall()
        alerted = {r["ref"] for r in conn.execute("SELECT ref FROM alerts WHERE kind='announcement'")}
        groups: dict[str, list] = {"high": [], "medium": [], "routine": []}
        counts: dict[str, int] = {}
        for r in rows:
            d = _ann_row(r, names)
            d["alerted"] = d["id"] in alerted
            groups[d["tier"] or "routine"].append(d)
            counts[d["category"]] = counts.get(d["category"], 0) + 1
        # Market alerts are tied to trading dates (IST), not timestamps.
        # The latest session's moves are always shown (otherwise a Sunday
        # 24h view would hide Friday's alerts); older ones only inside the window.
        start_date = s.astimezone(config.IST).date().isoformat()
        latest = conn.execute("SELECT MAX(date) FROM prices").fetchone()[0] or start_date
        market = [dict(r) for r in conn.execute(
            "SELECT * FROM alerts WHERE kind IN ('price','volume') AND (ref >= ? OR ref = ?) "
            "ORDER BY ref DESC, ABS(value) DESC", (min(start_date, latest), latest))]
        for m in market:
            m["company"] = names.get(m["symbol"], m["symbol"])
        return {"window": {"key": window, "from": db.to_utc_iso(s), "to": db.to_utc_iso(e), "label": label},
                "data": _data_mode(conn), "market_alerts": market, "groups": groups,
                "counts": counts, "total": len(rows)}


@app.post("/api/feed/seen")
def mark_feed_seen():
    with db.connect() as conn:
        db.put_settings(conn, {"last_seen_at": db.utcnow()})
    return {"ok": True}


@app.get("/api/announcements/{ann_id:path}")
def announcement(ann_id: str):
    with db.connect() as conn:
        r = conn.execute("SELECT * FROM announcements WHERE id=?", (ann_id,)).fetchone()
        if not r:
            raise HTTPException(404, "not found")
        names = {x["symbol"]: x["name"] for x in conn.execute("SELECT symbol, name FROM companies")}
        d = dict(r)
        d["company"] = names.get(d["symbol"], d["symbol"])
        return d


@app.get("/api/portfolio")
def portfolio():
    with db.connect() as conn:
        settings = db.get_settings(conn)
        since7 = db.to_utc_iso(datetime.now(timezone.utc) - timedelta(days=7))
        out = []
        for c in conn.execute("SELECT * FROM companies WHERE in_portfolio=1 ORDER BY symbol"):
            m = alert_rules.eod_metrics(conn, c["symbol"], int(settings["volume_lookback_days"]))
            spark = [r["close"] for r in conn.execute(
                "SELECT close FROM (SELECT date, close FROM prices WHERE symbol=? ORDER BY date DESC LIMIT 60) "
                "ORDER BY date", (c["symbol"],))]
            top = conn.execute("SELECT id, subject, body, summary, category, priority, published_at FROM announcements "
                               "WHERE symbol=? AND published_at>=? AND tier!='routine' ORDER BY priority DESC, published_at DESC LIMIT 1",
                               (c["symbol"], since7)).fetchone()
            n7 = conn.execute("SELECT COUNT(*) FROM announcements WHERE symbol=? AND published_at>=? AND tier!='routine'",
                              (c["symbol"], since7)).fetchone()[0]
            src = conn.execute("SELECT source FROM prices WHERE symbol=? ORDER BY date DESC LIMIT 1",
                               (c["symbol"],)).fetchone()
            out.append({"symbol": c["symbol"], "name": c["name"], "sector": c["sector"],
                        "financial": bool(c["financial"]), "eod": m, "spark": spark,
                        "price_source": src["source"] if src else None,
                        "notable_7d": n7,
                        "top_filing": ({**dict(top), "headline": headline(top["subject"], top["body"], top["summary"])}
                                       if top else None)})
        return {"holdings": out, "data": _data_mode(conn), "thresholds": {
            "price_move_pct": settings["price_move_pct"], "volume_multiple": settings["volume_multiple"]}}


@app.get("/api/alerts")
def list_alerts(limit: int = 50):
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM alerts ORDER BY created_at DESC, id DESC LIMIT ?", (limit,))]
        unseen = conn.execute("SELECT COUNT(*) FROM alerts WHERE seen=0").fetchone()[0]
    return {"alerts": rows, "unseen": unseen}


@app.post("/api/alerts/seen")
def alerts_seen():
    with db.connect() as conn:
        conn.execute("UPDATE alerts SET seen=1 WHERE seen=0")
    return {"ok": True}


class SettingsIn(BaseModel):
    price_move_pct: float | None = Field(None, ge=0.5, le=50)
    volume_multiple: float | None = Field(None, ge=1.1, le=20)
    volume_lookback_days: int | None = Field(None, ge=5, le=120)
    watched_categories: list[str] | None = None
    announcement_alert_min_priority: int | None = Field(None, ge=0, le=100)


@app.get("/api/settings")
def get_settings():
    with db.connect() as conn:
        s = db.get_settings(conn)
    return {"settings": s, "categories": CATEGORIES}


@app.put("/api/settings")
def put_settings(body: SettingsIn):
    values = body.model_dump(exclude_none=True)
    if "watched_categories" in values:
        bad = set(values["watched_categories"]) - set(CATEGORIES)
        if bad:
            raise HTTPException(400, f"unknown categories: {sorted(bad)}")
    with db.connect() as conn:
        db.put_settings(conn, values)
        s = db.get_settings(conn)
        ingest.rescore_all(conn, s)
        syms = [r[0] for r in conn.execute("SELECT symbol FROM companies WHERE in_portfolio=1")]
        alert_rules.evaluate_price_alerts(conn, syms, s)
        since = db.to_utc_iso(datetime.now(timezone.utc) - timedelta(days=3))
        alert_rules.evaluate_announcement_alerts(conn, s, since)
    return {"settings": s}


@app.post("/api/refresh")
def refresh(prices: bool = True, announcements: bool = True):
    return ingest.refresh(prices=prices, announcements=announcements)


@app.get("/api/sources")
def sources():
    with db.connect() as conn:
        return {"sources": db.source_status(conn), "data": _data_mode(conn),
                "counts": {"announcements": conn.execute("SELECT COUNT(*) FROM announcements").fetchone()[0],
                           "price_rows": conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0]}}


@app.get("/api/llm/usage")
def llm_usage():
    return llm.usage_summary()


# ---- frontend -------------------------------------------------------------------------

if config.STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=config.STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        f = config.STATIC_DIR / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(config.STATIC_DIR / "index.html")
