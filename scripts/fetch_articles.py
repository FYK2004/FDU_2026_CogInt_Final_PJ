"""Resolve Google-News links and store article text for the evidence log.

Writes one .txt per article into data/raw/articles/ plus an index CSV.
Only used to build the human-readable evidence appendix of the report.
"""

from __future__ import annotations

import csv
import html
import os
import re
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import polymarket_client as pc  # noqa: E402

from project_config import RAW, PROC, AS_OF, cutoff_utc
ART = os.path.join(RAW, "articles")

# (news_index title substring, short filename)
TARGETS = [
    ("Anthropic Shifts Planned IPO to November", "wsj_shift_nov"),
    ("Anthropic Moves Ahead With I.P.O. Plans", "nyt_moves_ahead"),
    ("IPO Delay: Prediction Markets See More Uncertainty", "time_prediction_markets"),
    ("looking to IPO as early as mid-November", "yahoo_mid_november"),
    ("Anthropic Targets Mega-IPO Before Thanksgiving", "bloomberg_thanksgiving"),
    ("expected to IPO despite market uncertainty", "cnn_despite_uncertainty"),
    ("Kalshi traders see high odds", "cnbc_kalshi"),
    ("Anthropic Pushes Its IPO to November", "yahoo_pushes_nov"),
    ("IPO market outlook: window open but selective", "investing_ipo_window"),
    ("Here's the Chip Stock to Buy Before It Lists", "mf_chip_stock"),
    ("Anthropic IPO launch shifts toward mid-October", "reuters_mid_october"),
    ("IPO prospectus shows sweeping AI vision", "reuters_prospectus"),
    ("Anthropic IPO Delay", "generic_delay"),
    ("Key drivers of Anthropic", "generic_drivers"),
]

TAG_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.S | re.I)
BLOCK_RE = re.compile(r"</?(p|div|br|li|h[1-6]|tr)[^>]*>", re.I)


def strip_html(doc: str) -> str:
    doc = TAG_RE.sub(" ", doc)
    doc = BLOCK_RE.sub("\n", doc)
    doc = re.sub(r"<[^>]+>", " ", doc)
    doc = html.unescape(doc)
    doc = re.sub(r"[ \t\xa0]+", " ", doc)
    doc = re.sub(r"\n\s*\n\s*\n+", "\n\n", doc)
    return doc.strip()


def resolve(link: str) -> str:
    req = urllib.request.Request(link, headers={"User-Agent": pc.UA})
    with pc._OPENER.open(req, timeout=30) as resp:
        final = resp.geturl()
        if "news.google.com" in final:
            body = resp.read().decode("utf-8", "ignore")
            m = re.search(r'data-n-au="([^"]+)"', body) or re.search(
                r'<a[^>]+href="(https?://(?!news\.google)[^"]+)"', body
            )
            if m:
                return html.unescape(m.group(1))
        return final


def load_index() -> list[dict]:
    import datetime as dt
    with (PROC / "news_index.csv").open(encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if r["published_utc"] and
                dt.datetime.fromisoformat(r["published_utc"]) < cutoff_utc()]


def main() -> None:
    os.makedirs(ART, exist_ok=True)
    rows = load_index()
    manifest = []
    for needle, name in TARGETS:
        hit = next((r for r in rows if needle.lower() in r["title"].lower()), None)
        if not hit:
            print(f"  no match for {needle!r}")
            continue
        try:
            url = resolve(hit["link"])
            req = urllib.request.Request(url, headers={"User-Agent": pc.UA})
            with pc._OPENER.open(req, timeout=35) as resp:
                doc = resp.read().decode("utf-8", "ignore")
            text = strip_html(doc)
            path = os.path.join(ART, f"{name}.txt")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(f"TITLE: {hit['title']}\nPUBLISHER: {hit['publisher']}\n")
                fh.write(f"DATE: {hit['published_date']}\nURL: {url}\n\n{text}\n")
            manifest.append(
                {
                    "name": name,
                    "title": hit["title"],
                    "publisher": hit["publisher"],
                    "date": hit["published_date"],
                    "url": url,
                    "chars": len(text),
                }
            )
            print(f"  OK {name:28s} {len(text):7d} chars  <- {hit['publisher']}")
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL {name:28s} {type(exc).__name__}: {exc}")
        time.sleep(0.8)

    if manifest:
        out = os.path.join(RAW, "articles", "_manifest.csv")
        with open(out, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(manifest[0].keys()))
            w.writeheader()
            w.writerows(manifest)
        print(f"wrote {out} ({len(manifest)} articles)")


if __name__ == "__main__":
    main()
