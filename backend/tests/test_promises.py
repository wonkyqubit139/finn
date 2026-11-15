from datetime import date

from finn.analysis.guidance import find_quote, verify
from finn.analysis.promises import evaluate, target_text


def q(rev, ebitda, pat):
    return {"revenue": rev, "ebitda": ebitda, "pat": pat}


# Q1–Q2 FY27 reported, plus year-ago quarters (from the filings' YoY columns)
SERIES = {
    "2025-06-30": q(1000, 200, 120), "2025-09-30": q(1050, 210, 125),
    "2026-06-30": q(1100, 209, 130), "2026-09-30": q(1200, 240, 145),
}
SAID = date(2026, 3, 31)        # guidance given on the Q4 FY26 call
LATEST = date(2026, 9, 30)


def test_growth_guidance_on_track_and_missed():
    c = {"metric": "revenue_growth", "basis": "yoy", "period_text": "FY27",
         "target": {"type": "range", "low": 12, "high": 15, "unit": "pct"}}
    r = evaluate(c, SAID, SERIES, LATEST)
    # H1: (1100+1200)/(1000+1050) − 1 = 12.2% → within range, year not complete → on track
    assert r["status"] == "on_track" and r["actual_value"] == 12.2 and r["actual_span"] == "Q1 FY27–Q2 FY27"
    c2 = {**c, "period_text": "Q2 FY27", "target": {"type": "at_least", "low": 18, "unit": "pct"}}
    r2 = evaluate(c2, SAID, SERIES, LATEST)
    assert r2["status"] == "missed" and round(r2["actual_value"], 1) == 14.3


def test_margin_guidance_bps_and_direction():
    c = {"metric": "ebitda_margin", "period_text": "Q2 FY27",
         "target": {"type": "at_least", "low": 50, "unit": "bps"}}
    r = evaluate(c, SAID, SERIES, LATEST)   # 20.0% vs 20.0% a year ago → 0 bps → missed
    assert r["status"] == "missed" and "a year earlier" in r["actual_text"]
    d = {"metric": "pat_margin", "period_text": "Q2 FY27", "target": {"type": "direction", "direction": "up"}}
    assert evaluate(d, SAID, SERIES, LATEST)["status"] == "delivered"   # 12.08% vs 11.90%


def test_pending_and_unverifiable():
    c = {"metric": "revenue_growth", "period_text": "Q4 FY27", "target": {"type": "at_least", "low": 10, "unit": "pct"}}
    assert evaluate(c, SAID, SERIES, LATEST)["status"] == "pending"
    o = {"metric": "other", "period_text": "FY27", "target": {"type": "point", "low": 25, "unit": "pct"}}
    assert evaluate(o, SAID, SERIES, LATEST)["status"] == "unverifiable"
    n = {"metric": "pat_growth", "period_text": "over the medium term", "target": {"type": "direction", "direction": "up"}}
    assert evaluate(n, SAID, SERIES, LATEST)["status"] == "unverifiable"
    assert target_text({"type": "range", "low": 12, "high": 15, "unit": "pct"}) == "12–15%"


PAGES = ["Moderator: Good morning everyone.",
         ("Rajiv Mehta - CFO: Thank you. Looking ahead, we expect revenue growth of 12 to 15% for FY27,\n"
          "with EBITDA margins improv-\ning by about 50 basis points as input costs ease."),
         "Analyst: What about exports?"]


def test_quote_verification():
    page, score = find_quote("we expect revenue growth of 12 to 15% for FY27", PAGES, 2)
    assert page == 2 and score == 1.0
    page, _ = find_quote("EBITDA margins improving by about 50 basis points", PAGES, None)   # hyphenated in PDF
    assert page == 2
    page, _ = find_quote("we expect revenue growth of 20 to 25% for FY28 and beyond", PAGES, 2)
    assert page is None
    ok, dropped = verify([{"quote": "we expect revenue growth of 12 to 15% for FY27", "page": 1},
                          {"quote": "we will double our order book in two years", "page": 2}], PAGES)
    assert len(ok) == 1 and ok[0]["page"] == 2 and len(dropped) == 1   # page corrected to where it really is


ANNUAL = {"2026-03-31": {"revenue": 4300.0, "ebitda": 172.0, "pat": 110.0},
          "2025-03-31": {"revenue": 3700.0, "ebitda": 150.0, "pat": 100.0}}


def test_full_year_claims_use_annual_columns():
    c = {"metric": "revenue_growth", "scope": "company", "period_text": "FY26",
         "target": {"type": "range", "low": 15, "high": 17, "unit": "pct"}}
    r = evaluate(c, date(2025, 6, 30), SERIES, LATEST, ANNUAL)
    # 4300/3700 − 1 = 16.2% → delivered, scored from the Q4 filing's full-year columns
    assert r["status"] == "delivered" and r["actual_value"] == 16.22 and "annual" in r["actual_text"]
    m = {"metric": "ebitda_margin", "scope": "company", "period_text": "FY26",
         "target": {"type": "at_least", "low": 4.5, "unit": "pct"}}
    assert evaluate(m, date(2025, 6, 30), SERIES, LATEST, ANNUAL)["status"] == "missed"   # 4.0%


def test_segment_and_operational_claims_never_scored_against_company_pnl():
    seg = {"metric": "revenue", "scope": "segment", "segment": "Telecom", "period_text": "FY27",
           "target": {"type": "range", "low": 6700, "high": 7000, "unit": "crore"}}
    r = evaluate(seg, SAID, SERIES, LATEST, ANNUAL)
    assert r["status"] == "unverifiable" and "Telecom" in r["detail"]
    op = {"metric": "other", "scope": "operational", "period_text": "FY27",
          "target": {"type": "range", "low": 32, "high": 33, "unit": None}}
    assert "volumes" in evaluate(op, SAID, SERIES, LATEST)["detail"]


def test_company_revenue_target_uses_labelled_run_rate():
    c = {"metric": "revenue", "scope": "company", "period_text": "FY27",
         "target": {"type": "at_least", "low": 4800, "unit": "crore"}}
    r = evaluate(c, SAID, SERIES, LATEST, ANNUAL)
    # H1 = 2300 → run-rate 4600 < 4800 → off track, and the text says it's a run-rate
    assert r["status"] == "off_track" and "run-rate" in r["actual_text"] and r["actual_value"] == 4600
    # a ₹ target is never compared with a % actual
    bad = {"metric": "revenue_growth", "scope": "company", "period_text": "Q2 FY27",
           "target": {"type": "at_least", "low": 5000, "unit": "crore"}}
    assert evaluate(bad, SAID, SERIES, LATEST)["status"] == "unverifiable"
