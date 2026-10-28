"""Backfill one historical ET information day, without current-book leakage.

python scripts/backfill_market.py --as-of 2026-10-14
Uses existing token metadata; saves separate raw responses and quote timestamps.
"""
import argparse
import csv
import datetime as dt
import json
from pathlib import Path
from polymarket_client import get_history_v2
from project_config import ROOT, RAW, PROC, cutoff_utc


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--as-of", type=dt.date.fromisoformat, required=True)
    args = ap.parse_args()
    source = ROOT / "data/archive/2026-10-07/processed/anthopic_term_structure.csv"
    with source.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    end = int(cutoff_utc(args.as_of).timestamp())
    start = end - 8*86400
    folder = RAW / "backfill" / args.as_of.isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    new_rows = []
    for old in rows:
        row = dict(old)
        row["metadata_as_of"] = "2026-10-07"
        if old["closed"] == "True":
            row.update(quote_utc="2026-10-07T09:12:36+00:00", quote_source="resolved_snapshot")
        else:
            pages = []
            history = get_history_v2(old["yes_token_id"], start, end, raw_pages=pages)
            responses = folder / "responses"
            responses.mkdir(exist_ok=True)
            (responses / f"{old['slug']}.json").write_text(json.dumps(pages), encoding="utf-8")
            if not history or end-history[-1]["t"] > 6*3600:
                raise ValueError(f"No recent historical quote: {old['slug']}")
            (folder / f"{old['slug']}.json").write_text(json.dumps(history), encoding="utf-8")
            row["yes_price"] = history[-1]["p"]
            row["quote_utc"] = dt.datetime.fromtimestamp(history[-1]["t"], dt.timezone.utc).isoformat()
            row["quote_source"] = "data_api_v2_hourly_history"
            # No historical bid/ask/volume/liquidity available from this endpoint.
            for key in ("best_bid", "best_ask", "last_trade", "spread", "volume", "liquidity", "one_day_change", "one_week_change", "accepting_orders"):
                row[key] = ""
            row["metadata_as_of"] = ""
        new_rows.append(row)
        print(old["slug"], row["yes_price"], row["quote_utc"], flush=True)
    # Publish the snapshot only after all active strikes succeed.
    out = folder / "snapshot.csv"
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(new_rows[0]))
        writer.writeheader()
        writer.writerows(new_rows)
    manifest = {"as_of": args.as_of.isoformat(), "cutoff_utc_exclusive": cutoff_utc(args.as_of).isoformat(),
                "retrieved_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "endpoint": "https://data-api.polymarket.com/v2/prices-history",
                "bucket_seconds": 3600, "price_kind": "historical price bucket, not bid/ask midpoint",
                "request_start_epoch_seconds": start, "request_end_epoch_seconds": end,
                "historical_liquidity_available": False}
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("Saved", out)


if __name__ == "__main__":
    main()
