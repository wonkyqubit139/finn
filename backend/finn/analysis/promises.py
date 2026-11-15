"""Promise Tracker: what management guided vs what was reported.

Numeric and directional claims about metrics present in the results
statements (revenue/EBITDA/PAT growth, EBITDA/PAT margin) are judged here, in
code, against figures extracted from the company's own results filings.
Everything else (order book, AUM, market share, qualitative statements) is
marked 'cannot verify from financial statements'. The synthesis step may add
a clearly-labelled model assessment for those.

Statuses: delivered | missed | on_track | off_track | pending | unverifiable
"""
from __future__ import annotations

import re
from datetime import date

from .periods import label as qlabel, parse_period, shift_quarters

GROWTH = {"revenue_growth": "revenue", "ebitda_growth": "ebitda", "pat_growth": "pat"}
MARGIN = {"ebitda_margin": ("ebitda", "revenue"), "pat_margin": ("pat", "revenue")}
LEVEL = {"revenue": "revenue"}          # absolute ₹ crore targets for the whole company


def _sum(series: dict, qs: list[date], key: str) -> float | None:
    vals = [series.get(q.isoformat(), {}).get(key) for q in qs]
    return None if any(v is None for v in vals) else sum(vals)


def actual_annual(metric: str, fy_end: date, annual: dict) -> dict | None:
    """Full-year figures straight from a Q4 filing's annual columns."""
    cur = annual.get(fy_end.isoformat())
    prev = annual.get(fy_end.replace(year=fy_end.year - 1).isoformat())
    if not cur:
        return None
    if metric in GROWTH:
        k = GROWTH[metric]
        if not prev or cur.get(k) is None or not prev.get(k) or prev[k] <= 0:
            return None
        g = (cur[k] / prev[k] - 1) * 100
        return {"value": g, "unit": "pct", "text": f"{g:+.1f}% for the full year (annual results)"}
    if metric in MARGIN:
        num, den = MARGIN[metric]
        if cur.get(num) is None or not cur.get(den):
            return None
        m = cur[num] / cur[den] * 100
        prior = (prev[num] / prev[den] * 100) if prev and prev.get(num) is not None and prev.get(den) else None
        return {"value": m, "unit": "pct", "prior": prior,
                "text": f"{m:.1f}% for the full year" + (f" (vs {prior:.1f}% the year before)" if prior is not None else "")}
    if metric in LEVEL and cur.get(LEVEL[metric]) is not None:
        v = cur[LEVEL[metric]]
        return {"value": v, "unit": "crore", "text": f"₹{v:,.0f} crore for the full year (annual results)"}
    return None


def actual_for(metric: str, basis: str | None, qs: list[date], series: dict) -> dict | None:
    """Compute the realised value of a metric over quarters qs. Returns
    {'value', 'unit', 'text', 'compare'} or None if data is missing."""
    if metric in GROWTH:
        k = GROWTH[metric]
        if basis == "qoq" and len(qs) == 1:
            prev = [shift_quarters(qs[0], -1)]
            a, b = _sum(series, qs, k), _sum(series, prev, k)
            what = "vs previous quarter"
        else:
            a, b = _sum(series, qs, k), _sum(series, [shift_quarters(q, -4) for q in qs], k)
            what = "vs same period last year"
        if a is None or b is None or b <= 0:
            return None
        g = (a / b - 1) * 100
        return {"value": g, "unit": "pct", "text": f"{g:+.1f}% {what}"}
    if metric in MARGIN:
        num, den = MARGIN[metric]
        a, r = _sum(series, qs, num), _sum(series, qs, den)
        a0, r0 = _sum(series, [shift_quarters(q, -4) for q in qs], num), _sum(series, [shift_quarters(q, -4) for q in qs], den)
        if a is None or not r:
            return None
        m = a / r * 100
        prior = (a0 / r0 * 100) if (a0 is not None and r0) else None
        txt = f"{m:.1f}%" + (f" (vs {prior:.1f}% a year earlier)" if prior is not None else "")
        return {"value": m, "unit": "pct", "text": txt, "prior": prior}
    if metric in LEVEL:
        v = _sum(series, qs, LEVEL[metric])
        if v is None:
            return None
        return {"value": v, "unit": "crore", "text": f"₹{v:,.0f} crore"}
    return None


def judge(target: dict, actual: dict, metric: str) -> bool | None:
    """True = met, False = not met, None = can't compare."""
    t = target or {}
    typ, lo, hi, unit = t.get("type"), t.get("low"), t.get("high"), t.get("unit")
    v = actual["value"]
    if unit == "bps" and metric in MARGIN:
        if actual.get("prior") is None:
            return None
        v = (actual["value"] - actual["prior"]) * 100       # margin change in bps
        unit = "bps"
    if typ == "direction":
        d = t.get("direction")
        ref = actual.get("prior") if metric in MARGIN else 0.0
        if ref is None or d not in ("up", "down", "stable"):
            return None
        delta = v - ref
        return {"up": delta > 0, "down": delta < 0, "stable": abs(delta) <= (0.5 if metric in MARGIN else 2.0)}[d]
    if unit not in ("pct", "bps", "crore", None):
        return None
    if (unit == "crore") != (actual.get("unit") == "crore"):
        return None            # never compare a ₹ target with a % actual or vice versa
    if typ == "range" and lo is not None and hi is not None:
        return v >= lo  # beating the top of a range counts as delivered
    if typ == "at_least" and lo is not None:
        return v >= lo
    if typ == "at_most" and hi is not None:
        return v <= hi
    if typ == "point":
        p = lo if lo is not None else hi
        if p is None:
            return None
        tol = 0.5 if metric in MARGIN else max(1.0, abs(p) * 0.1)
        return v >= p - tol
    return None


def target_text(t: dict) -> str:
    t = t or {}
    u = {"pct": "%", "bps": " bps", "crore": " crore", None: ""}.get(t.get("unit"), "")
    lo, hi = t.get("low"), t.get("high")
    typ = t.get("type")
    if typ == "range" and lo is not None and hi is not None:
        return f"{lo:g}–{hi:g}{u}"
    if typ == "at_least" and lo is not None:
        return f"at least {lo:g}{u}"
    if typ == "at_most" and hi is not None:
        return f"at most {hi:g}{u}"
    if typ == "point" and (lo is not None or hi is not None):
        return f"about {(lo if lo is not None else hi):g}{u}"
    if typ == "direction" and t.get("direction"):
        return {"up": "higher", "down": "lower", "stable": "stable"}[t["direction"]]
    return "qualitative"


# Words that mean the guidance is NOT about the P&L lines we can check, whatever
# metric the model picked (it mapped "AUM growth" to revenue growth and ROE to PAT
# margin on real Bajaj Finance transcripts). Deterministic guard on top of the model.
NON_PNL = re.compile(r"\baum\b|assets under management|loan|book|disburs|deposit|fee income|\bfee\b|"
                     r"return on|\broe\b|\broa\b|\bnim\b|net interest margin|credit cost|cost of funds|"
                     r"gross margin|order|volume|capacity|customer|branch|market share|capex|opex|"
                     r"segment|export|gold|msme|price increase|pricing", re.I)


def evaluate(claim: dict, said_in: date, series: dict, latest: date, annual: dict | None = None) -> dict:
    """claim: verified guidance claim. said_in: quarter of the call. series:
    {quarter_end_iso: metrics}. latest: latest reported quarter end. annual:
    {fy_end_iso: metrics} from Q4 filings' full-year columns."""
    annual = annual or {}
    metric = claim.get("metric") or "other"
    scope = claim.get("scope") or "company"
    per = parse_period(claim.get("period_text") or "", said_in)
    base = {"period_label": per["label"] if per else (claim.get("period_text") or "unspecified"),
            "target_text": target_text(claim.get("target") or {}), "assessed_by": "code", "scope": scope,
            "segment": claim.get("segment")}
    # Judge by the topic label: quotes for genuine company-level targets often mention drivers
    # ("revenue growth of 15-17%, led by mobile volumes"). Fall back to the quote only if no topic.
    if scope == "company" and NON_PNL.search(claim.get("topic") or claim.get("quote") or ""):
        scope = "operational"
        base["scope"] = scope
    if scope != "company":
        what = f"the {claim['segment']} segment" if claim.get("segment") else (
            "volumes, capacity or other operating figures" if scope == "operational" else "one segment")
        return {**base, "status": "unverifiable",
                "detail": f"About {what}, which the consolidated results statement doesn't report."}
    if metric not in GROWTH and metric not in MARGIN and metric not in LEVEL:
        return {**base, "status": "unverifiable",
                "detail": "Not measurable from the results statements (e.g. order book, AUM, volumes, qualitative)."}
    if not per and re.search(r"going forward|go(ing)? ahead|from here|next few quarters|coming quarters|"
                             r"sustain|maintain|band", f"{claim.get('period_text') or ''} {claim.get('quote') or ''}", re.I):
        since = [q for q in sorted(series) if date.fromisoformat(q) > said_in and date.fromisoformat(q) <= latest]
        if not since:
            return {**base, "status": "pending", "period_label": "since the call",
                    "detail": "No quarter reported since this was said."}
        per = {"kind": "since", "quarters": [date.fromisoformat(q) for q in since], "label": "quarters since the call"}
        base["period_label"] = per["label"]
        act = actual_for(metric, claim.get("basis"), per["quarters"], series)
        if act is None:
            return {**base, "status": "unverifiable", "detail": "Reported figures for those quarters are missing."}
        met = judge(claim.get("target") or {}, act, metric)
        if met is None:
            return {**base, "status": "unverifiable", "actual_text": act["text"],
                    "detail": "Target wording can't be compared numerically."}
        span = qlabel(per["quarters"][0]) if len(since) == 1 else f"{qlabel(per['quarters'][0])}–{qlabel(per['quarters'][-1])}"
        return {**base, "status": "on_track" if met else "off_track", "actual_text": act["text"],
                "actual_value": round(act["value"], 2), "actual_span": span, "complete": False,
                "detail": "Open-ended guidance, checked against every quarter reported since the call."}
    if not per:
        return {**base, "status": "unverifiable", "detail": "No specific period was given."}
    qs = per["quarters"]
    # full year already reported: use the annual columns printed in the Q4 filing
    if per["kind"] == "year" and qs[-1] <= latest:
        act = actual_annual(metric, qs[-1], annual)
        if act is not None:
            met = judge(claim.get("target") or {}, act, metric)
            if met is not None:
                return {**base, "status": "delivered" if met else "missed", "actual_text": act["text"],
                        "actual_value": round(act["value"], 2), "actual_span": per["label"], "complete": True,
                        "detail": None}
    reported = [q for q in qs if q <= latest and q.isoformat() in series]
    if not reported:
        nxt = min(qs)
        return {**base, "status": "pending", "detail": f"First relevant results ({qlabel(nxt)}) not yet reported."}
    act = actual_for(metric, claim.get("basis"), reported, series)
    if act is not None and metric in LEVEL and len(reported) < len(qs):
        # absolute full-period target, period incomplete: compare the run-rate, and say so
        run = act["value"] * len(qs) / len(reported)
        act = {"value": run, "unit": "crore",
               "text": f"₹{act['value']:,.0f} crore so far; at that run-rate ₹{run:,.0f} crore for {per['label']}"}
    if act is None:
        return {**base, "status": "unverifiable", "detail": "Reported figures for the comparison period are missing."}
    met = judge(claim.get("target") or {}, act, metric)
    complete = len(reported) == len(qs)
    span = qlabel(reported[0]) if len(reported) == 1 else f"{qlabel(reported[0])}–{qlabel(reported[-1])}"
    if met is None:
        return {**base, "status": "unverifiable", "actual_text": act["text"], "actual_span": span,
                "detail": "Target wording can't be compared numerically."}
    status = ("delivered" if met else "missed") if complete else ("on_track" if met else "off_track")
    return {**base, "status": status, "actual_text": act["text"], "actual_value": round(act["value"], 2),
            "actual_span": span, "complete": complete,
            "detail": None if complete else f"Only {span} reported so far for {per['label']}."}
