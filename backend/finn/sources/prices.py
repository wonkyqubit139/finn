"""End-of-day price & volume from Yahoo Finance (via yfinance).

NSE tickers are '<SYMBOL>.NS'; if a symbol returns nothing we retry on BSE
('.BO'). Only completed daily bars are kept.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .http import SourceError


@dataclass
class Bar:
    symbol: str
    date: str
    open: float | None
    high: float | None
    low: float | None
    close: float
    volume: int | None


def _num(x):
    try:
        f = float(x)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def frame_to_bars(df, symbol: str) -> list[Bar]:
    """Convert one ticker's OHLCV DataFrame (DatetimeIndex) into Bars."""
    bars: list[Bar] = []
    if df is None or len(df) == 0:
        return bars
    for idx, row in df.iterrows():
        close = _num(row.get("Close"))
        if close is None:
            continue
        vol = _num(row.get("Volume"))
        bars.append(Bar(symbol=symbol, date=idx.strftime("%Y-%m-%d"),
                        open=_num(row.get("Open")), high=_num(row.get("High")),
                        low=_num(row.get("Low")), close=close,
                        volume=int(vol) if vol is not None else None))
    return bars


def fetch_eod(symbols: list[str], period: str = "6mo") -> tuple[dict[str, list[Bar]], dict[str, str]]:
    """Returns (bars by symbol, errors by symbol)."""
    try:
        import yfinance as yf
    except ImportError as e:  # pragma: no cover
        raise SourceError(f"yfinance not installed: {e}")

    out: dict[str, list[Bar]] = {}
    errors: dict[str, str] = {}
    tickers = [f"{s}.NS" for s in symbols]
    try:
        df = yf.download(tickers, period=period, interval="1d", group_by="ticker",
                         auto_adjust=False, progress=False, threads=True)
    except Exception as e:
        raise SourceError(f"Yahoo download failed: {e}")

    first_pass: dict[str, list[Bar]] = {}
    for s, t in zip(symbols, tickers):
        try:
            sub = df[t] if len(tickers) > 1 else df
            if hasattr(sub.columns, "nlevels") and sub.columns.nlevels > 1:
                sub = sub.droplevel(0, axis=1)
            first_pass[s] = frame_to_bars(sub.dropna(how="all"), s)
        except Exception:
            first_pass[s] = []
    if not any(first_pass.values()):
        # Nothing at all came back: Yahoo is unreachable/blocking. Don't retry 18× on .BO.
        raise SourceError("Yahoo returned no data for any symbol (network blocked or rate-limited)")

    for s in symbols:
        bars = first_pass[s]
        if not bars:  # this one symbol is missing on .NS — retry on BSE listing
            try:
                alt = yf.download(f"{s}.BO", period=period, interval="1d",
                                  auto_adjust=False, progress=False)
                if hasattr(alt.columns, "nlevels") and alt.columns.nlevels > 1:
                    alt = alt.droplevel(1, axis=1)
                bars = frame_to_bars(alt.dropna(how="all"), s)
            except Exception as e:
                errors[s] = str(e)
        if bars:
            out[s] = bars
        else:
            errors.setdefault(s, "no data from Yahoo (.NS or .BO)")
    return out, errors
