"""Command-line entry points.

  python -m finn.cli refresh            # fetch announcements + prices, classify, alert
  python -m finn.cli refresh --no-prices
  python -m finn.cli export-snapshot    # write data/snapshot.json for deployment fallback
  python -m finn.cli sources            # show source health
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
    a = p.parse_args()

    if a.cmd == "refresh":
        out = ingest.refresh(days=a.days, prices=not a.no_prices, announcements=not a.no_announcements)
    elif a.cmd == "export-snapshot":
        out = ingest.export_snapshot()
    else:
        with db.connect() as conn:
            out = db.source_status(conn)
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
