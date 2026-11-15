"""Quarterly results: model transcribes, code calculates.

1. select_pages(): find the pages that hold the results statement (keyword
   scoring), so we send ~3–5 pages instead of a 40-page filing.
2. The fast model copies line items exactly as printed into a fixed JSON
   shape, with column labels, the unit and the page number. It is told not
   to compute anything.
3. build_view(): code converts units to ₹ crore, identifies the current,
   previous and year-ago quarter columns by date, derives EBITDA only when
   the reported line items allow it, computes QoQ/YoY and margins, and runs
   consistency checks. Every figure carries (document, page).

EBITDA is not a line item in the SEBI results format, so it is reconstructed:
    EBITDA = profit before exceptional items and tax
             + finance costs + depreciation & amortisation
             − other income − share of profit of associates/JVs
If the statement lacks a component, or has exceptional items but no
pre-exceptional profit line, EBITDA is left blank with the reason. For banks
and NBFCs it is not meaningful (interest is their main operating cost), so it
is never computed for them.
"""
from __future__ import annotations

import json
import re
from datetime import date

from .. import config
from ..llm import complete_json
from .periods import label as qlabel, shift_quarters

PROMPT_VERSION = "res-v1"

KEYWORDS = {
    "revenue from operations": 3, "total income": 2, "profit before tax": 3, "quarter ended": 2,
    "three months ended": 2, "finance cost": 2, "depreciation": 2, "tax expense": 2, "net profit": 2,
    "profit for the period": 2, "interest earned": 3, "interest expended": 2, "operating profit before provisions": 2,
    "other income": 1, "exceptional": 1, "consolidated": 1, "earnings per share": 1,
}

LINE_KEYS = [
    "revenue_from_operations", "other_income", "total_income", "total_expenses", "finance_costs",
    "depreciation_amortisation", "profit_before_exceptional_items_and_tax", "exceptional_items",
    "share_of_profit_of_associates_jv", "profit_before_tax", "tax_expense", "net_profit",
    "net_profit_attributable_to_owners",
    # banks / NBFCs
    "interest_earned", "interest_expended", "operating_expenses", "operating_profit_before_provisions",
    "provisions_and_contingencies", "impairment_on_financial_instruments",
]

UNIT_TO_CRORE = {"crore": 1.0, "lakh": 100.0, "million": 10.0, "billion": 0.01, "thousand": 10_000.0,
                 "rupees": 10_000_000.0}


def select_pages(page_texts: list[str], k: int = 5) -> tuple[list[int], bool]:
    """Return (1-based page numbers to send, is_scanned)."""
    scored = []
    for i, t in enumerate(page_texts):
        low = t.lower()
        s = sum(w for kw, w in KEYWORDS.items() if kw in low)
        scored.append((s, i + 1))
    text_pages = sum(1 for t in page_texts if len(t.strip()) > 200)
    good = sorted([x for x in scored if x[0] >= 6], reverse=True)[:k]
    if good:
        return sorted(p for _, p in good), False
    if text_pages < max(1, len(page_texts) // 3):
        # scanned filing: the statement is almost always within the first pages
        return list(range(1, min(len(page_texts), 6) + 1)), True
    return [], False


def detect_unit(texts: list[str]) -> str | None:
    """Deterministic read of the unit line ('₹ in crore', 'Rs. in lakhs', '(₹ million)')."""
    blob = " ".join(texts).lower()
    m = re.search(r"(?:₹|rs\.?|inr|rupees)\s*(?:in\s*)?\(?\s*(crores?|lakhs?|lacs?|millions?|mn|billions?|thousands?)", blob) \
        or re.search(r"\(?\s*(?:amount|amounts|figures|all amounts)?\s*in\s*(?:₹|rs\.?|inr)?\s*(crores?|lakhs?|lacs?|millions?|mn|billions?)\b", blob)
    if not m:
        return None
    u = m.group(1)
    if u.startswith("cr"):
        return "crore"
    if u.startswith(("lakh", "lac")):
        return "lakh"
    if u.startswith(("million", "mn")):
        return "million"
    if u.startswith("billion"):
        return "billion"
    if u.startswith("thousand"):
        return "thousand"
    return None


SYSTEM = """You transcribe Indian listed-company quarterly results statements (SEBI format) into JSON.
Copy numbers EXACTLY as printed. Do not calculate, infer or fill anything that is not printed.
If both consolidated and standalone statements are present, transcribe ONLY the consolidated one.
Use null for any line not printed. Losses and deductions are negative numbers.
Return JSON:
{
 "found": true|false,                       // false if no results statement is on these pages
 "basis": "consolidated"|"standalone",
 "format": "corporate"|"bank"|"nbfc"|"insurance",
 "unit": "crore"|"lakh"|"million"|"billion"|"thousand"|"rupees",   // as stated on the statement
 "page": <page number where the statement table is>,
 "columns": [{"label": "<header as printed>", "period_end": "YYYY-MM-DD",
              "period_type": "quarter"|"half_year"|"nine_months"|"year", "audited": true|false|null}],
 "lines": {"<key>": [<one value per column, same order as columns>], ...}
}
Line keys to use (omit those not printed): """ + ", ".join(LINE_KEYS)


def extract(page_texts: list[str], pages_sel: list[int], images: list[str] | None = None) -> dict:
    """One model call per document; cached by content in llm_cache."""
    if images:
        content: list[dict] = [{"type": "text", "text": "Results filing pages (scanned images) follow."}]
        for n, url in zip(pages_sel, images):
            content.append({"type": "text", "text": f"=== PAGE {n} ==="})
            content.append({"type": "image_url", "image_url": {"url": url}})
    else:
        content = "\n\n".join(f"=== PAGE {n} ===\n{page_texts[n - 1]}" for n in pages_sel)  # type: ignore[assignment]
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}]
    return complete_json("results", PROMPT_VERSION, messages, tier=config.LLM_FAST, max_tokens=6000)


# ---- deterministic part ------------------------------------------------------------------

def _to_date(s) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def _num(x):
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).replace(",", "").strip()
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def _pct(a, b):
    if a is None or b is None or b == 0:
        return None
    return (a / b - 1) * 100 if b > 0 else None   # growth vs a negative base is not meaningful


def metrics_for_column(lines: dict, j: int, financial: bool) -> dict:
    g = lambda k: (lines.get(k) or [None] * (j + 1))[j] if j < len(lines.get(k) or []) else None  # noqa: E731
    rev = g("revenue_from_operations")
    if rev is None and g("interest_earned") is not None:
        rev = (g("interest_earned") or 0) + (g("other_income") or 0)    # banks: total income
    pbt = g("profit_before_tax")
    pat = g("net_profit_attributable_to_owners")
    if pat is None:
        pat = g("net_profit")
    m = {"revenue": rev, "pbt": pbt, "pat": pat, "other_income": g("other_income"),
         "finance_costs": g("finance_costs"), "depreciation": g("depreciation_amortisation"),
         "tax": g("tax_expense"), "net_profit_total": g("net_profit"),
         "ppop": g("operating_profit_before_provisions"), "total_income": g("total_income"),
         "exceptional": g("exceptional_items"), "assoc": g("share_of_profit_of_associates_jv"),
         "pbt_pre_exc": g("profit_before_exceptional_items_and_tax")}
    m["ebitda"], m["ebitda_note"] = ebitda(m, financial)
    m["ebitda_margin"] = (m["ebitda"] / rev * 100) if (m["ebitda"] is not None and rev) else None
    m["pat_margin"] = (pat / rev * 100) if (pat is not None and rev) else None
    return m


def ebitda(m: dict, financial: bool) -> tuple[float | None, str]:
    if financial:
        return None, "Not meaningful for lenders: interest is their main operating cost."
    base, base_name = m["pbt_pre_exc"], "profit before exceptional items and tax"
    if base is None:
        if m["exceptional"] not in (None, 0):
            return None, "Statement shows exceptional items but no pre-exceptional profit line."
        base, base_name = m["pbt"], "profit before tax"
    missing = [n for n, v in (("finance costs", m["finance_costs"]), ("depreciation", m["depreciation"]),
                              (base_name, base)) if v is None]
    if missing:
        return None, f"Not reported in the statement: {', '.join(missing)}."
    val = base + m["finance_costs"] + m["depreciation"] - (m["other_income"] or 0) - (m["assoc"] or 0)
    note = f"{base_name.capitalize()} + finance costs + D&A − other income"
    if m["assoc"]:
        note += " − share of associates/JVs"
    return val, note


def build_view(raw: dict, financial_flag: bool, page_texts: list[str], pages_sel: list[int],
               doc: dict) -> dict:
    """Normalise one extracted statement into the figures the UI shows."""
    if not raw or not raw.get("found", True) or not raw.get("columns"):
        return {"ok": False, "reason": "No results statement found in this filing."}
    cols = raw["columns"]
    n = len(cols)
    lines = {k: [_num(v) for v in (raw.get("lines", {}).get(k) or [])][:n] for k in LINE_KEYS}
    # unit: trust the printed unit line over the model when they disagree
    detected = detect_unit([page_texts[p - 1] for p in pages_sel if 0 < p <= len(page_texts)]) if page_texts else None
    unit = detected or raw.get("unit") or "crore"
    unit_note = None
    if detected and raw.get("unit") and detected != raw.get("unit"):
        unit_note = f"Model read the unit as {raw.get('unit')}; the statement says {detected}. Used {detected}."
    div = UNIT_TO_CRORE.get(unit, 1.0)
    lines = {k: [None if v is None else v / div for v in vs] for k, vs in lines.items()}

    fmt = raw.get("format") or "corporate"
    financial = financial_flag or fmt in ("bank", "nbfc", "insurance")
    dated = [(i, _to_date(c.get("period_end")), c.get("period_type")) for i, c in enumerate(cols)]
    quarters = sorted([(d, i) for i, d, t in dated if d and t == "quarter"], reverse=True)
    if not quarters:
        return {"ok": False, "reason": "Could not identify a quarterly column."}
    cur_d, cur_i = quarters[0]
    by_date = {d: i for d, i in quarters}
    prev_i = by_date.get(shift_quarters(cur_d, -1))
    yoy_i = by_date.get(shift_quarters(cur_d, -4))

    cur = metrics_for_column(lines, cur_i, financial)
    prev = metrics_for_column(lines, prev_i, financial) if prev_i is not None else None
    ya = metrics_for_column(lines, yoy_i, financial) if yoy_i is not None else None

    def deltas(other):
        if not other:
            return {}
        return {k: _pct(cur[k], other[k]) for k in ("revenue", "ebitda", "pbt", "pat")}

    years = sorted([(d, i) for i, d, t in dated if d and t == "year"], reverse=True)
    annual = [{"period_end": d.isoformat(), "label": f"FY{(d.year % 100):02d}",
               **{k: v for k, v in metrics_for_column(lines, i, financial).items()
                  if k in ("revenue", "ebitda", "pbt", "pat", "ebitda_margin", "pat_margin", "ebitda_note")}}
              for d, i in years]

    checks = consistency_checks(lines, [i for _, i in quarters])
    return {
        "ok": True, "period_end": cur_d.isoformat(), "period_label": qlabel(cur_d),
        "basis": raw.get("basis") or "consolidated", "format": fmt, "financial": financial,
        "unit_reported": unit, "unit_note": unit_note,
        "current": cur, "previous": prev, "year_ago": ya,
        "previous_period": shift_quarters(cur_d, -1).isoformat() if prev else None,
        "year_ago_period": shift_quarters(cur_d, -4).isoformat() if ya else None,
        "qoq": deltas(prev), "yoy": deltas(ya),
        "quarters": {d.isoformat(): metrics_for_column(lines, i, financial) for d, i in quarters},
        "annual": annual, "checks": checks,
        "source": {"doc_id": doc["id"], "url": doc["url"], "page": raw.get("page") or (pages_sel[0] if pages_sel else None),
                   "title": doc.get("title")},
    }


def consistency_checks(lines: dict, cols: list[int]) -> list[dict]:
    """Arithmetic the printed statement must satisfy. A failure usually means a
    mis-read number, so it is shown next to the figures."""
    def at(key, j):
        vs = lines.get(key) or []
        return vs[j] if j < len(vs) else None

    def close(a, b):
        return abs(a - b) <= max(0.6, 0.006 * max(abs(a), abs(b)))   # printed figures are rounded

    pbt_ok, rev_ok = [], []
    for j in cols:
        pbt, tax, np_, assoc = at("profit_before_tax", j), at("tax_expense", j), at("net_profit", j), \
            at("share_of_profit_of_associates_jv", j)
        # skip when associates' share is added after tax (format varies by company)
        if None not in (pbt, tax, np_) and not assoc:
            pbt_ok.append(close(pbt - tax, np_))
        rev, oi, ti = at("revenue_from_operations", j), at("other_income", j), at("total_income", j)
        if None not in (rev, oi, ti):
            rev_ok.append(close(rev + oi, ti))
    out = []
    for name, res in (("PBT − tax = net profit", pbt_ok), ("Revenue + other income = total income", rev_ok)):
        if res:
            out.append({"name": name, "ok": all(res), "detail": f"{sum(res)}/{len(res)} columns"})
    return out


def reconcile(views: list[dict]) -> list[dict]:
    """Cross-filing check: a quarter that appears in two filings (as 'current' in
    one and 'previous'/'year-ago' in a later one) should carry the same revenue
    and PAT unless restated."""
    seen: dict[str, tuple[dict, str]] = {}
    out = []
    for v in sorted([v for v in views if v.get("ok")], key=lambda v: v["period_end"]):
        for qd, m in v["quarters"].items():
            if qd in seen:
                old, src = seen[qd]
                for k in ("revenue", "pat"):
                    a, b = old.get(k), m.get(k)
                    if a is not None and b is not None and abs(a - b) > max(1.0, 0.01 * abs(a)):
                        out.append({"quarter": qlabel(date.fromisoformat(qd)), "metric": k,
                                    "first": round(a, 2), "later": round(b, 2),
                                    "note": "Differs between filings (restated or mis-read)."})
            else:
                seen[qd] = (m, v["source"]["doc_id"])
    return out


def to_json(v: dict) -> str:
    return json.dumps(v, default=str)
