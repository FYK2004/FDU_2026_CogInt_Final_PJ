"""Turn the raw Polymarket snapshots into the analysis tables used in the report.

Outputs
-------
data/processed/term_structure.csv      snapshot + implied hazard rate per strike
data/processed/history_wide.csv         daily Yes-price panel, one column per strike
data/processed/jump_events.csv         largest day-over-day moves per strike
"""

from __future__ import annotations

import csv
import datetime as dt
import glob
import json
import os
import math
from project_config import RAW, PROC, AS_OF, market_deadline, cutoff_utc


# Strike order = chronological by resolution date.
ORDER = [
    "june-30-2026",
    "july-31-2026",
    "september-15-2026",
    "september-30-2026",
    "october-15-2026",
    "october-31-2026",
    "november-15-2026",
    "november-30-2026",
    "december-15-2026",
    "december-31-2026",
]


def utc(ts: float) -> dt.datetime:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc)


def load_snapshot() -> dict[str, dict]:
    path = RAW / "backfill" / AS_OF.isoformat() / "snapshot.csv"
    if not path.exists():
        if AS_OF != dt.date(2026, 10, 7):
            raise FileNotFoundError(f"Missing dated snapshot: {path}; run backfill_market.py")
        from project_config import ROOT
        path = ROOT / "data/archive/2026-10-07/processed/anthopic_term_structure.csv"
    with open(path, encoding="utf-8") as fh:
        return {r["slug"]: r for r in csv.DictReader(fh)}


def load_histories() -> dict[str, list[tuple[dt.datetime, float]]]:
    out: dict[str, list[tuple[dt.datetime, float]]] = {}
    for path in glob.glob(os.path.join(RAW, "history", "*.json")):
        slug = os.path.basename(path)[:-5]
        with open(path, encoding="utf-8") as fh:
            hist = json.load(fh)
        out[slug] = sorted((utc(pt["t"]), float(pt["p"])) for pt in hist)
    folder = RAW / "backfill" / AS_OF.isoformat()
    for path in folder.glob("*.json"):
        if path.name == "manifest.json":
            continue
        with path.open(encoding="utf-8") as fh:
            points = json.load(fh)
        merged = {t: p for t, p in out.get(path.stem, [])}
        merged.update({utc(pt["t"]): float(pt["p"]) for pt in points})
        out[path.stem] = sorted(merged.items())
    return {slug: [(t, p) for t, p in series if t < cutoff_utc()]
            for slug, series in out.items()}


def isotonic_probabilities(values):
    """Equal-weight PAVA; raw quotes remain available for auditing."""
    blocks = []
    for p in values:
        if not math.isfinite(p) or not 0 <= p <= 1:
            raise ValueError("Invalid market probability")
        blocks.append([p, 1])
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
            b, a = blocks.pop(), blocks.pop()
            count = a[1]+b[1]
            blocks.append([(a[0]*a[1]+b[0]*b[1])/count, count])
    return [p for p, count in blocks for _ in range(count)]


def build_term_structure(snap: dict[str, dict], hist: dict[str, list]) -> list[dict]:
    rows = []
    ordered = [snap[s] for s in ORDER if s in snap]
    adjusted = dict(zip([r["slug"] for r in ordered],
                        isotonic_probabilities([float(r["yes_price"]) for r in ordered])))
    prev_p, prev_end = 0.0, AS_OF
    for slug in ORDER:
        if slug not in snap:
            continue
        row = snap[slug]
        p = adjusted[slug]
        end = market_deadline(row)
        # Hazard h = -ln((1-F(t_k))/(1-F(t_{k-1}))) / dt, annualized percent.
        # that would reconcile two adjacent points of the survival curve.
        hazard = ""
        if end > prev_end and prev_p < 1 and p < 1:
            gap_days = (end - prev_end).days
            hazard = round(-math.log((1-p)/(1-prev_p))/gap_days*365*100, 4)
        rows.append(
            {
                "deadline": row["deadline"],
                "slug": slug,
                "end_date": end.isoformat(),
                "end_date_utc_metadata": row["end_date"],
                "as_of": AS_OF.isoformat(),
                "quote_utc": row.get("quote_utc", "2026-10-07T09:12:36+00:00"),
                "quote_source": row.get("quote_source", "gamma_snapshot"),
                "raw_yes_price": float(row["yes_price"]),
                "yes_price": p,
                "monotonic_adjustment_pp": round((p-float(row["yes_price"]))*100, 6),
                "implied_prob_pct": round(p * 100, 2),
                "annualized_hazard_pct": hazard,
                "volume_usd": round(float(row["volume"]), 2) if row["volume"] else "",
                "liquidity_usd": round(float(row["liquidity"]), 2) if row["liquidity"] else "",
                "spread": row["spread"],
                "closed": row["closed"],
                "history_points": len(hist.get(slug, [])),
            }
        )
        if end > AS_OF:
            prev_p, prev_end = p, end
    return rows


def build_wide(hist: dict[str, list]) -> tuple[list[str], list[dict]]:
    """Daily close panel (last observation of each UTC day)."""
    daily: dict[str, dict[str, float]] = {}
    for slug, series in hist.items():
        if not series:
            continue
        for ts, p in series:
            daily.setdefault(ts.date().isoformat(), {})[slug] = p
    days = sorted(daily)
    cols = [s for s in ORDER if any(s in daily[d] for d in days)]
    rows = [{"date": d, **{c: daily[d].get(c, "") for c in cols}} for d in days]
    return ["date", *cols], rows


def build_jumps(hist: dict[str, list], top: int = 8) -> list[dict]:
    out = []
    for slug, series in hist.items():
        if len(series) < 2:
            continue
        daily: dict[str, float] = {}
        for ts, p in series:
            daily[ts.date().isoformat()] = p  # last point of the day wins
        days = sorted(daily)
        moves = [
            (days[i], daily[days[i]] - daily[days[i - 1]], daily[days[i - 1]], daily[days[i]])
            for i in range(1, len(days))
            if (dt.date.fromisoformat(days[i])-dt.date.fromisoformat(days[i-1])).days == 1
        ]
        for day, delta, a, b in sorted(moves, key=lambda m: -abs(m[1]))[:top]:
            out.append(
                {
                    "slug": slug,
                    "date": day,
                    "delta_pp": round(delta * 100, 2),
                    "from": round(a, 4),
                    "to": round(b, 4),
                }
            )
    return sorted(out, key=lambda r: (r["slug"], -abs(r["delta_pp"])))


def write_csv(path: str, fieldnames: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {path} ({len(rows)} rows)")


def main() -> None:
    PROC.mkdir(parents=True, exist_ok=True)
    snap = load_snapshot()
    hist = load_histories()

    ts_rows = build_term_structure(snap, hist)
    write_csv(
        os.path.join(PROC, "term_structure.csv"),
        list(ts_rows[0].keys()),
        ts_rows,
    )

    cols, wide = build_wide(hist)
    write_csv(os.path.join(PROC, "history_wide.csv"), cols, wide)

    jumps = build_jumps(hist)
    write_csv(
        os.path.join(PROC, "jump_events.csv"),
        ["slug", "date", "delta_pp", "from", "to"],
        jumps,
    )


if __name__ == "__main__":
    main()
