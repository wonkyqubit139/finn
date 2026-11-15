"""Primary documents for a company, straight from its NSE filings.

Discovery: the company's own exchange announcements over ~15 months, classified
by the same rules as the feed, give us results filings, concall transcripts and
investor presentations, each with its exchange-hosted PDF.

Storage: PDFs are cached on disk by content hash; page text goes into
doc_pages so every later claim can cite (document, page) and quotes can be
verified against the actual text.
"""
from __future__ import annotations

import base64
import hashlib
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .. import config, db
from ..analysis.periods import period_for_filing
from ..pipeline.classify import classify
from ..sources.announcements import NSEClient, RawAnnouncement
from ..sources.http import SourceError, get_with_retry

log = logging.getLogger("finn.docs")
DOC_DIR = config.DB_PATH.parent / "docs"
MAX_PDF_BYTES = 40 * 1024 * 1024
LOOKBACK_DAYS = 470          # ~5 quarters of filings + slack


@dataclass
class FoundDoc:
    id: str
    symbol: str
    kind: str                # results | transcript | presentation
    period_end: date
    title: str
    url: str
    filed_at: datetime
    rank: int                # lower = preferred when several filings cover one period


def doc_id(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:16]


def _results_rank(subject: str) -> int:
    s = subject.lower()
    if "financial result" in s:
        return 0
    if "integrated filing" in s:
        return 1
    if "outcome of board meeting" in s:
        return 2
    return 3


def pick_documents(anns: list[RawAnnouncement]) -> list[FoundDoc]:
    """From raw announcements, keep the documents the dossier needs."""
    out: list[FoundDoc] = []
    for a in anns:
        if not a.attachment_url or not a.attachment_url.lower().endswith(".pdf"):
            continue
        c = classify(a.subject, a.body)
        kind = None
        if c.category == "results" and c.sub_type in ("outcome", "press_release"):
            kind = "results"
        elif c.category == "earnings_call" and c.sub_type == "transcript":
            kind = "transcript"
        elif c.category == "results" and c.sub_type == "presentation":
            kind = "presentation"
        if not kind:
            continue
        filed = a.published_at.astimezone(config.IST).date()
        period = period_for_filing(filed, a.body)
        rank = _results_rank(a.subject) if kind == "results" else 0
        out.append(FoundDoc(doc_id(a.attachment_url), a.symbol, kind, period,
                            f"{a.subject}: {a.body[:160]}", a.attachment_url, a.published_at, rank))
    return out


def discover(symbol: str, client: NSEClient | None = None, today: date | None = None) -> list[FoundDoc]:
    """Fetch the company's filings in 90-day slices and pick the useful PDFs."""
    client = client or NSEClient()
    today = today or datetime.now(config.IST).date()
    anns: list[RawAnnouncement] = []
    start = today - timedelta(days=LOOKBACK_DAYS)
    while start < today:
        end = min(start + timedelta(days=90), today)
        anns.extend(client.announcements(symbol, start, end))
        start = end + timedelta(days=1)
    seen, uniq = set(), []
    for a in anns:
        if a.id not in seen:
            seen.add(a.id)
            uniq.append(a)
    return pick_documents(uniq)


def save_found(conn, docs: list[FoundDoc]) -> None:
    for d in docs:
        conn.execute(
            "INSERT INTO documents(id, symbol, kind, period_end, title, url, source, filed_at) "
            "VALUES(?,?,?,?,?,?, 'nse', ?) ON CONFLICT(id) DO UPDATE SET period_end=excluded.period_end, "
            "kind=excluded.kind, title=excluded.title",
            (d.id, d.symbol, d.kind, d.period_end.isoformat(), d.title, d.url, db.to_utc_iso(d.filed_at)))


# ---- download + text ------------------------------------------------------------------

def _pdf_text_pages(data: bytes) -> list[str]:
    import pymupdf
    with pymupdf.open(stream=data, filetype="pdf") as pdf:
        return [p.get_text("text") for p in pdf]


def ingest_pdf(conn, did: str, data: bytes) -> dict:
    """Store a PDF's bytes on disk and its page text in doc_pages."""
    if not data.startswith(b"%PDF"):
        raise SourceError("not a PDF")
    sha = hashlib.sha256(data).hexdigest()
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    path = DOC_DIR / f"{sha}.pdf"
    if not path.exists():
        path.write_bytes(data)
    pages = _pdf_text_pages(data)
    conn.execute("DELETE FROM doc_pages WHERE doc_id=?", (did,))
    conn.executemany("INSERT INTO doc_pages(doc_id, page_no, text) VALUES(?,?,?)",
                     [(did, i + 1, t) for i, t in enumerate(pages)])
    text_pages = sum(1 for t in pages if len(t.strip()) > 200)
    conn.execute("UPDATE documents SET sha256=?, pages=?, text_pages=?, local_path=?, status='downloaded', error=NULL "
                 "WHERE id=?", (sha, len(pages), text_pages, str(path), did))
    return {"pages": len(pages), "text_pages": text_pages}


def download(conn, did: str, client: NSEClient | None = None) -> dict:
    row = conn.execute("SELECT * FROM documents WHERE id=?", (did,)).fetchone()
    if row["status"] == "downloaded" and row["local_path"]:
        return {"pages": row["pages"], "text_pages": row["text_pages"], "cached": True}
    client = client or NSEClient()
    try:
        r = get_with_retry(client.s, row["url"], headers={"Accept": "application/pdf,*/*",
                                                          "Referer": "https://www.nseindia.com/"})
        data = r.content
        if len(data) > MAX_PDF_BYTES:
            raise SourceError(f"PDF too large ({len(data) // 1_000_000} MB)")
        return ingest_pdf(conn, did, data)
    except Exception as e:
        conn.execute("UPDATE documents SET status='failed', error=? WHERE id=?", (str(e)[:300], did))
        raise


def pages(conn, did: str) -> list[str]:
    return [r["text"] for r in conn.execute("SELECT text FROM doc_pages WHERE doc_id=? ORDER BY page_no", (did,))]


def render_pages(local_path: str, page_numbers: list[int], dpi: int = 110) -> list[str]:
    """PNG data-URLs of selected pages, for scanned PDFs the text layer can't read."""
    import pymupdf
    out = []
    with pymupdf.open(local_path) as pdf:
        for n in page_numbers:
            if 1 <= n <= len(pdf):
                pix = pdf[n - 1].get_pixmap(dpi=dpi)
                out.append("data:image/png;base64," + base64.b64encode(pix.tobytes("png")).decode())
    return out
