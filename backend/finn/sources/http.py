"""Shared HTTP session.

NSE and BSE sit behind bot protection (Akamai) that rejects many plain Python
HTTP clients based on their TLS fingerprint. curl_cffi impersonates a real
Chrome TLS handshake, which is the single biggest factor in getting a 200 back.
"""
from __future__ import annotations

import time

from curl_cffi import requests as creq

BROWSER_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-IN,en;q=0.9",
}


class SourceError(RuntimeError):
    """Raised when an external source can't be reached or returns junk."""


def new_session() -> creq.Session:
    s = creq.Session(impersonate="chrome", timeout=20)
    s.headers.update(BROWSER_HEADERS)
    return s


def get_with_retry(session: creq.Session, url: str, *, params=None, headers=None,
                   tries: int = 3, backoff: float = 1.5):
    last: Exception | None = None
    for attempt in range(tries):
        try:
            r = session.get(url, params=params, headers=headers)
            if r.status_code == 200:
                return r
            # 401/403 from NSE usually means the cookie expired — caller re-warms.
            last = SourceError(f"HTTP {r.status_code} from {url}")
            if r.status_code in (401, 403, 404):
                break
        except Exception as e:  # network errors, TLS errors, timeouts
            last = SourceError(f"{type(e).__name__}: {e}")
        time.sleep(backoff * (attempt + 1))
    raise last or SourceError(f"failed: {url}")
