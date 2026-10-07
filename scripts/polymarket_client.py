"""Minimal Polymarket data client used by the Anthropic-IPO prediction project.

Network access goes through the local HTTP proxy configured in PROXY.
Every call is retried because the proxy is flaky for gamma-api.polymarket.com.

Public entry points
-------------------
get_event(slug)                -> raw Gamma event dict (list of events)
get_price_history(token_id)    -> list of {t, p} points from the CLOB
"""

from __future__ import annotations

import gzip
import json
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib

PROXY = "http://127.0.0.1:7897"
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE
_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}),
    urllib.request.HTTPSHandler(context=_CTX),
)


def _decode(raw: bytes, encoding: str | None) -> bytes:
    enc = (encoding or "").lower()
    if enc == "gzip":
        return gzip.decompress(raw)
    if enc == "deflate":
        return zlib.decompress(raw, -zlib.MAX_WBITS)
    return raw


def get_json(url: str, retries: int = 8, timeout: int = 40):
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
        except Exception as exc:  # noqa: BLE001 - proxy flakiness is expected
            last = exc
            print(f"    retry {attempt}/{retries} {url} :: {exc}", file=sys.stderr)
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
