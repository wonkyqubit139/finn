"""Results maths with hand-checked answers. The 'raw' dicts mimic what the model
returns; everything asserted here is computed by code."""
import pytest

from finn.analysis import results as R

DOC = {"id": "d1", "url": "https://nsearchives.nseindia.com/x.pdf", "title": "Outcome"}

# Columns: Q2 FY27, Q1 FY27, Q2 FY26, H1 FY27, H1 FY26, FY26. Figures in ₹ lakh.
CORP = {
    "found": True, "basis": "consolidated", "format": "corporate", "unit": "lakh", "page": 3,
    "columns": [
        {"label": "Quarter ended 30.09.2026", "period_end": "2026-09-30", "period_type": "quarter"},
        {"label": "Quarter ended 30.06.2026", "period_end": "2026-06-30", "period_type": "quarter"},
        {"label": "Quarter ended 30.09.2025", "period_end": "2025-09-30", "period_type": "quarter"},
        {"label": "Half year ended 30.09.2026", "period_end": "2026-09-30", "period_type": "half_year"},
        {"label": "Half year ended 30.09.2025", "period_end": "2025-09-30", "period_type": "half_year"},
        {"label": "Year ended 31.03.2026", "period_end": "2026-03-31", "period_type": "year"},
    ],
    "lines": {
        "revenue_from_operations": [120000, 110000, 100000, 230000, 195000, 410000],
        "other_income":            [2000, 1500, 1000, 3500, 2000, 5000],
        "total_income":            [122000, 111500, 101000, 233500, 197000, 415000],
        "finance_costs":           [1000, 1000, 800, 2000, 1600, 3500],
        "depreciation_amortisation": [4000, 3900, 3500, 7900, 7000, 15000],
        "profit_before_exceptional_items_and_tax": [21000, 18000, 15000, 39000, 29000, 70000],
        "exceptional_items":       [-1000, None, None, -1000, None, None],
        "profit_before_tax":       [20000, 18000, 15000, 38000, 29000, 70000],
        "tax_expense":             [5000, 4500, 3750, 9500, 7250, 17500],
        "net_profit":              [15000, 13500, 11250, 28500, 21750, 52500],
        "net_profit_attributable_to_owners": [14500, 13000, 11000, 27500, 21250, 51000],
    },
}


def test_corporate_view():
    v = R.build_view(CORP, False, [], [3], DOC)
    assert v["ok"] and v["period_label"] == "Q2 FY27"
    c = v["current"]
    assert c["revenue"] == pytest.approx(1200.0)          # 120000 lakh = 1,200 crore
    # EBITDA = pre-exceptional PBT 21000 + fin 1000 + D&A 4000 − OI 2000 = 24000 lakh = 240 crore
    assert c["ebitda"] == pytest.approx(240.0)
    assert c["ebitda_margin"] == pytest.approx(20.0)
    assert c["pat"] == pytest.approx(145.0)                # attributable to owners
    assert v["qoq"]["revenue"] == pytest.approx((1200 / 1100 - 1) * 100)
    assert v["yoy"]["revenue"] == pytest.approx(20.0)
    assert v["year_ago_period"] == "2025-09-30" and v["previous_period"] == "2026-06-30"
    assert v["annual"][0]["label"] == "FY26" and v["annual"][0]["revenue"] == pytest.approx(4100.0)
    assert all(ch["ok"] for ch in v["checks"]) and len(v["checks"]) == 2
    assert set(v["quarters"]) == {"2026-09-30", "2026-06-30", "2025-09-30"}   # half-years excluded


def test_unit_line_overrides_model():
    text = ["Statement of Consolidated Results (₹ in crore)\nRevenue from operations ..."]
    v = R.build_view({**CORP, "unit": "lakh"}, False, text, [1], DOC)
    assert v["unit_reported"] == "crore" and v["unit_note"]
    assert v["current"]["revenue"] == pytest.approx(120000.0)


def test_ebitda_refuses_when_inputs_missing():
    raw = {**CORP, "lines": {k: v for k, v in CORP["lines"].items()
                             if k not in ("profit_before_exceptional_items_and_tax",)}}
    v = R.build_view(raw, False, [], [3], DOC)
    # current column has exceptional items but no pre-exceptional line → refuse
    assert v["current"]["ebitda"] is None and "exceptional" in v["current"]["ebitda_note"]
    # previous quarter had no exceptional items → PBT base is fine
    assert v["previous"]["ebitda"] == pytest.approx((18000 + 1000 + 3900 - 1500) / 100)
    raw2 = {**CORP, "lines": {k: v for k, v in CORP["lines"].items() if k != "depreciation_amortisation"}}
    v2 = R.build_view(raw2, False, [], [3], DOC)
    assert v2["current"]["ebitda"] is None and "depreciation" in v2["current"]["ebitda_note"]


def test_bank_never_gets_ebitda():
    bank = {"found": True, "basis": "standalone", "format": "bank", "unit": "crore", "page": 2,
            "columns": [{"period_end": "2026-09-30", "period_type": "quarter"},
                        {"period_end": "2025-09-30", "period_type": "quarter"}],
            "lines": {"interest_earned": [80000, 72000], "other_income": [11000, 10000],
                      "profit_before_tax": [22000, 20000], "tax_expense": [5500, 5000], "net_profit": [16500, 15000],
                      "operating_profit_before_provisions": [26000, 24000]}}
    v = R.build_view(bank, True, [], [2], DOC)
    assert v["current"]["ebitda"] is None and "lenders" in v["current"]["ebitda_note"]
    assert v["current"]["revenue"] == 91000    # total income for banks
    assert v["yoy"]["pat"] == pytest.approx(10.0)
    assert v["previous"] is None and v["qoq"] == {}


def test_detected_inconsistency_is_flagged():
    bad = {**CORP, "lines": {**CORP["lines"], "net_profit": [9999, 13500, 11250, 28500, 21750, 52500]}}
    v = R.build_view(bad, False, [], [3], DOC)
    chk = next(c for c in v["checks"] if c["name"].startswith("PBT"))
    assert not chk["ok"] and chk["detail"] == "2/3 columns"


def test_number_parsing_and_negative_base():
    assert R._num("(1,234.5)") == -1234.5 and R._num("12,000") == 12000 and R._num("-") is None
    assert R._pct(10, -5) is None      # growth from a loss is not meaningful


def test_page_selection_and_unit_detection():
    pages = ["Cover letter to the exchange", "Auditor's limited review report " * 20,
             ("Statement of unaudited consolidated financial results for the quarter ended 30.09.2026 (Rs. in lakhs) "
              "Revenue from operations Other income Total income Finance costs Depreciation Profit before tax "
              "Tax expense Net profit Earnings per share"), "Notes " * 60]
    sel, scanned = R.select_pages(pages)
    assert sel == [3] and not scanned
    assert R.detect_unit([pages[2]]) == "lakh"
    assert R.detect_unit(["(₹ million)"]) == "million"
    sel2, scanned2 = R.select_pages(["", "", " ", ""])
    assert scanned2 and sel2 == [1, 2, 3, 4]


def test_reconcile_flags_restatement():
    v1 = R.build_view({**CORP, "columns": [{"period_end": "2026-06-30", "period_type": "quarter"}],
                       "lines": {"revenue_from_operations": [110000], "net_profit": [13500]}}, False, [], [1],
                      {**DOC, "id": "d0"})
    v2 = R.build_view({**CORP, "lines": {**CORP["lines"], "revenue_from_operations": [120000, 115000, 100000, 0, 0, 0]}},
                      False, [], [3], DOC)
    diffs = R.reconcile([v1, v2])
    assert diffs and diffs[0]["quarter"] == "Q1 FY27" and diffs[0]["metric"] == "revenue"


def test_nbfc_detected_from_numbers():
    # Bajaj-Finance-like: Ind-AS 'corporate' layout, but finance costs ~38% of revenue
    raw = {**CORP, "format": "corporate", "unit": "crore",
           "lines": {**CORP["lines"], "finance_costs": [46000, 42000, 38000, 0, 0, 0]}}
    v = R.build_view(raw, False, [], [3], DOC)
    assert v["financial"] and v["current"]["ebitda"] is None and "lenders" in v["current"]["ebitda_note"]
