"""Fetch a URL through the local proxy and save the body.

Usage:
    python scripts/fetch_url.py <url> <outfile> [--proxy http://127.0.0.1:7897]

Used by the Anthropic-IPO prediction project to collect raw evidence
(Polymarket market data, news pages) into data/raw/.
"""

from __future__ import annotations

import argparse
import gzip
import io
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
import zlib

DEFAULT_PROXY = os.environ.get("PJ_PROXY")
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def build_opener(proxy: str | None) -> urllib.request.OpenerDirector:
    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    ctx = ssl.create_default_context()
    handlers.append(urllib.request.HTTPSHandler(context=ctx))
    return urllib.request.build_opener(*handlers)


def decode(raw: bytes, encoding: str | None) -> bytes:
    enc = (encoding or "").lower()
    if enc == "gzip":
        return gzip.decompress(raw)
    if enc == "deflate":
        return zlib.decompress(raw, -zlib.MAX_WBITS)
    return raw


def fetch(url: str, proxy: str | None, retries: int = 4, timeout: int = 30) -> bytes:
    opener = build_opener(proxy)
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": UA,
                    "Accept": "*/*",
                    "Accept-Encoding": "gzip, deflate",
                },
            )
            with opener.open(req, timeout=timeout) as resp:
                return decode(resp.read(), resp.headers.get("Content-Encoding"))
        except (urllib.error.URLError, ssl.SSLError, TimeoutError, OSError) as exc:
            last_err = exc
            sys.stderr.write(f"  attempt {attempt}/{retries} failed: {exc}\n")
            time.sleep(1.5 * attempt)
    raise SystemExit(f"FAILED after {retries} attempts: {url}\n  last error: {last_err}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("outfile")
    ap.add_argument("--proxy", default=DEFAULT_PROXY)
    ap.add_argument("--no-proxy", action="store_true")
    args = ap.parse_args()

    proxy = None if args.no_proxy else args.proxy
    body = fetch(args.url, proxy)
    with open(args.outfile, "wb") as fh:
        fh.write(body)
    print(f"OK {len(body)} bytes -> {args.outfile}")


if __name__ == "__main__":
    main()
