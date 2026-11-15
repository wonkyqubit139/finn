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

from datetime import date

from .periods import label as qlabel, parse_period, shift_quarters

GROWTH = {"revenue_growth": "revenue", "ebitda_growth": "ebitda", "pat_growth": "pat"}
MARGIN = {"ebitda_margin": ("ebitda", "revenue"), "pat_margin": ("pat", "revenue")}


def _sum(series: dict, qs: list[date], key: str) -> float | None:
    vals = [series.get(q.isoformat(), {}).get(key) for q in qs]
    return None if any(v is None for v in vals) else sum(vals)


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
    if unit not in ("pct", "bps", None):
        return None
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


def evaluate(claim: dict, said_in: date, series: dict, latest: date) -> dict:
    """claim: verified guidance claim. said_in: quarter of the call. series:
    {quarter_end_iso: metrics}. latest: latest reported quarter end."""
    metric = claim.get("metric") or "other"
    per = parse_period(claim.get("period_text") or "", said_in)
    base = {"period_label": per["label"] if per else (claim.get("period_text") or "unspecified"),
            "target_text": target_text(claim.get("target") or {}), "assessed_by": "code"}
    if metric not in GROWTH and metric not in MARGIN:
        return {**base, "status": "unverifiable",
                "detail": "Not measurable from the results statements (e.g. order book, AUM, volumes, qualitative)."}
    if not per:
        return {**base, "status": "unverifiable", "detail": "No specific period was given."}
    qs = per["quarters"]
    reported = [q for q in qs if q <= latest and q.isoformat() in series]
    if not reported:
        nxt = min(qs)
        return {**base, "status": "pending", "detail": f"First relevant results ({qlabel(nxt)}) not yet reported."}
    act = actual_for(metric, claim.get("basis"), reported, series)
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
