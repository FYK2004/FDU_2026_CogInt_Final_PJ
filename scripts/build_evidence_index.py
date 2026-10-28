"""Merge retained headlines with reviewed dated evidence, offline and as-of safe."""
import csv
import datetime as dt
import json
from project_config import ROOT, PROC, AS_OF, cutoff_utc


def main():
    archive = ROOT / "data/archive/2026-10-07/processed/news_index.csv"
    with archive.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for path in sorted((ROOT/"data/updates").glob("*.json")):
        update = json.loads(path.read_text(encoding="utf-8"))
        if dt.date.fromisoformat(update["as_of"]) > AS_OF:
            continue
        for source in update["sources"]:
            if not source.get("used_for_forecast"):
                continue
            rows.append(dict(title=source["title"], publisher=source["publisher"],
                             published_utc=source["published_utc"], published_date=source["published_utc"][:10],
                             link=source["url"], query="reviewed_20261014"))
    seen = {}
    for row in rows:
        if row["published_utc"] and dt.datetime.fromisoformat(row["published_utc"]) < cutoff_utc():
            seen.setdefault(row["link"], row)
    rows = sorted(seen.values(), key=lambda r:r["published_utc"], reverse=True)
    with (PROC/"news_index.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh,fieldnames=["title","publisher","published_utc","published_date","link","query"])
        w.writeheader()
        w.writerows(rows)
    print(f"Indexed {len(rows)} headlines through {AS_OF}")


if __name__ == "__main__":
    main()
