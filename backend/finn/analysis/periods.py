"""Indian financial-year arithmetic.

FY27 runs 1 Apr 2026 – 31 Mar 2027. Quarters: Q1 Apr–Jun, Q2 Jul–Sep,
Q3 Oct–Dec, Q4 Jan–Mar. Everything here is pure functions on dates so it can
be tested exhaustively.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

QUARTER_ENDS = ((3, 31), (6, 30), (9, 30), (12, 31))


def quarter_end_on_or_before(d: date) -> date:
    for y in (d.year, d.year - 1):
        for m, dd in sorted(QUARTER_ENDS, reverse=True):
            q = date(y, m, dd)
            if q <= d:
                return q
    raise ValueError(d)


def shift_quarters(q: date, n: int) -> date:
    """Quarter end n quarters after (n<0: before) quarter end q."""
    idx = q.year * 4 + (q.month - 1) // 3 + n
    y, k = divmod(idx, 4)
    m, dd = QUARTER_ENDS[k]
    return date(y, m, dd)


def fy_of(q: date) -> int:
    """FY number (e.g. 27) of the fiscal year containing quarter end q."""
    return (q.year + 1 if q.month >= 4 else q.year) % 100


def fq_of(q: date) -> int:
    return {6: 1, 9: 2, 12: 3, 3: 4}[q.month]


def label(q: date) -> str:
    return f"Q{fq_of(q)} FY{fy_of(q):02d}"


def fy_quarters(fy: int) -> list[date]:
    """The four quarter ends of FY<fy> (two-digit or four-digit year)."""
    end_year = fy if fy > 100 else 2000 + fy
    return [date(end_year - 1, 6, 30), date(end_year - 1, 9, 30), date(end_year - 1, 12, 31), date(end_year, 3, 31)]


def period_for_filing(filed: date, text: str = "") -> date:
    """Which quarter a results filing / transcript reports on.

    Prefer an explicit 'quarter ended <date>' in the text; otherwise the latest
    quarter end at least a week before the filing (results come 2–8 weeks after
    quarter end, transcripts a few days after results)."""
    explicit = parse_quarter_ended(text)
    if explicit and explicit <= filed:
        return explicit
    return quarter_end_on_or_before(filed - timedelta(days=7))


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_quarter_ended(text: str) -> date | None:
    t = (text or "").lower()
    m = re.search(r"(?:quarter|period|half[- ]year|year)\s+ended\s+(?:on\s+)?"
                  r"(\d{1,2})(?:st|nd|rd|th)?[\s\-/.]*([a-z]{3,9}|\d{1,2})[\s,\-/.]*(\d{4}|\d{2})\b", t)
    if not m:
        m2 = re.search(r"(?:quarter|period|half[- ]year|year)\s+ended\s+(?:on\s+)?([a-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})", t)
        if not m2:
            return None
        mon, day, yr = m2.group(1)[:3], int(m2.group(2)), int(m2.group(3))
        month = _MONTHS.get(mon)
    else:
        day, mon, yr = int(m.group(1)), m.group(2), int(m.group(3))
        month = int(mon) if mon.isdigit() else _MONTHS.get(mon[:3])
        if yr < 100:
            yr += 2000
    if not month:
        return None
    try:
        d = date(yr, month, day)
    except ValueError:
        return None
    return d if (d.month, d.day) in QUARTER_ENDS else None


def parse_period(text: str, reference: date) -> dict | None:
    """Turn management's period wording into concrete quarters.

    reference = the quarter the statement was made in (to resolve 'next
    quarter', 'this year', 'H2'). Returns {'kind', 'quarters': [...], 'label'}.
    """
    t = (text or "").strip().lower().replace("’", "'")
    cur_fy = fy_of(reference)

    def fy_num(s: str) -> int:
        n = int(s)
        return n % 100 if n > 100 else n

    m = re.search(r"\bq([1-4])\s*(?:of\s*)?fy\s*'?(\d{2,4})", t)
    if m:
        q = fy_quarters(fy_num(m.group(2)))[int(m.group(1)) - 1]
        return {"kind": "quarter", "quarters": [q], "label": label(q)}
    m = re.search(r"\bh([12])\s*(?:of\s*)?fy\s*'?(\d{2,4})", t)
    if m:
        qs = fy_quarters(fy_num(m.group(2)))
        qs = qs[:2] if m.group(1) == "1" else qs[2:]
        return {"kind": "half", "quarters": qs, "label": f"H{m.group(1)} FY{fy_num(m.group(2)):02d}"}
    m = re.search(r"\bfy\s*'?(\d{2,4})\b", t) or re.search(r"\b(?:financial|fiscal) year\s*20(\d{2})", t)
    if m:
        fy = fy_num(m.group(1))
        return {"kind": "year", "quarters": fy_quarters(fy), "label": f"FY{fy:02d}"}
    if re.search(r"next quarter|coming quarter|following quarter", t):
        q = shift_quarters(reference, 1)
        return {"kind": "quarter", "quarters": [q], "label": label(q)}
    if re.search(r"second half|\bh2\b", t):
        qs = fy_quarters(cur_fy)[2:]
        return {"kind": "half", "quarters": qs, "label": f"H2 FY{cur_fy:02d}"}
    if re.search(r"this (financial |fiscal )?year|current (financial |fiscal )?year|full year|\bthe year\b|this fiscal", t):
        return {"kind": "year", "quarters": fy_quarters(cur_fy), "label": f"FY{cur_fy:02d}"}
    if re.search(r"next (financial |fiscal )?year", t):
        return {"kind": "year", "quarters": fy_quarters(cur_fy + 1), "label": f"FY{cur_fy + 1:02d}"}
    return None
