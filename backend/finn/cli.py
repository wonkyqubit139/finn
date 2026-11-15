"""Command-line entry points.

  python -m finn.cli refresh            # fetch announcements + prices, classify, alert
  python -m finn.cli refresh --no-prices
  python -m finn.cli export-snapshot    # write data/snapshot.json for deployment fallback
  python -m finn.cli sources            # show source health
  python -m finn.cli research DIXON     # build a research dossier and print a summary
"""
from __future__ import annotations

import argparse
import json

from . import db
from .pipeline import ingest


def main():
    p = argparse.ArgumentParser(prog="finn")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("refresh")
    r.add_argument("--days", type=int, default=None)
    r.add_argument("--no-prices", action="store_true")
    r.add_argument("--no-announcements", action="store_true")
    sub.add_parser("export-snapshot")
    sub.add_parser("sources")
    rs = sub.add_parser("research", help="build a dossier now and print a summary")
    rs.add_argument("symbol")
    rs.add_argument("--force", action="store_true")
    a = p.parse_args()

    if a.cmd == "refresh":
        out = ingest.refresh(days=a.days, prices=not a.no_prices, announcements=not a.no_announcements)
    elif a.cmd == "research":
        from .research import build as B
        st = B.request(a.symbol, force=a.force, run_async=False)
        d = st.get("data") or {}
        fin = d.get("financials") or {}
        out = {"status": st["status"], "error": st.get("error"),
               "progress": [f"{p['label']}: {p['state']}" + (f" ({p['detail']})" if p.get("detail") else "")
                            for p in st.get("progress", [])]}
        if d:
            out["latest"] = d.get("latest_label")
            out["quarters"] = [{k: (round(v, 1) if isinstance(v, float) else v) for k, v in r.items() if k != "source"}
                               for r in fin.get("table", [])]
            out["checks_failed"] = fin.get("checks_failed")
            out["ebitda_note"] = (fin.get("latest") or {}).get("current", {}).get("ebitda_note")
            out["promises"] = [f"[{p['status']}] {p.get('topic')}: {p['target_text']} for {p['period_label']}"
                               + (f" → {p['actual_text']}" if p.get("actual_text") else "") for p in d.get("promises", [])]
            out["dropped_quotes"] = d.get("dropped_claims")
            out["bull_bear"] = (len(d.get("bull", [])), len(d.get("bear", [])))
            out["model_usage"] = d.get("usage")
    elif a.cmd == "export-snapshot":
        out = ingest.export_snapshot()
    else:
        with db.connect() as conn:
            out = db.source_status(conn)
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
