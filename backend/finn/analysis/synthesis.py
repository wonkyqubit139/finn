"""Business overview, bull/bear case and assessment of qualitative claims.

The deep model sees ONLY: the computed financial table (from results filings),
the verified management quotes, the Promise Tracker results, and a few pages
of the latest transcript's opening remarks. Every point must cite a source
tag such as "D2:p5" (document D2, page 5) or "FIN" (the computed table, which
itself traces to the filings). Points with no valid citation are removed.
"""
from __future__ import annotations

import json
import re

from .. import config
from ..llm import complete_json

PROMPT_VERSION = "syn-v2"

SYSTEM = """You are an equity analyst writing for a portfolio manager. Use ONLY the material provided:
no outside knowledge, no news, no market data, no assumptions about the company beyond the sources.
Every item must cite at least one source tag from the material: "D<n>:p<page>" for a document page, or
"FIN" for the financial table. If the material doesn't support a point, leave it out.
Return JSON:
{
 "overview": [{"text": "...", "cite": ["D1:p3"]}],             // 2-3 sentences: what the business does, how it makes money
 "bull": [{"point": "...", "cite": [...]}],                     // 3-4 strongest arguments for owning it
 "bear": [{"point": "...", "cite": [...]}],                     // 3-4 strongest arguments against
 "claim_assessments": [{"id": "C3", "verdict": "delivered"|"missed"|"mixed"|"too_early"|"cannot_tell",
                        "reason": "one sentence referencing specific numbers", "cite": [...]}],
 "narrative_gap": {"text": "2-4 sentences: where management's narrative and the reported numbers diverge most", "cite": [...]}
}
Only assess claims listed under QUALITATIVE CLAIMS TO ASSESS. For segment, volume or capacity guidance, the
evidence is usually what management reported on the LATEST call (in the transcript excerpts): compare the
earlier promise with that, cite the page, and say "cannot_tell" if the excerpts don't cover it.
Be specific and quantitative; avoid generic statements."""

TAG = re.compile(r"^(FIN|D(\d+):p(\d+))$")


def build_prompt(company: str, fin_table: list[dict], promises: list[dict], qual: list[dict],
                 excerpts: list[tuple[str, int, str]]) -> str:
    lines = [f"COMPANY: {company}", "", "FINANCIAL TABLE [FIN] (₹ crore, from the company's results filings):"]
    for r in fin_table:
        lines.append(json.dumps({k: (round(v, 1) if isinstance(v, float) else v) for k, v in r.items()
                                 if k not in ("source",)}))
    lines += ["", "MANAGEMENT GUIDANCE ALREADY CHECKED IN CODE:"]
    for p in promises:
        lines.append(f'- [{p["ref"]}:p{p["page"]}] "{p["quote"]}" → {p["status"]}'
                     + (f' (actual {p["actual_text"]})' if p.get("actual_text") else ""))
    lines += ["", "QUALITATIVE CLAIMS TO ASSESS:"]
    for c in qual:
        lines.append(f'- {c["id"]} [{c["ref"]}:p{c["page"]}] said in {c["said_in"]}: "{c["quote"]}"')
    lines += ["", "TRANSCRIPT EXCERPTS:"]
    for ref, page, text in excerpts:
        lines.append(f"--- {ref}:p{page} ---\n{text[:4000]}")
    return "\n".join(lines)


def clean_cites(cites, valid: set[str]) -> list[str]:
    out = []
    for c in cites or []:
        c = str(c).strip().strip("[]")
        if TAG.match(c) and (c == "FIN" or c in valid):
            out.append(c)
    return out


def synthesize(company: str, fin_table, promises, qual, excerpts, valid_tags: set[str]) -> dict:
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": build_prompt(company, fin_table, promises, qual, excerpts)}]
    raw = complete_json("synthesis", PROMPT_VERSION, messages, tier=config.LLM_DEEP, max_tokens=5000,
                        temperature=0.2)
    return validate(raw, valid_tags, {c["id"] for c in qual})


def validate(raw: dict, valid_tags: set[str], qual_ids: set[str]) -> dict:
    """Drop anything that doesn't cite a real source."""
    raw = raw or {}
    dropped = 0

    def keep(items, text_key):
        nonlocal dropped
        out = []
        for it in items or []:
            if not isinstance(it, dict) or not it.get(text_key):
                continue
            cites = clean_cites(it.get("cite"), valid_tags)
            if cites:
                out.append({text_key: str(it[text_key]).strip(), "cite": cites})
            else:
                dropped += 1
        return out

    assessments = []
    for a in raw.get("claim_assessments") or []:
        if isinstance(a, dict) and a.get("id") in qual_ids and a.get("verdict") in (
                "delivered", "missed", "mixed", "too_early", "cannot_tell"):
            assessments.append({"id": a["id"], "verdict": a["verdict"], "reason": str(a.get("reason") or ""),
                                "cite": clean_cites(a.get("cite"), valid_tags)})
    gap = raw.get("narrative_gap") or {}
    gap_cites = clean_cites(gap.get("cite"), valid_tags) if isinstance(gap, dict) else []
    return {"overview": keep(raw.get("overview"), "text"), "bull": keep(raw.get("bull"), "point"),
            "bear": keep(raw.get("bear"), "point"), "claim_assessments": assessments,
            "narrative_gap": {"text": gap.get("text"), "cite": gap_cites} if gap_cites and gap.get("text") else None,
            "uncited_dropped": dropped}
