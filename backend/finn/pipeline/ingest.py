"""The refresh pipeline: fetch → store → classify → score → alert.

Source fallback is decided per run: if NSE refuses the first two symbols
(typically bot protection on cloud IPs), the rest of the run uses BSE instead
of timing out 18 times. Every outcome is written to source_status so the UI
can say exactly where the data came from.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import timedelta

from .. import config, db
from ..portfolio import sync_companies
from ..sources.announcements import BSEClient, NSEClient, RawAnnouncement, window
from ..sources.http import SourceError
from ..sources.prices import fetch_eod
from . import alerts
from .classify import classify
from .llm_classify import classify_batch
from .priority import score, tier

log = logging.getLogger("finn.ingest")
_run_lock = threading.Lock()


# ---- storage helpers ---------------------------------------------------------

def _is_cross_source_duplicate(conn, a: RawAnnouncement) -> bool:
    """The same filing appears on NSE and BSE. If we already hold one from the
    other exchange for this symbol within ±15 minutes with a similar subject,
    skip it."""
    lo = db.to_utc_iso(a.published_at - timedelta(minutes=15))
    hi = db.to_utc_iso(a.published_at + timedelta(minutes=15))
    rows = conn.execute("SELECT subject, body FROM announcements WHERE symbol=? AND source!=? "
                        "AND published_at BETWEEN ? AND ?", (a.symbol, a.source, lo, hi)).fetchall()
    mine = classify(a.subject, a.body)
    return any(classify(r["subject"], r["body"] or "").category == mine.category for r in rows)


def store_announcements(conn, items: list[RawAnnouncement]) -> int:
    new = 0
    now = db.utcnow()
    for a in items:
        if conn.execute("SELECT 1 FROM announcements WHERE id=?", (a.id,)).fetchone():
            continue
        if _is_cross_source_duplicate(conn, a):
            continue
        conn.execute(
            "INSERT INTO announcements(id, symbol, source, published_at, subject, body, attachment_url, fetched_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (a.id, a.symbol, a.source, db.to_utc_iso(a.published_at), a.subject, a.body, a.attachment_url, now))
        new += 1
    return new


def classify_pending(conn, settings: dict, use_llm: bool = True) -> dict:
    """Classify rows that have no category yet. Rules first; leftovers to the LLM."""
    rows = conn.execute("SELECT id, symbol, subject, body FROM announcements WHERE category IS NULL").fetchall()
    pending_llm = []
    watched = settings["watched_categories"]
    for r in rows:
        c = classify(r["subject"], r["body"] or "")
        p = score(c.category, c.sub_type, watched)
        conn.execute("UPDATE announcements SET category=?, sub_type=?, classified_by=?, priority=?, tier=? WHERE id=?",
                     (c.category, c.sub_type, c.rule, p, tier(p), r["id"]))
        if not c.confident:
            pending_llm.append(dict(r))
    # Commit the rule results BEFORE calling the model. The LLM client logs to
    # SQLite on its own connection, and SQLite allows one writer at a time:
    # holding this transaction open across a slow network call would deadlock.
    conn.commit()
    llm_done = 0
    if use_llm and pending_llm and config.LLM_FAST.enabled:
        results = classify_batch(pending_llm)
        for aid, res in results.items():
            p = score(res["category"], res["sub_type"], watched)
            conn.execute("UPDATE announcements SET category=?, sub_type=?, classified_by=?, priority=?, tier=?, "
                         "summary=COALESCE(summary, ?) WHERE id=?",
                         (res["category"], res["sub_type"], f"llm:{config.LLM_FAST.model}", p, tier(p),
                          res["summary"], aid))
            llm_done += 1
    return {"classified": len(rows), "sent_to_llm": len(pending_llm), "llm_classified": llm_done}


def reclassify_by_rules(conn, settings: dict) -> int:
    """Re-run the (deterministic) rules over stored filings, so rule fixes apply
    to existing data. A confident rule result replaces any earlier label; for
    filings the rules can't decide, an earlier model label is kept."""
    watched = settings["watched_categories"]
    n = 0
    for r in conn.execute("SELECT id, subject, body, category, sub_type, classified_by FROM announcements "
                          "WHERE category IS NOT NULL").fetchall():
        c = classify(r["subject"], r["body"] or "")
        if not c.confident and (r["classified_by"] or "").startswith("llm:"):
            continue
        if (c.category, c.sub_type, c.rule) != (r["category"], r["sub_type"], r["classified_by"]):
            p = score(c.category, c.sub_type, watched)
            conn.execute("UPDATE announcements SET category=?, sub_type=?, classified_by=?, priority=?, tier=? "
                         "WHERE id=?", (c.category, c.sub_type, c.rule, p, tier(p), r["id"]))
            n += 1
    return n


def rescore_all(conn, settings: dict) -> None:
    """Priority depends on the watched list, so re-score when settings change."""
    watched = settings["watched_categories"]
    for r in conn.execute("SELECT id, category, sub_type FROM announcements WHERE category IS NOT NULL").fetchall():
        p = score(r["category"], r["sub_type"] or "*", watched)
        conn.execute("UPDATE announcements SET priority=?, tier=? WHERE id=?", (p, tier(p), r["id"]))


# ---- fetch steps ---------------------------------------------------------------

def fetch_announcements(conn, holdings, days: int) -> dict:
    start, end = window(days)
    nse, bse = NSEClient(), BSEClient()
    use_nse = use_bse = True
    nse_failures = bse_failures = 0
    report = {"nse": 0, "bse": 0, "errors": {}}
    for h in holdings:
        items: list[RawAnnouncement] | None = None
        if use_nse:
            try:
                items = nse.announcements(h.symbol, start, end)
                report["nse"] += 1
            except SourceError as e:
                nse_failures += 1
                report["errors"][f"nse:{h.symbol}"] = str(e)
                if nse_failures >= 2 and report["nse"] == 0:
                    use_nse = False   # NSE is blocking us; don't burn time on the rest
        if items is None and h.bse_code and use_bse:
            try:
                items = bse.announcements(h.symbol, h.bse_code, start, end)
                report["bse"] += 1
            except SourceError as e:
                bse_failures += 1
                report["errors"][f"bse:{h.symbol}"] = str(e)
                if bse_failures >= 2 and report["bse"] == 0:
                    use_bse = False   # both exchanges unreachable: stop, keep what we have
        if items:
            store_announcements(conn, items)
        time.sleep(0.3)   # be polite to the exchanges
    if report["nse"]:
        db.mark_source(conn, "nse", True, detail=f"{report['nse']} symbols")
    elif any(k.startswith("nse:") for k in report["errors"]):
        db.mark_source(conn, "nse", False, error=next(v for k, v in report["errors"].items() if k.startswith("nse:")))
    if report["bse"]:
        db.mark_source(conn, "bse", True, detail=f"{report['bse']} symbols")
    elif any(k.startswith("bse:") for k in report["errors"]):
        db.mark_source(conn, "bse", False, error=next(v for k, v in report["errors"].items() if k.startswith("bse:")))
    return report


def fetch_prices(conn, symbols: list[str]) -> dict:
    try:
        bars, errors = fetch_eod(symbols)
    except SourceError as e:
        db.mark_source(conn, "yahoo", False, error=str(e))
        return {"symbols": 0, "errors": {"*": str(e)}}
    for s, bs in bars.items():
        conn.executemany(
            "INSERT INTO prices(symbol, date, open, high, low, close, volume, source) VALUES(?,?,?,?,?,?,?, 'yahoo') "
            "ON CONFLICT(symbol, date) DO UPDATE SET open=excluded.open, high=excluded.high, low=excluded.low, "
            "close=excluded.close, volume=excluded.volume, source='yahoo'",
            [(b.symbol, b.date, b.open, b.high, b.low, b.close, b.volume) for b in bs])
    if bars:
        db.mark_source(conn, "yahoo", True, detail=f"{len(bars)}/{len(symbols)} symbols")
    else:
        db.mark_source(conn, "yahoo", False, error=json.dumps(errors)[:400])
    return {"symbols": len(bars), "errors": errors}


def refresh(days: int | None = None, prices: bool = True, announcements: bool = True,
            enrich: bool = True) -> dict:
    if not _run_lock.acquire(blocking=False):
        return {"status": "already_running"}
    t0 = time.time()
    try:
        with db.connect() as conn:
            holdings = sync_companies(conn)
            settings = db.get_settings(conn)
        out: dict = {"status": "ok"}
        if announcements:
            with db.connect() as conn:
                out["announcements"] = fetch_announcements(conn, holdings, days or config.ANNOUNCEMENT_LOOKBACK_DAYS)
            with db.connect() as conn:
                out["classification"] = classify_pending(conn, settings)
        if prices:
            with db.connect() as conn:
                out["prices"] = fetch_prices(conn, [h.symbol for h in holdings])
        if announcements and enrich:
            from .enrich import enrich_pending   # local import: enrich pulls in the research stack
            since = db.to_utc_iso(db.parse_utc(db.utcnow()) - timedelta(days=config.ANNOUNCEMENT_LOOKBACK_DAYS))
            try:
                out["enrichment"] = enrich_pending(since)
            except Exception as e:   # enrichment is a bonus; never fail the refresh for it
                log.exception("enrichment failed")
                out["enrichment"] = {"error": str(e)}
        with db.connect() as conn:
            since = db.to_utc_iso(db.parse_utc(db.utcnow()) - timedelta(days=3))
            out["alerts_raised"] = (alerts.evaluate_price_alerts(conn, [h.symbol for h in holdings], settings)
                                    + alerts.evaluate_announcement_alerts(conn, settings, since))
        out["seconds"] = round(time.time() - t0, 1)
        return out
    finally:
        _run_lock.release()


# ---- snapshot fallback ---------------------------------------------------------

# Tables carried in a snapshot: enough for the deployed app to show the feed,
# portfolio, prices AND every pre-built research dossier (with citation page
# text and cached model answers) even if the exchanges block the server.
SNAPSHOT_TABLES = ["companies", "announcements", "prices", "alerts", "documents", "doc_pages",
                   "extractions", "dossiers", "llm_cache"]


def export_snapshot() -> dict:
    """Write the database's content tables to data/snapshot.json.gz.
    Run after a successful live refresh (and research builds) on a machine that
    can reach the exchanges; a deployed server loads it when its DB is empty."""
    import gzip
    out: dict = {"captured_at": db.utcnow(), "version": 2}
    counts = {}
    with db.connect() as conn:
        for t in SNAPSHOT_TABLES:
            rows = [dict(r) for r in conn.execute(f"SELECT * FROM {t}")]
            if t == "documents":
                for r in rows:
                    r["local_path"] = None     # PDFs aren't shipped; page text is
            if t == "dossiers":
                rows = [r for r in rows if r["status"] == "ready"]
            out[t] = rows
            counts[t] = len(rows)
    path = config.SNAPSHOT_PATH
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(out, f)
    return {"path": str(path), "bytes": path.stat().st_size, **counts}


def load_snapshot_if_empty() -> dict | None:
    import gzip
    path = config.SNAPSHOT_PATH
    if not path.exists():
        return None
    with db.connect() as conn:
        if conn.execute("SELECT COUNT(*) FROM announcements").fetchone()[0]:
            return None
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as f:
            snap = json.load(f)
        if "version" not in snap:      # v1: announcements + prices only
            snap = {"captured_at": snap["captured_at"],
                    "announcements": [{**a, "fetched_at": snap["captured_at"]} for a in snap["announcements"]],
                    "prices": [{**p, "source": "snapshot"} for p in snap["prices"]]}
        sync_companies(conn)
        loaded = {}
        for t in SNAPSHOT_TABLES:
            rows = snap.get(t) or []
            if not rows or t == "companies":
                continue
            if t == "prices":
                rows = [{**r, "source": "snapshot"} for r in rows]
            cols = list(rows[0].keys())
            conn.executemany(f"INSERT OR IGNORE INTO {t}({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                             [tuple(r.get(c) for c in cols) for r in rows])
            loaded[t] = len(rows)
        db.mark_source(conn, "snapshot", True, detail=f"captured {snap['captured_at']}")
        settings = db.get_settings(conn)
        classify_pending(conn, settings, use_llm=False)
        syms = [r[0] for r in conn.execute("SELECT symbol FROM companies WHERE in_portfolio=1")]
        alerts.evaluate_price_alerts(conn, syms, settings)
    return {"captured_at": snap["captured_at"], **loaded}
