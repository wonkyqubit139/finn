"""Management-change filings: who, what role, and their background.

SEBI's disclosure rules require an appointment filing to include a brief
profile of the appointee, so the background comes from the filing itself
(primary source) rather than from LinkedIn or news. The model extracts it with
a verbatim quote, which is verified against the page text like guidance quotes.
"""
from __future__ import annotations

from .. import config
from ..llm import complete_json
from .guidance import find_quote

PROMPT_VERSION = "ppl-v1"

SYSTEM = """From this Indian stock-exchange filing about a management or board change, extract
the people changes. Use only the filing text. Return JSON:
{"changes": [{"person": "...", "role": "...", "change": "appointment"|"resignation"|"retirement"|"re-designation"|"other",
  "effective": "date as written or null", "reason": "stated reason or null",
  "background": "1-2 sentences: prior roles, experience, qualifications, as stated in the filing; null if none",
  "quote": "EXACT excerpt (max 40 words) from the filing supporting the background or the change",
  "page": <page number>}]}"""


def extract(page_texts: list[str]) -> list[dict]:
    body = "\n\n".join(f"=== PAGE {i} ===\n{t[:6000]}" for i, t in enumerate(page_texts[:6], 1))
    res = complete_json("people", PROMPT_VERSION, [{"role": "system", "content": SYSTEM},
                                                   {"role": "user", "content": body}],
                        tier=config.LLM_FAST, max_tokens=2000)
    out = []
    for c in (res or {}).get("changes") or []:
        if not isinstance(c, dict) or not c.get("person"):
            continue
        page, score = find_quote(c.get("quote") or "", page_texts, c.get("page") if isinstance(c.get("page"), int) else None)
        if page is None:
            c = {**c, "background": None, "quote": None}   # unverifiable background is withheld
        out.append({**c, "page": page})
    return out[:4]
