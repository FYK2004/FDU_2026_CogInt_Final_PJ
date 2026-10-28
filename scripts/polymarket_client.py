"""Minimal Polymarket data client used by the Anthropic-IPO prediction project.

Network uses system settings or the optional PJ_PROXY environment variable.
Only transient failures are retried; HTTPS certificate verification is enabled.

Public entry points
-------------------
get_event(slug)                -> raw Gamma event dict (list of events)
get_price_history(token_id)    -> list of {t, p} points from the CLOB
"""

from __future__ import annotations

import gzip
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib

PROXY = os.environ.get("PJ_PROXY")
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

_CTX = ssl.create_default_context()
_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}) if PROXY else urllib.request.ProxyHandler(),
    urllib.request.HTTPSHandler(context=_CTX),
)


def _decode(raw: bytes, encoding: str | None) -> bytes:
    enc = (encoding or "").lower()
    if enc == "gzip":
        return gzip.decompress(raw)
    if enc == "deflate":
        return zlib.decompress(raw, -zlib.MAX_WBITS)
    return raw


def get_json(url: str, retries: int = 3, timeout: int = 20):
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": UA,
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip, deflate",
                },
            )
            with _OPENER.open(req, timeout=timeout) as resp:
                return json.loads(_decode(resp.read(), resp.headers.get("Content-Encoding")))
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504):
                raise
            last = exc
            if attempt < retries:
                time.sleep(min(float(exc.headers.get("Retry-After", attempt)), 10))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
            print(f"    retry {attempt}/{retries} {url} :: {exc}", file=sys.stderr)
            if attempt < retries:
                time.sleep(min(1.0 * attempt, 6.0))
    raise RuntimeError(f"giving up on {url}: {last}")


def get_event(slug: str):
    return get_json(f"{GAMMA}/events?slug={urllib.parse.quote(slug)}")


def get_price_history(token_id: str, interval: str = "max", fidelity: int = 60):
    """interval: 1h|6h|1d|1w|1m|max ; fidelity: minutes per data point."""
    qs = urllib.parse.urlencode(
        {"market": token_id, "interval": interval, "fidelity": fidelity}
    )
    return get_json(f"{CLOB}/prices-history?{qs}")["history"]


def yes_token(market: dict) -> str:
    """Return the token id of the 'Yes' outcome of a Gamma market dict."""
    tokens = json.loads(market["clobTokenIds"])
    outcomes = json.loads(market["outcomes"])
    return tokens[outcomes.index("Yes")]


def get_history_v2(token_id, start, end, bucket_seconds=3600, raw_pages=None):
    """Explicit epoch-second window, cursor pagination, normalized legacy points."""
    if not 0 < start < end:
        raise ValueError("require 0 < start < end")
    query = dict(token_id=token_id, start=start, end=end,
                 bucket_seconds=bucket_seconds, limit=10000)
    points, cursors = {}, set()
    while True:
        payload = get_json("https://data-api.polymarket.com/v2/prices-history?" + urllib.parse.urlencode(query))
        if raw_pages is not None:
            raw_pages.append(payload)
        for point in payload["data"]:
            t, p = int(point["timestamp"]), float(point["price"])
            # API buckets may floor start; reject everything outside [start,end).
            if not 0 <= p <= 1:
                raise ValueError("Invalid history price")
            if start <= t < end:
                points[t] = p
        cursor = (payload.get("pagination") or {}).get("next_cursor")
        if not cursor:
            break
        if cursor in cursors:
            raise ValueError("Repeated history cursor")
        cursors.add(cursor)
        query["cursor"] = cursor
    return [{"t": t, "p": p} for t, p in sorted(points.items())]
