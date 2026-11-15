"""End-to-end dossier build: fake NSE (serving real generated PDFs) + fake model.
Checks the whole chain: discovery → download → page text → results maths →
guidance quote verification → promise scoring → citation enforcement."""
import json
import re
from datetime import date, datetime, timedelta

import httpx
import pymupdf
import pytest

from finn import config, db
from finn.research import build as B
from finn.research import documents as D
from finn.sources.announcements import RawAnnouncement

QUARTERS = [date(2025, 12, 31), date(2026, 3, 31), date(2026, 6, 30), date(2026, 9, 30)]
REV = {date(2024, 12, 31): 900, date(2025, 3, 31): 950, date(2025, 6, 30): 1000, date(2025, 9, 30): 1050,
       date(2025, 12, 31): 1080, date(2026, 3, 31): 1120, date(2026, 6, 30): 1100, date(2026, 9, 30): 1200}


def _pdf(pages: list[str]) -> bytes:
    doc = pymupdf.open()
    for t in pages:
        p = doc.new_page()
        p.insert_textbox(pymupdf.Rect(40, 40, 560, 800), t, fontsize=9)
    return doc.tobytes()


def results_pdf(q: date) -> bytes:
    stmt = (f"Statement of unaudited consolidated financial results for the quarter ended {q:%d.%m.%Y} "
            "(Rs. in crore)\nRevenue from operations  Other income  Total income  Finance costs  Depreciation "
            "Profit before tax  Tax expense  Net profit for the period  Earnings per share\n" + "x " * 50)
    return _pdf(["Letter to the exchange: outcome of board meeting.", stmt, "Notes to results " * 40])


TRANSCRIPT_P2 = ("Rajiv Mehta, CFO: Looking ahead, we expect revenue growth of 12 to 15% for FY27, "
                 "and we are confident EBITDA margins will stay above 19% for the full year. "
                 "We also aim to double our order book over the next two years. " + "Discussion continued. " * 30)


def transcript_pdf() -> bytes:
    return _pdf(["Earnings conference call transcript. Moderator opening remarks. " * 10, TRANSCRIPT_P2,
                 "Analyst questions " * 40])


class FakeSession:
    def get(self, url, params=None, headers=None):
        class Resp:
            status_code = 200
        r = Resp()
        if "transcript" in url:
            r.content = transcript_pdf()
        else:
            q = date.fromisoformat(re.search(r"res_(\d{4}-\d{2}-\d{2})", url).group(1))
            r.content = results_pdf(q)
        return r


class FakeNSE:
    def __init__(self):
        self.s = FakeSession()

    def quote(self, symbol):
        return {"symbol": symbol, "name": "Demo Industries Ltd", "industry": "Capital Goods"}

    def announcements(self, symbol, start, end):
        out = []
        for q in QUARTERS:
            filed = datetime.combine(q + timedelta(days=30), datetime.min.time()).replace(tzinfo=config.IST)
            items = [("Outcome of Board Meeting", f"approved financial results for the quarter ended {q:%B %d, %Y}",
                      f"https://nsearchives.nseindia.com/res_{q}.pdf", filed)]
            if q >= date(2026, 3, 31):
                items.append(("Analysts/Institutional Investor Meet/Con. Call Updates",
                              "Transcript of the earnings call", f"https://nsearchives.nseindia.com/transcript_{q}.pdf",
                              filed + timedelta(days=4)))
            for subj, body, url, ts in items:
                if start <= ts.date() <= end:
                    out.append(RawAnnouncement(f"nse:{url}", symbol, "nse", ts, subj, body, url))
        return out


def fake_model(url, json=None, headers=None, timeout=None):
    system = json["messages"][0]["content"]
    user = json["messages"][1]["content"]
    if "transcribe Indian listed-company" in system:
        q = date.fromisoformat(re.search(r"quarter ended (\d{2})\.(\d{2})\.(\d{4})", user).expand(r"\3-\2-\1"))
        prev, ya = B.R.shift_quarters(q, -1), B.R.shift_quarters(q, -4)
        cols = [q, prev, ya]

        def line(f):
            return [f(REV.get(c, 1000)) for c in cols]
        reply = {"found": True, "basis": "consolidated", "format": "corporate", "unit": "crore", "page": 2,
                 "columns": [{"label": str(c), "period_end": c.isoformat(), "period_type": "quarter"} for c in cols],
                 "lines": {"revenue_from_operations": line(lambda r: r), "other_income": line(lambda r: 10),
                           "total_income": line(lambda r: r + 10), "finance_costs": line(lambda r: 5),
                           "depreciation_amortisation": line(lambda r: 40),
                           "profit_before_tax": line(lambda r: r * 0.2 - 35), "tax_expense": line(lambda r: (r * 0.2 - 35) * 0.25),
                           "net_profit": line(lambda r: (r * 0.2 - 35) * 0.75)}}
    elif "earnings-call transcript" in system:
        reply = {"claims": [
            {"speaker": "Rajiv Mehta", "page": 2, "quote": "we expect revenue growth of 12 to 15% for FY27",
             "metric": "revenue_growth", "basis": "yoy", "period_text": "FY27", "specificity": "numeric",
             "target": {"type": "range", "low": 12, "high": 15, "unit": "pct"}, "topic": "Revenue growth"},
            {"speaker": "Rajiv Mehta", "page": 2, "quote": "EBITDA margins will stay above 19% for the full year",
             "metric": "ebitda_margin", "basis": "level", "period_text": "FY27", "specificity": "numeric",
             "target": {"type": "at_least", "low": 19, "unit": "pct"}, "topic": "Margin floor"},
            {"speaker": "Rajiv Mehta", "page": 2, "quote": "We also aim to double our order book over the next two years",
             "metric": "other", "period_text": "next two years", "specificity": "directional",
             "target": {"type": "direction", "direction": "up"}, "topic": "Order book"},
            {"speaker": "Rajiv Mehta", "page": 2, "quote": "we will become debt free by March and grow exports 40%",
             "metric": "other", "period_text": "FY27", "specificity": "numeric", "target": {}, "topic": "invented"},
        ]}
    else:  # synthesis
        reply = {"overview": [{"text": "Demo makes industrial equipment.", "cite": ["D5:p1"]}],
                 "bull": [{"point": "Revenue up 14% YoY in Q2 FY27.", "cite": ["FIN"]},
                          {"point": "Unsupported optimism.", "cite": []},
                          {"point": "Cites a page that doesn't exist.", "cite": ["D5:p99"]}],
                 "bear": [{"point": "Margins flat.", "cite": ["FIN", "D5:p2"]}],
                 "claim_assessments": [{"id": "C3", "verdict": "too_early", "reason": "No order book data.", "cite": ["D5:p2"]}],
                 "narrative_gap": {"text": "Growth guidance is being met so far.", "cite": ["FIN"]}}

    class R:
        status_code = 200
        headers = {}
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": __import__("json").dumps(reply)}}],
                    "usage": {"prompt_tokens": 1000, "completion_tokens": 200}}
    return R()


@pytest.fixture
def env(monkeypatch, temp_db):
    monkeypatch.setattr(D, "DOC_DIR", temp_db / "docs")
    monkeypatch.setattr(config, "LLM_FAST", config.LLMTier("http://fake", "k", "fast"))
    monkeypatch.setattr(config, "LLM_DEEP", config.LLMTier("http://fake", "k", "deep"))
    monkeypatch.setattr(httpx, "post", fake_model)
    monkeypatch.setattr(D, "discover", lambda sym, client=None, today=None: D.pick_documents(
        [a for q in QUARTERS for a in FakeNSE().announcements(sym, date(2025, 1, 1), date(2026, 12, 31))]))


def test_full_dossier(env):
    d = B.build("DEMO", FakeNSE())
    fin = d["financials"]
    assert d["name"] == "Demo Industries Ltd" and d["latest_label"] == "Q2 FY27"
    assert [r["label"] for r in fin["table"]] == ["Q2 FY27", "Q1 FY27", "Q4 FY26", "Q3 FY26"]
    top = fin["table"][0]
    # revenue 1200 vs 1050 a year ago (from comparative column) → +14.3%
    assert top["revenue"] == 1200 and round(top["revenue_yoy"], 1) == 14.3
    # EBITDA = PBT (205) + 5 + 40 − 10 = 240 → 20.0% margin
    assert round(top["ebitda"], 1) == 240.0 and round(top["ebitda_margin"], 1) == 20.0
    assert top["source"]["ref"] == "D1" and top["source"]["page"] == 2
    assert all(c["ok"] for c in fin["latest"]["checks"])
    assert fin["reconciliation"] == []

    # guidance: 3 transcripts × 4 claims; the invented quote is dropped from each
    assert d["dropped_claims"] == 3
    # same guidance repeated on three calls → one row each, older calls listed
    assert len(d["promises"]) == 3
    by_status = {(p["said_in"], p["metric"]): p for p in d["promises"]}
    assert [a["said_in"] for a in by_status[("Q2 FY27", "revenue_growth")]["also_said"]] == ["Q1 FY27", "Q4 FY26"]
    rev = by_status[("Q2 FY27", "revenue_growth")]
    # FY27 so far: (1100+1200)/(1000+1050)−1 = 12.2% → inside 12–15% but year incomplete → on track
    assert rev["status"] == "on_track" and rev["actual_value"] == 12.2 and rev["page"] == 2
    margin = by_status[("Q2 FY27", "ebitda_margin")]
    assert margin["status"] == "on_track"          # H1 margin ≈ 19.6% ≥ 19
    ob = by_status[("Q2 FY27", "other")]
    assert ob["status"] == "unverifiable"

    # synthesis: uncited and bad-page points removed; real cites kept
    assert [b["point"] for b in d["bull"]] == ["Revenue up 14% YoY in Q2 FY27."]
    assert d["uncited_dropped"] == 2
    assert d["overview"][0]["cite"] == ["D5:p1"]
    assert any(p.get("model_verdict") == "too_early" for p in d["promises"])
    assert [x["ref"] for x in d["documents"]][:4] == ["D1", "D2", "D3", "D4"]
    assert d["usage"]["calls"] >= 8


def test_rebuild_uses_cache_and_api_flow(env, monkeypatch):
    B.build("DEMO", FakeNSE())
    calls = []
    real = httpx.post
    monkeypatch.setattr(httpx, "post", lambda *a, **k: calls.append(1) or real(*a, **k))
    B.build("DEMO", FakeNSE())
    assert calls == []      # every extraction and the synthesis came from cache

    monkeypatch.setattr(B, "NSEClient", FakeNSE)
    from fastapi.testclient import TestClient
    from finn.api import app
    with TestClient(app) as client:
        r = client.post("/api/research/demo?sync=1&force=1").json()
        assert r["status"] == "ready" and r["data"]["symbol"] == "DEMO"
        g = client.get("/api/research/DEMO").json()
        assert g["data"]["financials"]["table"][0]["label"] == "Q2 FY27"
        assert client.post("/api/research/not a symbol").status_code == 400
        pg = client.get(f"/api/documents/{g['data']['documents'][0]['id']}/pages/2").json()
        assert "Revenue from operations" in pg["text"]


def test_no_key_fails_with_clear_message(env, monkeypatch):
    monkeypatch.setattr(config, "LLM_FAST", config.LLMTier("http://x", "", ""))
    with db.connect() as conn:
        conn.execute("INSERT INTO dossiers(symbol, status) VALUES('DEMO','queued')")
    B._run("DEMO", FakeNSE())
    st = B.status("DEMO")
    assert st["status"] == "failed" and "GEMINI_API_KEY" in st["error"]


def test_feed_enrichment(env, monkeypatch, temp_db):
    """A results filing in the portfolio feed gets its table; a CFO appointment gets the appointee profile."""
    from finn.pipeline import enrich, ingest
    from finn.portfolio import sync_companies
    appt_page = ("Appointment of Ms. Asha Rao as Chief Financial Officer. Brief profile: Ms. Asha Rao is a chartered "
                 "accountant with 22 years of experience, previously CFO of Alpha Cements Limited.")

    class S2(FakeSession):
        def get(self, url, params=None, headers=None):
            if "appt" in url:
                class Resp:
                    status_code = 200
                    content = _pdf([appt_page])
                return Resp()
            return super().get(url, params, headers)

    class N2(FakeNSE):
        def __init__(self):
            self.s = S2()
    monkeypatch.setattr(enrich, "NSEClient", N2)
    real_model = fake_model

    def model(url, json=None, **kw):
        if "management or board change" in json["messages"][0]["content"]:
            reply = {"changes": [{"person": "Asha Rao", "role": "Chief Financial Officer", "change": "appointment",
                                  "background": "Chartered accountant, 22 years' experience, ex-CFO of Alpha Cements.",
                                  "quote": "chartered accountant with 22 years of experience, previously CFO of Alpha Cements Limited",
                                  "page": 1}]}

            class R:
                status_code = 200
                headers = {}
                text = ""

                def json(self):
                    return {"choices": [{"message": {"content": __import__("json").dumps(reply)}}], "usage": {}}
            return R()
        return real_model(url, json=json, **kw)
    monkeypatch.setattr(httpx, "post", model)

    now = datetime.now(config.IST)
    with db.connect() as conn:
        sync_companies(conn)
        ingest.store_announcements(conn, [
            RawAnnouncement("nse:r1", "TCS", "nse", now - timedelta(hours=2), "Outcome of Board Meeting",
                            "approved financial results for the quarter ended September 30, 2026",
                            "https://nsearchives.nseindia.com/res_2026-09-30.pdf"),
            RawAnnouncement("nse:m1", "TCS", "nse", now - timedelta(hours=3), "Change in Management",
                            "appointment of Ms. Asha Rao as Chief Financial Officer",
                            "https://nsearchives.nseindia.com/appt.pdf")])
        ingest.classify_pending(conn, db.get_settings(conn), use_llm=False)
    out = enrich.enrich_pending(db.to_utc_iso(now - timedelta(days=2)))
    assert out == {"results": 1, "people": 1, "failed": 0}
    from fastapi.testclient import TestClient
    from finn.api import app
    with TestClient(app) as client:
        items = {x["id"]: x for g in client.get("/api/feed?window=24h").json()["groups"].values() for x in g}
    r = items["nse:r1"]["enrichment"]
    assert r["ok"] and r["period_label"] == "Q2 FY27" and r["current"]["revenue"] == 1200
    assert round(r["yoy"]["revenue"], 1) == 14.3 and r["page"] == 2
    p = items["nse:m1"]["enrichment"]
    assert p["changes"][0]["person"] == "Asha Rao" and p["changes"][0]["page"] == 1 and p["changes"][0]["background"]
