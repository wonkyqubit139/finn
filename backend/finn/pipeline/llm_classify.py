"""Batched LLM classification for announcements the rules couldn't settle.

Up to 25 filings go in one request (one round-trip instead of 25), using only
the exchange's own subject + description text. The model must pick from a
fixed category/sub-type vocabulary; anything outside it is discarded.
"""
from __future__ import annotations

import json

from .. import config
from ..llm import LLMUnavailable, complete_json
from .priority import BASE

PROMPT_VERSION = "cls-v1"
BATCH = 25

GUIDE = """Categories (pick exactly one):
results – quarterly/annual results, results board meeting, results deck
M&A – acquisition, merger, demerger, JV, stake purchase/sale in a subsidiary
fund_raise – rights issue, QIP, preferential allotment, buyback, debt (CP/NCD)
management_change – CEO/CFO/MD/director joining, resigning, retiring
litigation – lawsuits, regulatory orders, fines, warnings, insolvency
insider_trading – promoter/insider buying or selling own shares
earnings_call – concall notice, transcript or recording
investor_meetings – meetings with specific investors/funds, conferences
credit_rating – rating assigned/upgraded/downgraded/reaffirmed
dividend – cash dividend declared, record date
bonus_split – bonus issue or stock split
capex – new plant/facility/capacity expansion approved
press_release – order wins, products, partnerships, clarifications not covered above
postal_ballot, agm_egm, pledging
unclassified – routine paperwork that does not move the stock"""


def _subtypes() -> dict[str, list[str]]:
    return {c: [k for k in v if k != "*"] for c, v in BASE.items()}


def classify_batch(items: list[dict]) -> dict[str, dict]:
    """items: [{id, symbol, subject, body}] → {id: {category, sub_type, summary}}"""
    out: dict[str, dict] = {}
    allowed = _subtypes()
    for i in range(0, len(items), BATCH):
        chunk = items[i:i + BATCH]
        listing = [{"id": it["id"], "company": it["symbol"], "subject": it["subject"],
                    "text": (it.get("body") or "")[:500]} for it in chunk]
        messages = [
            {"role": "system", "content":
                "You classify Indian stock-exchange corporate announcements. Use ONLY the text given; "
                "do not use outside knowledge about the companies. " + GUIDE +
                "\nAllowed sub_type values per category (use '' if none fits): " + json.dumps(allowed) +
                "\nAlso write `summary`: one plain sentence (max 22 words) saying what was announced, "
                "taken from the text; '' if the text is pure boilerplate."
                "\nReturn JSON: {\"items\": [{\"id\", \"category\", \"sub_type\", \"summary\"}]}"},
            {"role": "user", "content": json.dumps(listing, ensure_ascii=False)},
        ]
        try:
            res = complete_json("classify", PROMPT_VERSION, messages, tier=config.LLM_FAST, max_tokens=3000)
        except LLMUnavailable:
            continue
        for r in (res or {}).get("items", []):
            cat = r.get("category")
            if r.get("id") not in {c["id"] for c in chunk} or cat not in BASE:
                continue
            sub = r.get("sub_type") if r.get("sub_type") in allowed.get(cat, []) else "*"
            out[r["id"]] = {"category": cat, "sub_type": sub,
                            "summary": (r.get("summary") or "").strip()[:240] or None}
    return out
