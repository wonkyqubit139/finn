"""Enrich important portfolio filings during refresh.

results outcome  → Revenue / EBITDA / PBT / PAT with QoQ and YoY (same reader as research)
management change (senior/board) → who, role, background from the filing's own profile

Bounded per run (the model's free tier is rate-limited); failures are stored
with a reason so a bad PDF isn't retried forever.
"""
from __future__ import annotations

import json
import logging

from .. import config, db
from ..analysis import people
from ..llm import LLMUnavailable
from ..research import documents as D
from ..research.build import FIN_INDUSTRY, _results_view
from ..sources.announcements import NSEClient

log = logging.getLogger("finn.enrich")
MAX_RESULTS, MAX_PEOPLE = 6, 4


def _doc_for(conn, a) -> dict:
    did = D.doc_id(a["attachment_url"])
    kind = "results" if a["category"] == "results" else "filing"
    conn.execute("INSERT OR IGNORE INTO documents(id, symbol, kind, title, url, source, filed_at) VALUES(?,?,?,?,?,?,?)",
                 (did, a["symbol"], kind, a["subject"], a["attachment_url"], a["source"], a["published_at"]))
    return dict(conn.execute("SELECT * FROM documents WHERE id=?", (did,)).fetchone())


def compact_results(v: dict, doc: dict) -> dict:
    keep = ("revenue", "ebitda", "pbt", "pat", "ebitda_margin", "pat_margin", "ebitda_note")
    pick = lambda m: {k: m.get(k) for k in keep} if m else None  # noqa: E731
    return {"type": "results", "ok": True, "period_label": v["period_label"], "basis": v["basis"],
            "financial": v["financial"], "current": pick(v["current"]), "previous": pick(v["previous"]),
            "year_ago": pick(v["year_ago"]), "qoq": v["qoq"], "yoy": v["yoy"], "checks": v["checks"],
            "unit_note": v["unit_note"], "page": v["source"]["page"], "url": doc["url"]}


def enrich_pending(since_iso: str) -> dict:
    if not config.LLM_FAST.enabled:
        return {"skipped": "no model key"}
    done = {"results": 0, "people": 0, "failed": 0}
    client = NSEClient()
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT a.*, c.financial AS fin_flag, c.sector FROM announcements a JOIN companies c ON c.symbol=a.symbol "
            "WHERE a.enrichment IS NULL AND a.attachment_url LIKE '%.pdf' AND a.published_at >= ? AND ("
            " (a.category='results' AND a.sub_type IN ('outcome','press_release')) OR "
            " (a.category='management_change' AND a.sub_type IN ('kmp_join','kmp_exit','director_join','director_exit'))"
            ") ORDER BY a.priority DESC, a.published_at DESC", (since_iso,)).fetchall()
    for a in rows:
        is_res = a["category"] == "results"
        if (is_res and done["results"] >= MAX_RESULTS) or (not is_res and done["people"] >= MAX_PEOPLE):
            continue
        with db.connect() as conn:
            try:
                doc = _doc_for(conn, a)
                D.download(conn, doc["id"], client)
                conn.commit()
                doc = dict(conn.execute("SELECT * FROM documents WHERE id=?", (doc["id"],)).fetchone())
                if is_res:
                    fin = bool(a["fin_flag"]) or bool(FIN_INDUSTRY.search(a["sector"] or ""))
                    v = _results_view(conn, doc, fin)
                    enr = compact_results(v, doc) if v.get("ok") else {"type": "results", "ok": False, "reason": v.get("reason")}
                    done["results"] += 1
                else:
                    conn.commit()
                    changes = people.extract(D.pages(conn, doc["id"]))
                    enr = {"type": "people", "ok": bool(changes), "changes": changes, "url": doc["url"]}
                    done["people"] += 1
            except LLMUnavailable as e:
                log.warning("enrich: model unavailable (%s); stopping this run", e)
                break                      # rate-limited: try again next refresh
            except Exception as e:
                enr = {"type": "results" if is_res else "people", "ok": False, "reason": str(e)[:200]}
                done["failed"] += 1
            conn.execute("UPDATE announcements SET enrichment=? WHERE id=?", (json.dumps(enr), a["id"]))
    return done
