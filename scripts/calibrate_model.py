"""模型校准 + 市场融合 + 最终预测。

流程
----
1. 读取市场的期限结构（data/processed/term_structure.csv，Polymarket Yes 价）。
2. **两阶段网格搜索**：在 (stall_prob, gap_mode, gap_high, roadshow_high) 上搜索，
   用「加权平方误差」拟合市场的 4 个活跃节点（11/15、11/30、12/15、12/31）。
   之所以要校准，是因为先验参数的基线模型系统性慢了一周：它把中位挂牌日放在
   11/30，而市场期限结构隐含的中位挂牌日是 11/25 前后。
3. 用最优参数做 400k 路径精算，输出 final_model_vs_market.csv 与分桶概率。
4. 用 log-odds 加权把模型与市场融合，给出**最终预测**及其不确定性区间。

校准得到的参数会一并写入 forecast.json，并且必须能用地上的公开证据解释，
否则只算「拟合」不算「校准」。
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from model_core import (  # noqa: E402
    Params,
    blend_logodds,
    simulate,
)

PROC = os.path.join("data", "processed")
TODAY = dt.date(2026, 10, 7)
TARGET_DATE = dt.date(2026, 12, 15)      # 本题标的：「2026-12-15 前是否 IPO」
TARGET_END = dt.date(2026, 12, 16)       # 结算语义：<= 12/15 当日
SEED = 20261007

# 参与参数选择的目标节点。
#
# 为什么要排除 11/15 节点：该节点 13% 的报价隐含「11/15 之前完成挂牌」，而公开
# 报道（Bloomberg，2026-10-01/02：路演最快 11 月 9 日当周启动）意味着路演在 11/9
# 才启动，此后还需约两周簿记 + 定价 + 首日交易，11/15 前挂牌在时序上几乎不可能。
# 该节点同时是活跃节点中流动性最薄的一个（liquidity 9,905 美元，仅为 12/15 节点的
# 41%、12/31 节点的 32%）。因此它被排除在目标函数之外，其偏离量在
# final_model_vs_market.csv 与报告第 5 节中单独作为「市场异常」披露，而不是被
# 参数强行拟合掉。
TARGETS = [
    ("November 30, 2026", 1.0),
    ("December 15, 2026", 1.0),
    ("December 31, 2026", 1.0),
]
# 只在诊断中使用的节点（不参与参数选择）。
DIAGNOSTIC = ["November 15, 2026"]


def load_market():
    """返回 (节点列表, {deadline: end_date}, {deadline: yes_price})。"""
    with open(os.path.join(PROC, "term_structure.csv"), encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    end = {r["deadline"]: dt.date.fromisoformat(r["end_date"]) for r in rows}
    px = {r["deadline"]: float(r["yes_price"]) for r in rows}
    return rows, end, px


def loss_from(res, end: dict) -> float:
    total = 0.0
    for dl, w in TARGETS:
        p_mkt = PX[dl]
        total += w * ((res.cdf(end[dl]) - p_mkt) * 100.0) ** 2
    return total


def market_implied_median(end: dict) -> dict:
    """把期限结构看成 CDF，分段线性插值求市场隐含的分位数挂牌日。"""
    pts = sorted(
        ((end[dl], PX[dl]) for dl in end if end[dl] > TODAY and PX[dl] > 0),
        key=lambda t: t[0],
    )
    out = {}
    for q in (0.25, 0.50, 0.75):
        for (d0, p0), (d1, p1) in zip(pts, pts[1:]):
            if p0 <= q <= p1 and p1 > p0:
                frac = (q - p0) / (p1 - p0)
                days = (d1 - d0).days * frac
                out[f"p{int(q * 100)}"] = (
                    d0 + dt.timedelta(days=int(round(days)))
                ).isoformat()
                out[f"p{int(q * 100)}_exact"] = f"{d0.isoformat()}+{days:.2f}d"
                break
        else:
            out[f"p{int(q * 100)}"] = None
    return out


def sweep(end: dict, grid: dict, n_paths: int, base: Params):
    """在网格上搜索最优参数。返回 (最优 Params, 结果列表)。"""
    results = []
    best = (math.inf, base)
    for stall in grid["stall"]:
        for gm in grid["gap_mode"]:
            for gh in grid["gap_high"]:
                for rh in grid["road_high"]:
                    # 三角分布要求 下界 < 众数 < 上界；网格取整后可能越界，这里兜底。
                    # 下界 24 天 = 2026-11-07，即「11 月 9 日当周启动」报道所能容许的
                    # 最早路演启动日；不允许参数跑到证据之外。
                    gm = float(min(max(gm, 24.0), 80.0))
                    gh = float(max(gh, gm + 5.0))
                    rh = float(max(rh, 14.0))
                    p = base.with_(
                        stall_prob=float(stall),
                        gap=(16.0, gm, gh),
                        roadshow=(8.0, 12.0, rh),
                    )
                    res = simulate(p, n_paths, SEED)
                    L = loss_from(res, end)
                    results.append(
                        {
                            "stall_prob": float(stall),
                            "gap_mode": float(gm),
                            "gap_high": float(gh),
                            "roadshow_high": float(rh),
                            "p_nov15": res.cdf(end["November 15, 2026"]),
                            "p_nov30": res.cdf(end["November 30, 2026"]),
                            "p_dec15": res.cdf(end["December 15, 2026"]),
                            "p_dec31": res.cdf(end["December 31, 2026"]),
                            "loss": L,
                        }
                    )
                    if L < best[0]:
                        best = (L, p)
    return best, results


def market_cdf_fn(end: dict, px: dict, today: dt.date):
    """把期限结构看成 CDF：对 (结算日, Yes 价) 做分段线性插值，得到任意日期的市场隐含概率。

    注意：线性插值等价于假设「相邻节点之间每天的挂牌密度是均匀的」。这对
    12/16–12/31 这个窗口明显不现实（超大型 IPO 不会在圣诞前后两周定价），
    因此本函数给出的 12 月窗口概率应视为**市场隐含的上界**。
    """
    pts = sorted(
        ((end[dl], px[dl]) for dl in end if end[dl] > today),
        key=lambda t: t[0],
    )

    def f(day: dt.date) -> float:
        if day <= pts[0][0]:
            return pts[0][1]
        for (d0, p0), (d1, p1) in zip(pts, pts[1:]):
            if d0 <= day <= d1:
                if d1 == d0:
                    return p1
                return p0 + (p1 - p0) * (day - d0).days / (d1 - d0).days
        return pts[-1][1]

    return f, pts


def main() -> None:
    global PX
    rows, end, PX = load_market()

    # --- 阶段一：粗网格 ---------------------------------------------------
    grid1 = {
        "stall": np.round(np.arange(0.06, 0.301, 0.02), 3).tolist(),
        "gap_mode": [24.0, 26.0, 33.0, 40.0],
        "gap_high": [40.0, 50.0, 60.0, 75.0, 95.0],
        "road_high": [16.0, 20.0, 25.0],
    }
    (L1, best1), res1 = sweep(end, grid1, 12_000, Params())
    print(f"stage1 best loss={L1:.1f} params={best1}")

    # --- 阶段二：在最优点附近细化 ----------------------------------------
    def clamp(vals, lo, hi):
        """去重 + 保证三角分布的参数合法（下界 < 众数 < 上界）。"""
        return sorted({float(min(max(v, lo), hi)) for v in vals})

    gm = best1.gap[1]
    gh = best1.gap[2]
    rh = best1.roadshow[2]
    grid2 = {
        "stall": np.round(
            np.arange(max(0.02, best1.stall_prob - 0.04), best1.stall_prob + 0.041, 0.01), 3
        ).tolist(),
        "gap_mode": clamp([gm - 7, gm, gm + 7], 24.0, 80.0),
        "gap_high": clamp([gh + d for d in (-15, -7, 0, 7, 15)], gm + 5.0, 120.0),
        "road_high": clamp([rh + d for d in (-3, 0, 3)], 14.0, 30.0),
    }
    (L2, best2), res2 = sweep(end, grid2, 40_000, Params())
    print(f"stage2 best loss={L2:.1f} params={best2}")

    all_cells = res1 + res2
    with open(os.path.join(PROC, "sensitivity_grid.csv"), "w", newline="",
              encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(all_cells[0].keys()))
        w.writeheader()
        w.writerows(all_cells)

    # --- 阶段三：一维搜索「延期支线」占比 --------------------------------
    # 没有这一支线时，时间线的硬右边界会让 P(12/15) 恒等于 P(12/31)，而市场
    # 的 12/31 节点比 12/15 节点高 4pp（即承认存在少量「12 月上中旬才定价」）。
    slip_rows = []
    best3 = best2
    best3_loss = L2
    for ss in (0.0, 0.05, 0.10, 0.15, 0.20, 0.25):
        p = best2.with_(slip_share=float(ss))
        res = simulate(p, 40_000, SEED)
        L = loss_from(res, end)
        slip_rows.append(
            {
                "slip_share": float(ss),
                "p_nov30": res.cdf(end["November 30, 2026"]),
                "p_dec15": res.cdf(end["December 15, 2026"]),
                "p_dec31": res.cdf(end["December 31, 2026"]),
                "loss": L,
            }
        )
        if L < best3_loss:
            best3_loss, best3 = L, p
    print(f"stage3 best loss={best3_loss:.1f} slip_share={best3.slip_share}")
    with open(os.path.join(PROC, "sensitivity_slip.csv"), "w", newline="",
              encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(slip_rows[0].keys()))
        w.writeheader()
        w.writerows(slip_rows)

    # --- 参数敏感性曲面（供 fig6 使用） -----------------------------------
    # 两阶段搜索的网格点是稀疏且不规则的，直接热力图会留空洞。这里在最优解所在
    # 切片 gap_mode = best3.gap[1] 上，用整齐的 (stall_prob, gap_high) 网格重算
    # 一张稠密误差曲面，只用于画图，不参与参数选择。
    surf_rows = []
    for stall in np.round(np.arange(0.06, 0.305, 0.01), 3):
        for gh in np.arange(30.0, 100.0, 5.0):
            p = best3.with_(
                stall_prob=float(stall),
                gap=(best3.gap[0], best3.gap[1], float(gh)),
            )
            res = simulate(p, 40_000, SEED)
            surf_rows.append(
                {
                    "stall_prob": float(stall),
                    "gap_mode": float(best3.gap[1]),
                    "gap_high": float(gh),
                    "roadshow_high": float(best3.roadshow[2]),
                    "loss": loss_from(res, end),
                    "p_dec15": res.cdf(end["December 15, 2026"]),
                }
            )
    with open(os.path.join(PROC, "sensitivity_surface.csv"), "w", newline="",
              encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(surf_rows[0].keys()))
        w.writeheader()
        w.writerows(surf_rows)

    # --- 最终精算 ---------------------------------------------------------
    final = simulate(best3, 400_000, SEED)
    mkt_med = market_implied_median(end)

    rows_out = []
    for r in rows:
        dl = r["deadline"]
        p_model = final.cdf(end[dl])
        rows_out.append(
            {
                "deadline": dl,
                "end_date": r["end_date"],
                "market_prob": round(float(r["yes_price"]), 4),
                "model_prob": round(p_model, 4),
                "diff_pp": round((p_model - float(r["yes_price"])) * 100.0, 2),
                "closed": r["closed"],
            }
        )
    with open(os.path.join(PROC, "final_model_vs_market.csv"), "w", newline="",
              encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows_out[0].keys()))
        w.writeheader()
        w.writerows(rows_out)

    # --- 分桶概率 ---------------------------------------------------------
    # 市场：期限结构相邻节点相减 = 该时间窗口的隐含挂牌概率。
    # 模型：同一窗口上的蒙特卡洛频率。两者对照能定位分歧的具体位置。
    bucket_spec = [
        # (标签, 上一节点, 本节点, 窗口起点, 窗口终点)
        ("10/31 及以前", None, "October 31, 2026",
         TODAY, dt.date(2026, 11, 1)),
        ("11/01 - 11/15", "October 31, 2026", "November 15, 2026",
         dt.date(2026, 11, 1), dt.date(2026, 11, 16)),
        ("11/16 - 11/30", "November 15, 2026", "November 30, 2026",
         dt.date(2026, 11, 16), dt.date(2026, 12, 1)),
        ("12/01 - 12/15", "November 30, 2026", "December 15, 2026",
         dt.date(2026, 12, 1), dt.date(2026, 12, 16)),
        ("12/16 - 12/31", "December 15, 2026", "December 31, 2026",
         dt.date(2026, 12, 16), dt.date(2027, 1, 1)),
        ("2027 年及以后（含流产）", "December 31, 2026", None,
         dt.date(2027, 1, 1), dt.date(2099, 1, 1)),
    ]
    buckets = []
    for name, prev_dl, cur_dl, lo, hi in bucket_spec:
        mkt = (float(PX[cur_dl]) if cur_dl else 1.0) - (float(PX[prev_dl]) if prev_dl else 0.0)
        buckets.append(
            {
                "bucket": name,
                "lo": lo.isoformat(),
                "hi": "" if hi.year > 2090 else hi.isoformat(),
                "market_prob": round(mkt, 4),
                "model_prob": round(final.bucket(lo, hi), 4),
                "diff_pp": round((final.bucket(lo, hi) - mkt) * 100.0, 2),
            }
        )
    with open(os.path.join(PROC, "bucket_implied.csv"), "w", newline="",
              encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(buckets[0].keys()))
        w.writeheader()
        w.writerows(buckets)

    # --- 融合与最终预测 ---------------------------------------------------
    p_model = final.cdf(TARGET_END)
    p_market = float(PX["December 15, 2026"])
    blend = {
        str(wm): round(blend_logodds(p_model, p_market, wm), 4)
        for wm in (0.0, 0.25, 0.35, 0.50, 0.65, 1.0)
    }
    W_MODEL = 0.35
    p_final = blend_logodds(p_model, p_market, W_MODEL)

    # 不确定性：参数邻域 × 融合权重的包络
    lo_hi = []
    for stall in (best3.stall_prob - 0.03, best3.stall_prob + 0.03):
        alt = simulate(best3.with_(stall_prob=float(stall)), 200_000, SEED)
        lo_hi.append(alt.cdf(TARGET_END))
    lo_hi.append(p_model)
    band = [
        blend_logodds(pl, p_market, wm)
        for pl in lo_hi
        for wm in (0.25, 0.35, 0.50)
    ]

    hist = np.bincount(
        final.offset[~final.stall].astype(np.int64),
        minlength=(dt.date(2027, 1, 15) - final.params.investor_day).days + 1,
    )
    with open(os.path.join(PROC, "listing_date_hist.csv"), "w", newline="",
              encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "count", "prob"])
        for i, c in enumerate(hist):
            if i % 7 == 0 or c:
                w.writerow([
                    (final.params.investor_day + dt.timedelta(days=int(i))).isoformat(),
                    int(c),
                    round(float(c) / final.n_paths, 6),
                ])

    # --- 条件更新情景（模型相对「读报价」的核心优势） ---------------------
    mkt_cdf, _ = market_cdf_fn(end, PX, TODAY)
    tg = dt.date(2026, 11, 26)   # 感恩节

    # 情景 A：若感恩节前未能挂牌，则 12/15 前完成挂牌的条件概率。
    # 市场版本 = (F_mkt(12/15) - F_mkt(11/26)) / (1 - F_mkt(11/26))
    m_after_tg = 1.0 - mkt_cdf(tg)
    m_cond = (float(PX["December 15, 2026"]) - mkt_cdf(tg)) / m_after_tg
    d_after_tg = 1.0 - final.cdf(tg)
    d_cond = (final.cdf(TARGET_END) - final.cdf(tg)) / d_after_tg

    # 情景 B/C：路演启动整体推迟 1 周 / 2 周
    def shift_gap(p: Params, days: int) -> Params:
        lo, mo, hi = p.gap
        return p.with_(gap=(lo + days, mo + days, hi + days))

    delayed = {}
    for weeks in (1, 2):
        alt = simulate(shift_gap(best3, 7 * weeks), 400_000, SEED)
        delayed[f"roadshow_delay_{weeks}w"] = {
            "p_by_2026_12_15": round(alt.cdf(TARGET_END), 4),
            "median_listing_date": alt.date_at(0.50).isoformat(),
        }

    scenarios = {
        "A_conditional_after_thanksgiving": {
            "question": "若感恩节（11/26）前仍未能挂牌，则 12/15 前完成挂牌的概率？",
            "market_implied": round(m_cond, 4),
            "model": round(d_cond, 4),
            "note": "市场隐含值用分段线性插值在 11/26 处取值，见 market_cdf_fn 的说明。",
        },
        "B_roadshow_delayed": delayed,
        "market_implied_p_by_thanksgiving": round(mkt_cdf(tg), 4),
        "model_p_by_thanksgiving": round(final.cdf(tg), 4),
    }

    forecast = {
        "target_question": "Anthropic 是否会在 2026-12-15（含）之前正式 IPO 并开始交易？",
        "target_date": TARGET_DATE.isoformat(),
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "market": {
            "polymarket_event": "anthropic-ipo-by / december-15-2026",
            "yes_price": p_market,
            "kalshi_cross_check": {"anthropic_ipo_first_yes": 0.95,
                                   "openai_ipo_first_yes": 0.03},
        },
        "model": {
            "kind": "milestone_gated_monte_carlo",
            "calibrated_params": {
                "investor_day": best3.investor_day.isoformat(),
                "gap_calendar_days": list(best3.gap),
                "roadshow_calendar_days": list(best3.roadshow),
                "listing_lag_calendar_days": list(best3.listing_lag),
                "slip_share": best3.slip_share,
                "slip_calendar_days": list(best3.slip),
                "stall_prob": best3.stall_prob,
            },
            "fit_loss_weighted": round(best3_loss, 2),
            "p_by_target": round(p_model, 4),
            "p_before_thanksgiving": round(final.cdf(tg), 4),
            "median_listing_date": final.date_at(0.50).isoformat(),
            "listing_date_quantiles": final.quantiles(),
        },
        "market_implied_median_listing_date": mkt_med,
        "scenarios": scenarios,
        "blend_logodds_by_model_weight": blend,
        "final": {
            "model_weight": W_MODEL,
            "p_final": round(p_final, 4),
            "p_final_pct": round(p_final * 100, 1),
            "band_80pct": [round(min(band), 4), round(max(band), 4)],
            "call": "Yes（倾向于 Anthropic 会在 2026-12-15 前完成 IPO）",
            "edge_vs_market_pp": round((p_final - p_market) * 100, 2),
        },
    }
    with open(os.path.join(PROC, "forecast.json"), "w", encoding="utf-8") as fh:
        json.dump(forecast, fh, ensure_ascii=False, indent=2)

    print(json.dumps(forecast, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
