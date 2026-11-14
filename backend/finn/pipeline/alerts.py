"""Threshold alerts — pure arithmetic on stored end-of-day data.

price:  |close/prev_close − 1| ≥ price_move_pct
volume: volume ≥ volume_multiple × mean(volume of the previous N sessions)
announcement: a filing in a watched category with priority ≥ the alert floor

Alerts are de-duplicated by a key (kind:symbol:date / announcement id), so
re-running a refresh never re-raises the same alert.
"""
from __future__ import annotations

import sqlite3

from .. import db
from ..text import headline


def eod_metrics(conn: sqlite3.Connection, symbol: str, lookback: int) -> dict | None:
    rows = conn.execute("SELECT date, close, volume FROM prices WHERE symbol=? ORDER BY date DESC LIMIT ?",
                        (symbol, lookback + 1)).fetchall()
    if len(rows) < 2:
        return None
    last, prev = rows[0], rows[1]
    hist = [r["volume"] for r in rows[1:] if r["volume"]]
    avg_vol = sum(hist) / len(hist) if hist else None
    change = (last["close"] / prev["close"] - 1) * 100 if prev["close"] else None
    vol_mult = (last["volume"] / avg_vol) if (avg_vol and last["volume"] is not None) else None
    return {"date": last["date"], "close": last["close"], "prev_close": prev["close"],
            "change_pct": change, "volume": last["volume"], "avg_volume": avg_vol,
            "volume_multiple": vol_mult, "sessions_in_avg": len(hist)}


def _raise(conn, kind, symbol, ref, message, value, threshold, key) -> bool:
    cur = conn.execute(
        "INSERT OR IGNORE INTO alerts(kind, symbol, ref, message, value, threshold, created_at, dedupe_key) "
        "VALUES(?,?,?,?,?,?,?,?)", (kind, symbol, ref, message, value, threshold, db.utcnow(), key))
    return cur.rowcount > 0


def evaluate_price_alerts(conn: sqlite3.Connection, symbols: list[str], settings: dict) -> int:
    n = 0
    pct = float(settings["price_move_pct"])
    mult = float(settings["volume_multiple"])
    lookback = int(settings["volume_lookback_days"])
    for s in symbols:
        m = eod_metrics(conn, s, lookback)
        if not m:
            continue
        if m["change_pct"] is not None and abs(m["change_pct"]) >= pct:
            word = "up" if m["change_pct"] > 0 else "down"
            n += _raise(conn, "price", s, m["date"],
                        f"{s} closed {word} {abs(m['change_pct']):.1f}% at ₹{m['close']:,.2f}",
                        round(m["change_pct"], 2), pct, f"price:{s}:{m['date']}:{pct}")
        # require a reasonable baseline before calling volume "unusual"
        if m["volume_multiple"] is not None and m["sessions_in_avg"] >= 5 and m["volume_multiple"] >= mult:
            n += _raise(conn, "volume", s, m["date"],
                        f"{s} traded {m['volume_multiple']:.1f}× its {m['sessions_in_avg']}-day average volume",
                        round(m["volume_multiple"], 2), mult, f"volume:{s}:{m['date']}:{mult}")
    return n


def evaluate_announcement_alerts(conn: sqlite3.Connection, settings: dict, since_iso: str) -> int:
    watched = settings["watched_categories"]
    floor = int(settings["announcement_alert_min_priority"])
    if not watched:
        return 0
    q = ("SELECT id, symbol, category, subject, body, summary, priority FROM announcements "
         f"WHERE published_at >= ? AND priority >= ? AND category IN ({','.join('?' * len(watched))})")
    n = 0
    for r in conn.execute(q, (since_iso, floor, *watched)).fetchall():
        label = headline(r["subject"], r["body"], r["summary"], limit=140)
        n += _raise(conn, "announcement", r["symbol"], r["id"], f"{r['symbol']}: {label}",
                    r["priority"], floor, f"ann:{r['id']}")
    return n
