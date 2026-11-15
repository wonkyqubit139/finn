"""End-to-end: refresh pipeline → SQLite → API, with the network replaced by
synthetic payloads. Proves the whole flow, not just the units."""
from datetime import date, datetime, timedelta

import pandas as pd
from fastapi.testclient import TestClient

from conftest import bse_payload, nse_items
from finn import config
from finn.sources import announcements as ann_src
from finn.sources import prices as price_src
from finn.sources.http import SourceError


def test_parse_nse_and_bse():
    now = datetime.now(config.IST)
    items = ann_src.parse_nse(nse_items(now), "TCS")
    assert len(items) == 7
    assert items[0].id == "nse:900001" and items[0].published_at.tzinfo is not None
    assert items[3].attachment_url is None           # '-' means no attachment
    assert items[6].published_at.hour == (now - timedelta(hours=3)).hour  # an_dt fallback
    b = ann_src.parse_bse(bse_payload()["Table"], "RELIANCE")
    assert [x.id for x in b] == ["bse:b-1111", "bse:b-2222"]   # row without NEWSID skipped
    assert b[0].subject == "Credit Rating"
    assert b[0].attachment_url.endswith("AttachLive/sample-rating.pdf")


def _fake_frame(n=30, spike_last=True):
    idx = pd.bdate_range(end=date.today(), periods=n)
    close = [100 + i * 0.1 for i in range(n)]
    vol = [1_000_000] * n
    if spike_last:
        close[-1] = close[-2] * 1.065   # +6.5%
        vol[-1] = 3_100_000             # 3.1× average
    return pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close, "Volume": vol}, index=idx)


def test_eod_bars_and_alert_math(temp_db):
    from finn import db
    from finn.pipeline import alerts
    bars = price_src.frame_to_bars(_fake_frame(), "TCS")
    assert len(bars) == 30
    with db.connect() as conn:
        conn.executemany("INSERT INTO prices VALUES(?,?,?,?,?,?,?, 'yahoo')",
                         [(b.symbol, b.date, b.open, b.high, b.low, b.close, b.volume) for b in bars])
        m = alerts.eod_metrics(conn, "TCS", 20)
        assert round(m["change_pct"], 1) == 6.5
        assert round(m["volume_multiple"], 1) == 3.1
        s = db.get_settings(conn)
        assert alerts.evaluate_price_alerts(conn, ["TCS"], s) == 2
        assert alerts.evaluate_price_alerts(conn, ["TCS"], s) == 0   # de-duplicated


def _patch_network(monkeypatch, nse_blocked=False):
    now = datetime.now(config.IST)

    def fake_nse(self, symbol, start, end):
        if nse_blocked:
            raise SourceError("HTTP 403 from nseindia")
        return ann_src.parse_nse(nse_items(now), symbol) if symbol == "TCS" else []

    def fake_bse(self, symbol, code, start, end):
        return ann_src.parse_bse(bse_payload()["Table"], symbol) if symbol == "RELIANCE" else []

    def fake_eod(symbols, period="6mo"):
        return {s: price_src.frame_to_bars(_fake_frame(spike_last=(s == "TCS")), s) for s in symbols}, {}

    monkeypatch.setattr(ann_src.NSEClient, "announcements", fake_nse)
    monkeypatch.setattr(ann_src.BSEClient, "announcements", fake_bse)
    monkeypatch.setattr("finn.pipeline.ingest.fetch_eod", fake_eod)
    monkeypatch.setattr("finn.pipeline.ingest.time.sleep", lambda s: None)


def test_full_flow_nse(monkeypatch):
    _patch_network(monkeypatch)
    from finn.api import app
    from finn.pipeline import ingest
    out = ingest.refresh()
    assert out["status"] == "ok" and out["prices"]["symbols"] == 18
    with TestClient(app) as client:
        f = client.get("/api/feed", params={"window": "24h"}).json()
        assert f["data"]["mode"] == "live"
        # within 24h: results outcome (2h), newspaper ad (3h), transcript (5h)
        assert [x["sub_type"] for x in f["groups"]["high"]] == ["outcome"]
        assert {x["sub_type"] for x in f["groups"]["routine"]} == {"newspaper_ad"}
        assert {x["category"] for x in f["groups"]["medium"]} == {"earnings_call"}
        assert f["market_alerts"] and {a["kind"] for a in f["market_alerts"]} == {"price", "volume"}
        f7 = client.get("/api/feed", params={"window": "7d"}).json()
        assert f7["total"] == 7
        assert f7["groups"]["high"][0]["sub_type"] in ("outcome", "kmp_join")
        # alerts inbox: results + CFO appointment raised as announcement alerts
        al = client.get("/api/alerts").json()
        assert {a["kind"] for a in al["alerts"]} == {"price", "volume", "announcement"}
        # settings change re-scores: un-watching management_change lowers the CFO item
        before = next(x for x in f7["groups"]["high"] if x["category"] == "management_change")["priority"]
        client.put("/api/settings", json={"watched_categories": ["results"]})
        f7b = client.get("/api/feed", params={"window": "7d"}).json()
        after = [x for g in f7b["groups"].values() for x in g if x["category"] == "management_change"][0]["priority"]
        assert after < before
        p = client.get("/api/portfolio").json()
        tcs = next(h for h in p["holdings"] if h["symbol"] == "TCS")
        assert len(tcs["spark"]) == 30 and tcs["eod"]["volume_multiple"] > 3
        assert client.get("/api/feed", params={"window": "bogus"}).status_code == 400


def test_nse_blocked_falls_back_to_bse(monkeypatch):
    _patch_network(monkeypatch, nse_blocked=True)
    from finn.pipeline import ingest
    from finn import db
    out = ingest.refresh(prices=False)
    assert out["announcements"]["bse"] >= 1
    with db.connect() as conn:
        st = {r["source"]: r for r in db.source_status(conn)}
        assert st["nse"]["last_error"] and st["bse"]["last_ok"]
        rows = conn.execute("SELECT category, sub_type FROM announcements WHERE symbol='RELIANCE'").fetchall()
        assert {(r[0], r[1]) for r in rows} == {("credit_rating", "reaffirm"), ("M&A", "deal")}


def test_snapshot_roundtrip(monkeypatch, temp_db):
    _patch_network(monkeypatch)
    from finn.pipeline import ingest
    from finn import db
    ingest.refresh()
    exp = ingest.export_snapshot()
    assert exp["announcements"] == 7
    # simulate a fresh deployment with an empty DB
    monkeypatch.setattr(config, "DB_PATH", temp_db / "fresh.db")
    res = ingest.load_snapshot_if_empty()
    assert res["loaded"] == 7
    from finn.api import _data_mode
    with db.connect() as conn:
        assert _data_mode(conn)["mode"] == "snapshot"
        assert conn.execute("SELECT COUNT(*) FROM announcements WHERE category IS NULL").fetchone()[0] == 0


def test_since_last_visit_and_settings_validation(monkeypatch):
    _patch_network(monkeypatch)
    from finn.api import app
    from finn.pipeline import ingest
    ingest.refresh()
    with TestClient(app) as client:
        first = client.get("/api/feed", params={"window": "since_last"}).json()
        assert first["window"]["label"] == "Last 24 hours"          # no visit recorded yet
        client.post("/api/feed/seen")
        after = client.get("/api/feed", params={"window": "since_last"}).json()
        assert after["window"]["label"] == "Since you last looked" and after["total"] == 0
        assert client.put("/api/settings", json={"price_move_pct": 0}).status_code == 422
        assert client.put("/api/settings", json={"watched_categories": ["nope"]}).status_code == 400
        ok = client.put("/api/settings", json={"price_move_pct": 7.5}).json()
        assert ok["settings"]["price_move_pct"] == 7.5
        a = client.get("/api/alerts").json()
        msgs = [x["message"] for x in a["alerts"] if x["kind"] == "announcement"]
        assert msgs and not any(m.endswith(": Outcome of Board Meeting") for m in msgs)  # readable text, not raw subject


def test_refresh_with_llm_enabled_does_not_deadlock(monkeypatch):
    """Regression: classify_pending held an open write transaction while the
    LLM client opened a second connection to log the call → 'database is locked'.
    Reproduces the real-world case: real filings + a configured model key."""
    import json
    import httpx
    from finn import db, llm  # noqa: F401
    _patch_network(monkeypatch)
    monkeypatch.setattr(db, "LOCK_TIMEOUT", 1)           # fail fast instead of waiting 30 s
    monkeypatch.setattr(config, "LLM_FAST", config.LLMTier("http://fake/v1", "k", "fake-model"))

    def fake_post(url, json=None, **kw):
        items = __import__("json").loads(json["messages"][1]["content"])
        reply = {"items": [{"id": it["id"], "category": "press_release", "sub_type": "general",
                            "summary": "Company issued a press release."} for it in items]}

        class R:
            status_code = 200
            headers = {}
            text = ""

            def json(self):
                return {"choices": [{"message": {"content": __import__("json").dumps(reply)}}],
                        "usage": {"prompt_tokens": 50, "completion_tokens": 20}}
        return R()

    monkeypatch.setattr(httpx, "post", fake_post)
    from finn.pipeline import ingest
    out = ingest.refresh(prices=False)
    assert out["classification"]["sent_to_llm"] >= 1
    assert out["classification"]["llm_classified"] == out["classification"]["sent_to_llm"]
    with db.connect() as conn:
        row = conn.execute("SELECT classified_by, summary FROM announcements WHERE id='nse:900006'").fetchone()
        assert row["classified_by"] == "llm:fake-model" and row["summary"]
        assert conn.execute("SELECT COUNT(*) FROM llm_calls WHERE ok=1").fetchone()[0] == 1
