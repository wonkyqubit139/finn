"""Builds a research dossier for any NSE symbol, from primary documents only.

Steps (progress is written to the dossiers table after each one):
  find      company filings on NSE (≈15 months) → results / transcripts
  download  PDFs (cached by URL and content hash)
  results   fast model transcribes each results statement; code computes
  guidance  deep model lists management's forward-looking statements;
            code verifies every quote against the transcript text
  promises  code scores guidance against reported numbers
  synthesis deep model writes overview + bull/bear from the above, citations enforced

Every LLM output is cached (llm_cache + extractions), so rebuilding a dossier
when one new filing arrives only pays for that filing.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from datetime import date, datetime, timedelta, timezone

from .. import config, db
from ..analysis import guidance as G
from ..analysis import results as R
from ..analysis import synthesis as S
from ..analysis.periods import label as qlabel
from ..analysis.promises import evaluate
from ..llm import LLMUnavailable
from ..sources.announcements import NSEClient
from ..sources.http import SourceError
from . import documents as D

log = logging.getLogger("finn.research")

STEPS = [("find", "Find filings on NSE"), ("download", "Download documents"),
         ("results", "Read quarterly results"), ("guidance", "Extract management guidance"),
         ("promises", "Check guidance against reported numbers"), ("synthesis", "Write overview and bull/bear case")]
QUARTERS = 4
FRESH_HOURS = 12
SYMBOL_RX = re.compile(r"^[A-Z0-9&\-]{1,20}$")
FIN_INDUSTRY = re.compile(r"bank|financ|nbfc|lending|insurance|housing finance", re.I)

_sem = threading.Semaphore(1)        # one build at a time: free-tier rate limits
_lock = threading.Lock()


class BuildError(RuntimeError):
    """A failure the user should read (shown verbatim in the UI)."""


# ---- job control ----------------------------------------------------------------------

def _progress_init() -> list[dict]:
    return [{"step": k, "label": lbl, "state": "pending", "detail": None} for k, lbl in STEPS]


def _save(symbol: str, **f) -> None:
    with db.connect() as conn:
        sets = ", ".join(f"{k}=?" for k in f)
        conn.execute(f"UPDATE dossiers SET {sets} WHERE symbol=?", (*[
            json.dumps(v) if k in ("progress", "data") and not isinstance(v, str) else v for k, v in f.items()], symbol))


def status(symbol: str) -> dict | None:
    with db.connect() as conn:
        r = conn.execute("SELECT * FROM dossiers WHERE symbol=?", (symbol,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["progress"] = json.loads(d["progress"]) if d["progress"] else []
    d["data"] = json.loads(d["data"]) if d["data"] else None
    return d


def request(symbol: str, force: bool = False, run_async: bool = True) -> dict:
    symbol = (symbol or "").strip().upper()
    if not SYMBOL_RX.match(symbol):
        raise BuildError("That doesn't look like an NSE symbol (letters, digits, & or -).")
    with _lock:
        cur = status(symbol)
        if cur and cur["status"] in ("queued", "running"):
            return cur
        if cur and cur["status"] == "ready" and not force and cur["built_at"]:
            age = datetime.now(timezone.utc) - db.parse_utc(cur["built_at"])
            if age < timedelta(hours=FRESH_HOURS):
                return cur
        if config.MAX_BUILDS_PER_HOUR:
            since = db.to_utc_iso(datetime.now(timezone.utc) - timedelta(hours=1))
            with db.connect() as conn:
                n = conn.execute("SELECT COUNT(*) FROM dossiers WHERE started_at >= ?", (since,)).fetchone()[0]
            if n >= config.MAX_BUILDS_PER_HOUR:
                if cur and cur["status"] == "ready":
                    return cur          # serve the existing dossier rather than refuse
                raise BuildError(f"Research limit reached ({config.MAX_BUILDS_PER_HOUR} new builds per hour on this "
                                 "server). Try again later.")
        with db.connect() as conn:
            conn.execute("INSERT INTO dossiers(symbol, status, progress, started_at) VALUES(?, 'queued', ?, ?) "
                         "ON CONFLICT(symbol) DO UPDATE SET status='queued', progress=excluded.progress, "
                         "error=NULL, started_at=excluded.started_at",
                         (symbol, json.dumps(_progress_init()), db.utcnow()))
    if run_async:
        threading.Thread(target=_run, args=(symbol,), daemon=True).start()
    else:
        _run(symbol)
    return status(symbol)  # type: ignore[return-value]


def _run(symbol: str, client: NSEClient | None = None) -> None:
    with _sem:
        try:
            build(symbol, client)
        except BuildError as e:
            _save(symbol, status="failed", error=str(e))
        except (SourceError, LLMUnavailable) as e:
            _save(symbol, status="failed", error=f"A data source failed: {e}")
        except Exception as e:  # pragma: no cover - unexpected
            log.exception("dossier build failed")
            _save(symbol, status="failed", error=f"Unexpected error: {type(e).__name__}: {e}")


# ---- the build ------------------------------------------------------------------------

class Progress:
    def __init__(self, symbol: str):
        self.symbol, self.items = symbol, _progress_init()

    def set(self, step: str, state: str, detail: str | None = None) -> None:
        for it in self.items:
            if it["step"] == step:
                it["state"], it["detail"] = state, detail
        _save(self.symbol, status="running", step=step, progress=self.items)


def _select(found: list[D.FoundDoc]) -> tuple[dict[date, list[D.FoundDoc]], dict[date, D.FoundDoc]]:
    res: dict[date, list[D.FoundDoc]] = {}
    tr: dict[date, D.FoundDoc] = {}
    for d in found:
        if d.kind == "results":
            res.setdefault(d.period_end, []).append(d)
        elif d.kind == "transcript":
            if d.period_end not in tr or d.filed_at > tr[d.period_end].filed_at:
                tr[d.period_end] = d
    res = {p: sorted(v, key=lambda x: (x.rank, -x.filed_at.timestamp())) for p, v in
           sorted(res.items(), reverse=True)[:QUARTERS]}
    tr = dict(sorted(tr.items(), reverse=True)[:QUARTERS])
    return res, tr


def _results_view(conn, doc: dict, financial: bool) -> dict:
    cached = conn.execute("SELECT data FROM extractions WHERE doc_id=? AND task='results' AND version=?",
                          (doc["id"], R.PROMPT_VERSION)).fetchone()
    page_texts = D.pages(conn, doc["id"])
    sel, scanned = R.select_pages(page_texts)
    if cached:
        raw = json.loads(cached["data"])
    else:
        if not sel:
            return {"ok": False, "reason": "No results table found in the filing's text."}
        images = D.render_pages(doc["local_path"], sel) if scanned else None
        conn.commit()   # never hold a write lock across a model call
        raw = R.extract(page_texts, sel, images)
        conn.execute("INSERT OR REPLACE INTO extractions(doc_id, task, version, data, created_at) VALUES(?,?,?,?,?)",
                     (doc["id"], "results", R.PROMPT_VERSION, json.dumps(raw), db.utcnow()))
    return R.build_view(raw, financial, page_texts if not scanned else [], sel, doc)


def _guidance(conn, doc: dict) -> tuple[list[dict], list[dict]]:
    page_texts = D.pages(conn, doc["id"])
    cached = conn.execute("SELECT data FROM extractions WHERE doc_id=? AND task='guidance' AND version=?",
                          (doc["id"], G.PROMPT_VERSION)).fetchone()
    if cached:
        claims = json.loads(cached["data"])
    else:
        if sum(1 for t in page_texts if len(t.strip()) > 200) == 0:
            return [], []
        conn.commit()
        claims = G.extract(page_texts)
        conn.execute("INSERT OR REPLACE INTO extractions(doc_id, task, version, data, created_at) VALUES(?,?,?,?,?)",
                     (doc["id"], "guidance", G.PROMPT_VERSION, json.dumps(claims), db.utcnow()))
    return G.verify(claims, page_texts)


def build(symbol: str, client: NSEClient | None = None) -> dict:
    client = client or NSEClient()
    pg = Progress(symbol)
    t0 = db.utcnow()

    # 1. find -------------------------------------------------------------------------
    pg.set("find", "running")
    try:
        info = client.quote(symbol)
    except Exception:
        info = {}
    found = D.discover(symbol, client)
    res_by_p, tr_by_p = _select(found)
    if not res_by_p and not tr_by_p:
        raise BuildError(f"No results filings or concall transcripts found on NSE for {symbol} in the last "
                         "15 months. Check the symbol is an NSE equity.")
    with db.connect() as conn:
        D.save_found(conn, [d for v in res_by_p.values() for d in v] + list(tr_by_p.values()))
    pg.set("find", "done", f"{len(res_by_p)} quarters of results, {len(tr_by_p)} transcripts")
    if not config.LLM_FAST.enabled:
        raise BuildError("Reading filings needs a model key. Add GEMINI_API_KEY to .env and restart FINN.")

    # 2. download ----------------------------------------------------------------------
    pg.set("download", "running")
    to_get = [v[0] for v in res_by_p.values()] + list(tr_by_p.values())
    failed = 0
    with db.connect() as conn:
        for d in to_get:
            try:
                D.download(conn, d.id, client)
            except Exception as e:
                failed += 1
                log.warning("download failed %s: %s", d.url, e)
            conn.commit()
    pg.set("download", "done", f"{len(to_get) - failed} of {len(to_get)} documents" + (f", {failed} failed" if failed else ""))

    # 3. results -----------------------------------------------------------------------
    financial = bool(FIN_INDUSTRY.search(info.get("industry") or ""))
    views: list[dict] = []
    used_docs: dict[str, dict] = {}
    with db.connect() as conn:
        for i, (period, cands) in enumerate(res_by_p.items(), 1):
            pg.set("results", "running", f"{qlabel(period)} ({i} of {len(res_by_p)})")
            for cand in cands[:3]:   # fall back to another filing for the same quarter if one can't be read
                row = conn.execute("SELECT * FROM documents WHERE id=?", (cand.id,)).fetchone()
                if row["status"] != "downloaded":
                    try:
                        D.download(conn, cand.id, client)
                        row = conn.execute("SELECT * FROM documents WHERE id=?", (cand.id,)).fetchone()
                    except Exception:
                        continue
                try:
                    v = _results_view(conn, dict(row), financial)
                except LLMUnavailable as e:
                    v = {"ok": False, "reason": f"model error: {e}"}
                conn.commit()
                if v.get("ok"):
                    views.append(v)
                    used_docs[row["id"]] = dict(row)
                    break
    if not views:
        raise BuildError("Couldn't read any results statement from the filings found (they may be scanned "
                         "images the model couldn't read, or the model is rate-limited). Try again shortly.")
    pg.set("results", "done", f"{len(views)} quarters read")

    # 4. guidance -----------------------------------------------------------------------
    claims_by_doc: list[tuple[dict, date, list[dict]]] = []
    dropped_total = 0
    with db.connect() as conn:
        for i, (period, d) in enumerate(tr_by_p.items(), 1):
            pg.set("guidance", "running", f"{qlabel(period)} call ({i} of {len(tr_by_p)})")
            row = dict(conn.execute("SELECT * FROM documents WHERE id=?", (d.id,)).fetchone())
            if row["status"] != "downloaded":
                continue
            try:
                ok, dropped = _guidance(conn, row) if config.LLM_DEEP.enabled else ([], [])
            except LLMUnavailable as e:
                log.warning("guidance failed: %s", e)
                ok, dropped = [], []
            conn.commit()
            dropped_total += len(dropped)
            used_docs[row["id"]] = row
            claims_by_doc.append((row, period, ok))
    pg.set("guidance", "done", f"{sum(len(c) for _, _, c in claims_by_doc)} statements, "
                               f"{dropped_total} discarded (quote not found in transcript)")

    # document references D1, D2… (results newest first, then transcripts)
    ordered = sorted(used_docs.values(), key=lambda r: (r["kind"] != "results", r["period_end"] or ""), reverse=False)
    ordered = sorted([r for r in ordered if r["kind"] == "results"], key=lambda r: r["period_end"], reverse=True) + \
        sorted([r for r in ordered if r["kind"] != "results"], key=lambda r: r["period_end"], reverse=True)
    ref = {r["id"]: f"D{i}" for i, r in enumerate(ordered, 1)}

    # 5. numbers + promises ---------------------------------------------------------------
    pg.set("promises", "running")
    fin = assemble_financials(views, ref)
    series, latest = fin["series"], date.fromisoformat(fin["latest_period"])
    promises: list[dict] = []
    n = 0
    for row, said_in, claims in sorted(claims_by_doc, key=lambda x: x[1], reverse=True):
        for c in claims:
            n += 1
            ev = evaluate(c, said_in, series, latest)
            promises.append({"id": f"C{n}", "quote": c["quote"], "speaker": c.get("speaker"), "topic": c.get("topic"),
                             "metric": c.get("metric"), "specificity": c.get("specificity"),
                             "ref": ref[row["id"]], "page": c["page"], "said_in": qlabel(said_in),
                             "said_in_date": said_in.isoformat(), "url": row["url"], **ev})
    promises = merge_repeats(promises)
    counts: dict[str, int] = {}
    for p in promises:
        counts[p["status"]] = counts.get(p["status"], 0) + 1
    pg.set("promises", "done", ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in counts.items()) or "no guidance found")

    # 6. synthesis ----------------------------------------------------------------------
    pg.set("synthesis", "running")
    syn: dict = {"overview": [], "bull": [], "bear": [], "claim_assessments": [], "narrative_gap": None}
    syn_note = None
    if config.LLM_DEEP.enabled:
        valid = {f"{ref[r['id']]}:p{p}" for r in ordered for p in range(1, (r["pages"] or 0) + 1)}
        qual = [p for p in promises if p["status"] == "unverifiable"][:8]
        excerpts = []
        with db.connect() as conn:
            tr_rows = [r for r in ordered if r["kind"] == "transcript"]
            if tr_rows:
                pts = D.pages(conn, tr_rows[0]["id"])
                excerpts = [(ref[tr_rows[0]["id"]], i, t) for i, t in enumerate(pts[:4], 1) if len(t.strip()) > 200][:3]
        try:
            syn = S.synthesize(info.get("name") or symbol, fin["table"], [p for p in promises if p["status"] != "unverifiable"],
                               qual, excerpts, valid)
        except LLMUnavailable as e:
            syn_note = f"Synthesis skipped: {e}"
        for a in syn.get("claim_assessments", []):
            for p in promises:
                if p["id"] == a["id"]:
                    p.update({"model_verdict": a["verdict"], "model_reason": a["reason"], "model_cite": a["cite"]})
    pg.set("synthesis", "done" if not syn_note else "skipped", syn_note)

    with db.connect() as conn:
        usage = conn.execute("SELECT COUNT(*) calls, COALESCE(SUM(cached),0) cached, COALESCE(SUM(prompt_tokens),0) tin, "
                             "COALESCE(SUM(completion_tokens),0) tout FROM llm_calls WHERE created_at >= ?", (t0,)).fetchone()
    dossier = {
        "symbol": symbol, "name": info.get("name") or symbol, "industry": info.get("industry"),
        "built_at": db.utcnow(), "latest_period": fin["latest_period"], "latest_label": fin["latest_label"],
        "documents": [{"ref": ref[r["id"]], "id": r["id"], "kind": r["kind"], "period": r["period_end"],
                       "period_label": qlabel(date.fromisoformat(r["period_end"])) if r["period_end"] else None,
                       "title": r["title"], "url": r["url"], "pages": r["pages"], "filed_at": r["filed_at"]}
                      for r in ordered],
        "financials": {k: v for k, v in fin.items() if k != "series"},
        "promises": promises, "dropped_claims": dropped_total,
        "overview": syn.get("overview", []), "bull": syn.get("bull", []), "bear": syn.get("bear", []),
        "narrative_gap": syn.get("narrative_gap"), "uncited_dropped": syn.get("uncited_dropped", 0),
        "coverage": {"results_quarters": [qlabel(p) for p in res_by_p], "transcript_quarters": [qlabel(p) for p in tr_by_p]},
        "usage": dict(usage),
    }
    fp = hashlib.sha1(",".join(sorted(used_docs)).encode()).hexdigest()[:16]
    _save(symbol, status="ready", step=None, data=dossier, built_at=db.utcnow(), doc_fingerprint=fp, error=None)
    return dossier


def assemble_financials(views: list[dict], ref: dict[str, str]) -> dict:
    """Merge quarters across filings. A quarter's figures come from the filing
    where it is the *current* quarter; older filings' comparison columns only
    fill gaps (e.g. year-ago quarters needed for YoY)."""
    views = sorted(views, key=lambda v: v["period_end"])
    series: dict[str, dict] = {}
    src: dict[str, dict] = {}
    for v in views:
        for q, m in v["quarters"].items():
            if q == v["period_end"] or q not in series:
                series[q] = m
                src[q] = {"ref": ref.get(v["source"]["doc_id"]), "page": v["source"]["page"], "url": v["source"]["url"],
                          "as": "reported" if q == v["period_end"] else "comparative column"}
    latest = views[-1]
    reported = {v["period_end"] for v in views}
    table = []
    for q in sorted(series, reverse=True):
        if q not in reported:
            continue     # comparatives feed YoY, but the table shows quarters the filings report on
        m = series[q]
        ya = series.get((date.fromisoformat(q).replace(year=date.fromisoformat(q).year - 1)).isoformat())
        table.append({"period_end": q, "label": qlabel(date.fromisoformat(q)), "revenue": m["revenue"],
                      "ebitda": m["ebitda"], "ebitda_margin": m["ebitda_margin"], "pbt": m["pbt"], "pat": m["pat"],
                      "pat_margin": m["pat_margin"],
                      "revenue_yoy": R._pct(m["revenue"], ya["revenue"]) if ya else None,
                      "pat_yoy": R._pct(m["pat"], ya["pat"]) if ya else None,
                      "source": src[q]})
    annual_v = next((v for v in reversed(views) if v.get("annual")), None)
    return {
        "series": series, "table": table, "latest_period": latest["period_end"], "latest_label": latest["period_label"],
        "latest": {k: latest[k] for k in ("current", "previous", "year_ago", "qoq", "yoy", "previous_period",
                                          "year_ago_period", "basis", "format", "financial", "unit_reported",
                                          "unit_note", "checks")} | {"source": {**latest["source"],
                                                                                "ref": ref.get(latest["source"]["doc_id"])}},
        "annual": annual_v["annual"] if annual_v else [],
        "annual_source": {"ref": ref.get(annual_v["source"]["doc_id"]), "page": annual_v["source"]["page"]} if annual_v else None,
        "reconciliation": R.reconcile(views),
        "checks_failed": sum(1 for v in views for c in v["checks"] if not c["ok"]),
    }


def merge_repeats(promises: list[dict]) -> list[dict]:
    """Management repeats guidance call after call. Collapse statements with the
    same metric, target and period into one row (newest quote first) and keep
    the other calls as 'also said on'. Repetition itself is informative: it
    shows guidance was maintained rather than quietly changed."""
    out: list[dict] = []
    index: dict[tuple, dict] = {}
    for p in sorted(promises, key=lambda x: x["said_in_date"], reverse=True):
        key = (p.get("metric"), p.get("target_text"), p.get("period_label"),
               (p.get("topic") or "").lower() if p.get("metric") == "other" else "")
        if key in index:
            index[key].setdefault("also_said", []).append({"said_in": p["said_in"], "ref": p["ref"], "page": p["page"]})
        else:
            index[key] = p
            out.append(p)
    return out
