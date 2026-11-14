"""Text helpers shared by the API and the alert engine."""
from __future__ import annotations

import re

_BOILER = re.compile(r"^.{0,120}?\bhas (informed|submitted to) the exchange\s*(about|regarding|that|on|of|with)?\s*",
                     re.I)


def headline(subject: str, body: str | None, summary: str | None, limit: int = 220) -> str:
    """Best one-line description: LLM summary > exchange text minus boilerplate > subject."""
    if summary:
        return summary
    text = _BOILER.sub("", body or "").strip()
    if len(text) < 12:
        return subject
    text = text[0].upper() + text[1:]
    return text if len(text) <= limit else text[:limit - 3].rsplit(" ", 1)[0] + "…"
