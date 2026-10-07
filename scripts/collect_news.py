"""Harvest Anthropic-IPO news headlines from Google News RSS into a tidy CSV.

Writes data/raw/news_<query>.xml and data/processed/news_index.csv
"""

from __future__ import annotations

import csv
import datetime as dt
import email.utils
import gzip
import os
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import polymarket_client as pc  # noqa: E402  (re-used proxy opener + retry logic)

RAW = "data/raw"
PROC = "data/processed"

QUERIES = {
    "anthropic_ipo": "Anthropic IPO",
    "anthropic_ipo_nov": "Anthropic IPO November 2026",
    "anthropic_s1": "Anthropic S-1 prospectus",
    "anthropic_valuation": "Anthropic valuation IPO",
}


def fetch_rss(query: str) -> bytes:
    url = (
        "https://news.google.com/rss/search?q="
        + urllib.parse.quote(query)
        + "&hl=en-US&gl=US&ceid=US:en"
    )
    for attempt in range(1, 6):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": pc.UA, "Accept-Encoding": "gzip, deflate"}
            )
            with pc._OPENER.open(req, timeout=30) as resp:
                raw = resp.read()
                enc = (resp.headers.get("Content-Encoding") or "").lower()
                if enc == "gzip":
                    raw = gzip.decompress(raw)
                elif enc == "deflate":
                    raw = zlib.decompress(raw, -zlib.MAX_WBITS)
                return raw
        except Exception as exc:  # noqa: BLE001
            print(f"  retry {attempt}/5 {exc}", file=sys.stderr)
            time.sleep(attempt * 0.8)
    raise RuntimeError(f"rss failed: {query}")


def parse(xml_bytes: bytes) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    out = []
    for item in root.findall(".//item"):
        title = item.findtext("title") or ""
        publisher = ""
        if " - " in title:
            title, publisher = title.rsplit(" - ", 1)
        published = item.findtext("pubDate") or ""
        try:
            when = email.utils.parsedate_to_datetime(published)
        except (TypeError, ValueError):
            when = None
        out.append(
            {
                "title": title.strip(),
                "publisher": publisher.strip(),
                "published_utc": when.astimezone(dt.timezone.utc).isoformat() if when else "",
                "published_date": when.astimezone(dt.timezone.utc).date().isoformat() if when else "",
                "link": item.findtext("link") or "",
            }
        )
    return out


def main() -> None:
    os.makedirs(PROC, exist_ok=True)
    seen: dict[str, dict] = {}
    for name, query in QUERIES.items():
        body = fetch_rss(query)
        path = os.path.join(RAW, f"news_{name}.xml")
        with open(path, "wb") as fh:
            fh.write(body)
        items = parse(body)
        print(f"{name}: {len(items)} items -> {path}")
        for it in items:
            it["query"] = name
            seen.setdefault(it["title"].lower(), it)

    rows = sorted(seen.values(), key=lambda r: r["published_utc"], reverse=True)
    out = os.path.join(PROC, "news_index.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out} ({len(rows)} unique headlines)")


if __name__ == "__main__":
    main()
