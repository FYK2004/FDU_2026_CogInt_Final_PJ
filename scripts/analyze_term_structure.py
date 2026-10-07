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

RAW = "data/raw"
PROC = "data/processed"

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
    with open(os.path.join(PROC, "anthopic_term_structure.csv"), encoding="utf-8") as fh:
        return {r["slug"]: r for r in csv.DictReader(fh)}


def load_histories() -> dict[str, list[tuple[dt.datetime, float]]]:
    out: dict[str, list[tuple[dt.datetime, float]]] = {}
    for path in glob.glob(os.path.join(RAW, "history", "*.json")):
        slug = os.path.basename(path)[:-5]
        with open(path, encoding="utf-8") as fh:
            hist = json.load(fh)
        out[slug] = sorted((utc(pt["t"]), float(pt["p"])) for pt in hist)
    return out


def build_term_structure(snap: dict[str, dict], hist: dict[str, list]) -> list[dict]:
    rows = []
    prev_p, prev_end = 1.0, None
    for slug in ORDER:
        if slug not in snap:
            continue
        row = snap[slug]
        p = float(row["yes_price"])
        end = dt.datetime.fromisoformat(row["end_date"].replace("Z", "+00:00"))
        # Hazard h = -ln(P(t_k)/P(t_{k-1})) / dt, i.e. the constant IPO intensity
        # that would reconcile two adjacent points of the survival curve.
        hazard = ""
        if prev_end is not None and prev_p > 0 and p < prev_p:
            gap_days = (end - prev_end).total_seconds() / 86400
            import math

            hazard = round(-math.log(p / prev_p) / gap_days * 365, 4)
        rows.append(
            {
                "deadline": row["deadline"],
                "slug": slug,
                "end_date": end.date().isoformat(),
                "yes_price": p,
                "implied_prob_pct": round(p * 100, 2),
                "annualized_hazard_pct": hazard,
                "volume_usd": round(float(row["volume"] or 0), 2),
                "liquidity_usd": round(float(row["liquidity"] or 0), 2),
                "spread": row["spread"],
                "closed": row["closed"],
                "history_points": len(hist.get(slug, [])),
            }
        )
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
