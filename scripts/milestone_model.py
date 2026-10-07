"""未校准基线模型（uncalibrated baseline）。

这是「凭公开证据直接设定参数、完全不看市场价格」的版本。它的作用是验证设计
思想 —— 里程碑门控的蒙特卡洛能否复现市场期限结构上明显的 S 形 —— 并给出一个
与市场互相独立的「第二意见」。校准与融合见 scripts/calibrate_model.py，
核心引擎见 scripts/model_core.py。
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import os

from model_core import THANKSGIVING, Params, simulate

PROC = os.path.join("data", "processed")
PARAMS = Params()          # 全部使用 model_core 中的先验默认值，不拟合市场
N_PATHS = 400_000
SEED = 20261007


def main() -> None:
    res = simulate(PARAMS, N_PATHS, SEED)

    with open(os.path.join(PROC, "term_structure.csv"), encoding="utf-8") as fh:
        strikes = list(csv.DictReader(fh))

    rows = []
    for s in strikes:
        deadline = dt.date.fromisoformat(s["end_date"])
        p_model = res.cdf(deadline)
        p_market = float(s["yes_price"])
        rows.append(
            {
                "deadline": s["deadline"],
                "end_date": s["end_date"],
                "market_prob": round(p_market, 4),
                "model_prob": round(p_model, 4),
                "diff_pp": round((p_model - p_market) * 100, 2),
                "closed": s["closed"],
            }
        )

    out = os.path.join(PROC, "baseline_model_vs_market.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    summary = {
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "kind": "uncalibrated_baseline",
        "paths": N_PATHS,
        "seed": SEED,
        "assumptions": {
            "investor_day": PARAMS.investor_day.isoformat(),
            "gap_investor_day_to_roadshow": list(PARAMS.gap[1:]),
            "roadshow_len": list(PARAMS.roadshow[1:]),
            "listing_lag": list(PARAMS.listing_lag[1:]),
            "stall_prob": PARAMS.stall_prob,
        },
        "listing_date_quantiles": res.quantiles(),
        "p_list_before_thanksgiving_2026_11_26": round(res.cdf(THANKSGIVING), 4),
        "model_p_by_2026_12_15":
            next(r["model_prob"] for r in rows if "December 15" in r["deadline"]),
        "market_p_by_2026_12_15":
            next(r["market_prob"] for r in rows if "December 15" in r["deadline"]),
    }
    with open(os.path.join(PROC, "baseline_summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)

    print(f"wrote {out}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
