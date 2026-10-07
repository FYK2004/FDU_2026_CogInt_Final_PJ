"""Collect the full Polymarket 'Anthropic IPO by ___?' term structure.

Writes:
    data/raw/gamma_event_anthropic_ipo.json   raw Gamma event payload
    data/raw/history/<date>.json              Yes-token price history per strike
    data/processed/anthopic_term_structure.csv snapshot of every sub-market
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from polymarket_client import get_event, get_price_history, yes_token  # noqa: E402

SLUG = "anthropic-ipo-by"
RAW = "data/raw"
HIST = os.path.join(RAW, "history")
PROC = "data/processed"


def slugify(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")


def main() -> None:
    os.makedirs(HIST, exist_ok=True)
    os.makedirs(PROC, exist_ok=True)

    events = get_event(SLUG)
    with open(os.path.join(RAW, "gamma_event_anthropic_ipo.json"), "w", encoding="utf-8") as fh:
        json.dump(events, fh, ensure_ascii=False, indent=2)
    event = events[0]
    print(f"event: {event['title']}  markets={len(event['markets'])}")

    rows = []
    for market in event["markets"]:
        label = market["groupItemTitle"]
        tok = yes_token(market)
        prices = json.loads(market["outcomePrices"])
        row = {
            "deadline": label,
            "slug": slugify(label),
            "question": market["question"],
            "market_slug": market["slug"],
            "condition_id": market["conditionId"],
            "yes_token_id": tok,
            "yes_price": float(prices[0]),
            "best_bid": market.get("bestBid"),
            "best_ask": market.get("bestAsk"),
            "last_trade": market.get("lastTradePrice"),
            "spread": market.get("spread"),
            "volume": market.get("volumeNum"),
            "liquidity": market.get("liquidityNum"),
            "one_day_change": market.get("oneDayPriceChange"),
            "one_week_change": market.get("oneWeekPriceChange"),
            "end_date": market.get("endDate"),
            "closed": market.get("closed"),
            "accepting_orders": market.get("acceptingOrders"),
        }
        rows.append(row)

        try:
            hist = get_price_history(tok)
            with open(os.path.join(HIST, f"{row['slug']}.json"), "w", encoding="utf-8") as fh:
                json.dump(hist, fh)
            print(f"  {label:22s} yes={row['yes_price']:.4f} hist_points={len(hist)}")
        except Exception as exc:  # noqa: BLE001
            print(f"  {label:22s} history FAILED: {exc}", file=sys.stderr)

    rows.sort(key=lambda r: r["end_date"] or "")
    out = os.path.join(PROC, "anthopic_term_structure.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
