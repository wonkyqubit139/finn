"""Loads the mock portfolio from data/portfolio.json into the companies table."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from . import config


@dataclass(frozen=True)
class Holding:
    symbol: str
    name: str
    sector: str
    bse_code: str | None
    financial: bool


def load_holdings() -> list[Holding]:
    data = json.loads(config.PORTFOLIO_PATH.read_text())
    return [Holding(h["symbol"], h["name"], h.get("sector", ""), h.get("bse_code"),
                    bool(h.get("financial"))) for h in data["portfolio"]]


def sync_companies(conn: sqlite3.Connection) -> list[Holding]:
    holdings = load_holdings()
    conn.execute("UPDATE companies SET in_portfolio=0")
    for h in holdings:
        conn.execute(
            "INSERT INTO companies(symbol, name, sector, bse_code, financial, in_portfolio) "
            "VALUES(?,?,?,?,?,1) ON CONFLICT(symbol) DO UPDATE SET name=excluded.name, "
            "sector=excluded.sector, bse_code=excluded.bse_code, "
            "financial=excluded.financial, in_portfolio=1",
            (h.symbol, h.name, h.sector, h.bse_code, int(h.financial)),
        )
    return holdings
