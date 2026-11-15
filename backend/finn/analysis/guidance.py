"""Management guidance from earnings-call transcripts.

The model lists forward-looking statements by management (not analysts), each
with a verbatim quote and page. Then code checks every quote really is in the
transcript. Claims whose quote can't be found are dropped and counted, never
shown. That is the main guard against invented guidance.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from .. import config
from ..llm import complete_json

PROMPT_VERSION = "guid-v2"
MAX_CHARS = 160_000          # ~40k tokens; transcripts are usually far shorter

METRICS = ["revenue_growth", "ebitda_growth", "pat_growth", "ebitda_margin", "pat_margin",
           "revenue", "capex", "volume_growth", "other"]

SYSTEM = """You read an Indian listed company's earnings-call transcript and list what MANAGEMENT
said about the FUTURE: guidance, targets, expectations, commitments. Ignore analysts' questions,
history, and generic optimism with no content. Use only the transcript.
For each statement return:
- speaker: as named in the transcript
- page: page number (from the === PAGE n === markers) where the quote is
- quote: an EXACT contiguous excerpt (max 45 words) copied character-for-character
- topic: 3-6 word label
- scope: "company" if it is about the WHOLE company's consolidated numbers, "segment" if about one
  business/segment/product line, "operational" for volumes, capacity, order book, capex, market share
- segment: the segment/product name when scope is "segment", else null
- metric: one of %s   (revenue_growth/margins/pat/ebitda only for scope "company"; else "other")
- basis: "yoy" | "qoq" | "level" | null      (growth vs last year, vs last quarter, or an absolute level)
- target: {"type": "range"|"at_least"|"at_most"|"point"|"direction",
           "low": number|null, "high": number|null, "unit": "pct"|"bps"|"crore"|null,
           "direction": "up"|"down"|"stable"|null}
- period_text: the period as said ("FY27", "Q3", "H2", "next year", "medium term"...)
- specificity: "numeric" | "directional" | "qualitative"
Return {"claims": [...]} with at most 12 of the most material statements, numeric ones first.""" % METRICS


def transcript_input(page_texts: list[str]) -> str:
    parts, total = [], 0
    for i, t in enumerate(page_texts, 1):
        chunk = f"=== PAGE {i} ===\n{t}"
        if total + len(chunk) > MAX_CHARS:
            break
        parts.append(chunk)
        total += len(chunk)
    return "\n\n".join(parts)


def extract(page_texts: list[str]) -> list[dict]:
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": transcript_input(page_texts)}]
    # Extraction (find statements, copy quotes) doesn't need a thinking model, and on real 20–30 page
    # transcripts the thinking model timed out. Fast tier first; deep tier only as a fallback.
    res = complete_json("guidance", PROMPT_VERSION, messages, tier=config.LLM_FAST, max_tokens=5000,
                        fallback=config.LLM_DEEP)
    claims = (res or {}).get("claims") or []
    return [c for c in claims if isinstance(c, dict) and c.get("quote")]


# ---- quote verification -----------------------------------------------------------------

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("–", "-").replace("—", "-")
    s = re.sub(r"-\s*\n\s*", "", s)              # words hyphenated across a line break
    s = re.sub(r"[^a-z0-9%.]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def find_quote(quote: str, page_texts: list[str], hint_page: int | None) -> tuple[int | None, float]:
    """Return (page where the quote occurs, match score 0–1). Exact match after
    normalisation scores 1.0; otherwise the best fuzzy window ≥ 0.9 is accepted
    (PDF text extraction sometimes splits or merges words)."""
    q = _norm(quote)
    if len(q) < 12:
        return None, 0.0
    order = list(range(len(page_texts)))
    if hint_page and 1 <= hint_page <= len(page_texts):
        h = hint_page - 1
        order = [h] + [i for i in (h - 1, h + 1) if 0 <= i < len(page_texts)] + [i for i in order if abs(i - h) > 1]
    normed = {}
    for i in order:
        normed[i] = _norm(page_texts[i])
        if q in normed[i]:
            return i + 1, 1.0
    # fuzzy: compare against windows anchored on the quote's first words
    qw = q.split()
    n = len(qw)
    best = (None, 0.0)
    for i in order:
        words = normed[i].split()
        anchors = [k for k, w in enumerate(words) if w == qw[0]] or range(0, max(1, len(words) - n + 1), 3)
        for k in anchors:
            window = " ".join(words[k:k + n + 2])
            r = SequenceMatcher(None, q, window).ratio()
            if r > best[1]:
                best = (i + 1, r)
    return best if best[1] >= 0.9 else (None, best[1])


def verify(claims: list[dict], page_texts: list[str]) -> tuple[list[dict], list[dict]]:
    ok, dropped = [], []
    for c in claims:
        page, score = find_quote(c.get("quote", ""), page_texts, c.get("page") if isinstance(c.get("page"), int) else None)
        if page is None:
            dropped.append({**c, "match_score": round(score, 2)})
        else:
            ok.append({**c, "page": page, "match_score": round(score, 2)})
    return ok, dropped
