"""Deterministic priority scoring (0–100).

A transparent table rather than a model: an investor can ask "why is this
ranked above that?" and the answer is a number they can see and change.
Score = base(category, sub_type) + boost if the investor watches the category.
"""
from __future__ import annotations

BASE: dict[str, dict[str, int]] = {
    "results":           {"outcome": 90, "press_release": 80, "presentation": 55,
                          "intimation": 34, "newspaper_ad": 8, "*": 70},
    "M&A":               {"deal": 85, "subsidiary": 45, "*": 80},
    "fund_raise":        {"equity": 78, "buyback": 80, "debt": 35, "*": 70},
    "management_change": {"kmp_exit": 90, "kmp_join": 85, "director_exit": 60,
                          "director_join": 50, "other_exit": 40, "other_join": 35, "*": 50},
    "litigation":        {"regulatory": 75, "legal": 68, "*": 70},
    "pledging":          {"create": 72, "release": 45, "*": 60},
    "credit_rating":     {"downgrade": 80, "upgrade": 62, "reaffirm": 30, "*": 40},
    "capex":             {"*": 70},
    "bonus_split":       {"*": 62},
    "press_release":     {"order_win": 60, "general": 42, "*": 42},
    "dividend":          {"*": 50},
    "earnings_call":     {"transcript": 48, "notice": 32, "recording": 22, "*": 30},
    "insider_trading":   {"*": 40},
    "agm_egm":           {"*": 22},
    "investor_meetings": {"*": 18},
    "postal_ballot":     {"*": 18},
    "unclassified":      {"*": 5},
}

WATCH_BOOST = 8
HIGH, MEDIUM = 70, 40


def score(category: str, sub_type: str, watched: list[str]) -> int:
    table = BASE.get(category, BASE["unclassified"])
    s = table.get(sub_type, table["*"])
    # Boost only filings that already carry substance; a watched category
    # should not lift routine paperwork (e.g. a results newspaper ad) into view.
    if category in watched and s >= 30:
        s += WATCH_BOOST
    return max(0, min(100, s))


def tier(priority: int) -> str:
    if priority >= HIGH:
        return "high"
    if priority >= MEDIUM:
        return "medium"
    return "routine"
