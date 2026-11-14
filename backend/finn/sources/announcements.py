"""Corporate announcements from NSE (primary) and BSE (fallback).

Both exchanges expose the same JSON their own websites use. Neither is a
documented public API, so the parsers are deliberately tolerant: unknown or
missing fields degrade to None rather than crashing the whole refresh.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .. import config
from .http import SourceError, get_with_retry, new_session

NSE_HOME = "https://www.nseindia.com/"
NSE_REFERER = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
NSE_API = "https://www.nseindia.com/api/corporate-announcements"

BSE_API = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
BSE_ATTACH = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/"
BSE_HEADERS = {"Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com"}


@dataclass
class RawAnnouncement:
    id: str                 # '<source>:<exchange id>'
    symbol: str
    source: str
    published_at: datetime  # tz-aware
    subject: str
    body: str
    attachment_url: str | None


def _clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _parse_ist(value: str | None, formats: tuple[str, ...]) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=config.IST)
        except ValueError:
            continue
    return None


# ---- NSE -------------------------------------------------------------------

NSE_TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M")


def parse_nse(items: list[dict], symbol: str) -> list[RawAnnouncement]:
    out: list[RawAnnouncement] = []
    for it in items or []:
        ts = _parse_ist(it.get("sort_date"), NSE_TIME_FORMATS) or \
             _parse_ist(it.get("an_dt"), NSE_TIME_FORMATS)
        if ts is None:
            continue
        ex_id = it.get("seq_id") or it.get("an_id")
        if not ex_id:  # stable fallback id (built-in hash() is randomised per process)
            digest = hashlib.sha1(f"{it.get('desc')}|{it.get('attchmntFile')}".encode()).hexdigest()[:10]
            ex_id = f"{symbol}-{ts:%Y%m%d%H%M%S}-{digest}"
        att = it.get("attchmntFile") or None
        if att in ("-", ""):
            att = None
        out.append(RawAnnouncement(
            id=f"nse:{ex_id}",
            symbol=(it.get("symbol") or symbol).upper(),
            source="nse",
            published_at=ts,
            subject=_clean(it.get("desc")) or "Announcement",
            body=_clean(it.get("attchmntText")),
            attachment_url=att,
        ))
    return out


class NSEClient:
    def __init__(self):
        self.s = new_session()
        self._warm = False

    def warm(self):
        # NSE sets the cookies its API checks only after a normal page visit.
        get_with_retry(self.s, NSE_HOME, headers={"Accept": "text/html"}, tries=2)
        get_with_retry(self.s, NSE_REFERER, headers={"Accept": "text/html"}, tries=2)
        self._warm = True

    def announcements(self, symbol: str, start: date, end: date) -> list[RawAnnouncement]:
        if not self._warm:
            self.warm()
        params = {"index": "equities", "symbol": symbol,
                  "from_date": start.strftime("%d-%m-%Y"), "to_date": end.strftime("%d-%m-%Y")}
        try:
            r = get_with_retry(self.s, NSE_API, params=params, headers={"Referer": NSE_REFERER})
        except SourceError:
            self.warm()   # cookie may have expired mid-run; retry once
            r = get_with_retry(self.s, NSE_API, params=params, headers={"Referer": NSE_REFERER})
        try:
            data = r.json()
        except Exception as e:
            raise SourceError(f"NSE returned non-JSON ({e})")
        if isinstance(data, dict):  # some variants wrap the list
            data = data.get("data") or []
        return parse_nse(data, symbol)


# ---- BSE -------------------------------------------------------------------

BSE_TIME_FORMATS = ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M:%S")


def parse_bse(rows: list[dict], symbol: str) -> list[RawAnnouncement]:
    out: list[RawAnnouncement] = []
    for it in rows or []:
        ts = _parse_ist(it.get("DT_TM"), BSE_TIME_FORMATS) or \
             _parse_ist(it.get("NEWS_DT"), BSE_TIME_FORMATS)
        if ts is None or not it.get("NEWSID"):
            continue
        att = it.get("ATTACHMENTNAME")
        subject = _clean(it.get("SUBCATNAME")) or _clean(it.get("CATEGORYNAME"))
        headline = _clean(it.get("HEADLINE")) or _clean(it.get("NEWSSUB"))
        if subject in ("", "-"):
            subject = headline[:120] or "Announcement"
        out.append(RawAnnouncement(
            id=f"bse:{it['NEWSID']}",
            symbol=symbol.upper(),
            source="bse",
            published_at=ts,
            subject=subject,
            body=headline,
            attachment_url=(BSE_ATTACH + att) if att else None,
        ))
    return out


class BSEClient:
    def __init__(self):
        self.s = new_session()

    def announcements(self, symbol: str, scrip_code: str, start: date, end: date) -> list[RawAnnouncement]:
        rows: list[dict] = []
        for page in range(1, 6):  # 5 × 50 rows is plenty for a 10-day window
            params = {"pageno": page, "strCat": "-1", "strPrevDate": start.strftime("%Y%m%d"),
                      "strScrip": scrip_code, "strSearch": "P", "strToDate": end.strftime("%Y%m%d"),
                      "strType": "C", "subcategory": "-1"}
            r = get_with_retry(self.s, BSE_API, params=params, headers=BSE_HEADERS)
            try:
                data = r.json()
            except Exception as e:
                raise SourceError(f"BSE returned non-JSON ({e})")
            batch = data.get("Table") or []
            rows.extend(batch)
            total = (data.get("Table1") or [{}])[0].get("ROWCNT") or 0
            if not batch or len(rows) >= total:
                break
        return parse_bse(rows, symbol)


def window(days: int) -> tuple[date, date]:
    today = datetime.now(config.IST).date()
    return today - timedelta(days=days), today
