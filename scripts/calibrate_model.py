"""Market fit for diagnostics; final pool uses the UNCALIBRATED evidence model.

The target 12/15 quote is held out of calibration. Search jointly includes the
delay branch, with cached conditional CDFs and analytic stall mixing.
Sensitivity envelopes are not coverage-calibrated confidence intervals.
"""
from __future__ import annotations
import csv
import datetime as dt
import hashlib
import itertools
import json
import math
from dataclasses import asdict
import numpy as np
from model_core import Params, simulate, blend_logodds, THANKSGIVING
from project_config import PROC, ROOT, AS_OF, SEED, cutoff_utc

TARGET_DATE = dt.date(2026, 12, 15)
TARGET_LABEL = "December 15, 2026"
# Weight is a declared modelling choice, not a fitted measure of quote quality.
TARGETS = [("November 15, 2026", .25), ("November 30, 2026", 1.),
           ("December 31, 2026", 1.)]


def write_csv(name, rows):
    with (PROC / name).open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def load_market():
    with (PROC / "term_structure.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError("Empty market table")
    if any(r.get("as_of") != AS_OF.isoformat() for r in rows):
        raise ValueError("Snapshot cutoff differs from forecast cutoff; rerun analysis")
    if any(dt.datetime.fromisoformat(r["quote_utc"]) >= cutoff_utc() for r in rows):
        raise ValueError("Future quote leakage")
    end = {r["deadline"]: dt.date.fromisoformat(r["end_date"]) for r in rows}
    px = {r["deadline"]: float(r["yes_price"]) for r in rows}
    probs = [float(r["yes_price"]) for r in rows]
    if any(not 0 <= p <= 1 for p in probs) or any(a > b for a, b in zip(probs, probs[1:])):
        raise ValueError("Term structure must be a monotone CDF")
    for name in [TARGET_LABEL, *(name for name, _ in TARGETS)]:
        if name not in end or end[name] <= AS_OF:
            raise ValueError(f"Missing or expired calibration/target strike: {name}")
    return rows, end, px


def loss_from(probabilities, px):
    return sum(w*((probabilities[dl]-px[dl])*100)**2 for dl, w in TARGETS)


def market_cdf_fn(end, px, today):
    """Piecewise linear interpolation is an assumption, not a probability bound."""
    pts = [(today, 0.)] + sorted((end[k], px[k]) for k in end if end[k] > today)
    def f(day):
        if day <= today:
            return 0.
        for (d0, p0), (d1, p1) in zip(pts, pts[1:]):
            if day <= d1:
                return p0+(p1-p0)*(day-d0).days/(d1-d0).days
        return pts[-1][1]
    return f, pts


def market_implied_median(end, px):
    _, pts = market_cdf_fn(end, px, AS_OF)
    out = {}
    for q in (.25, .5, .75):
        out[f"p{int(q*100)}"] = None
        for (d0, p0), (d1, p1) in zip(pts, pts[1:]):
            if p0 <= q <= p1 and p1 > p0:
                out[f"p{int(q*100)}"] = (d0+dt.timedelta(days=round((d1-d0).days*(q-p0)/(p1-p0)))).isoformat()
                break
    return out


def sweep(end, px, grid, n_paths):
    best, records = (math.inf, None), []
    # For each timeline, one simulation suffices for every stall probability.
    # Independence of stall and durations is an explicit model assumption.
    for gm, gh, rh, ss in itertools.product(grid["mode"], grid["high"], grid["road"], grid["slip"]):
        if not 26 <= gm < gh or rh < 12:
            continue
        params = Params(gap=(26., float(gm), float(gh)), roadshow=(8., 12., float(rh)),
                        slip_share=float(ss), stall_prob=0., label="market_calibrated_diagnostic")
        live = simulate(params, n_paths, SEED)
        cond = {k: live.cdf(v) for k, v in end.items()}
        for stall in grid["stall"]:
            pred = {k: p*(1-stall) for k, p in cond.items()}
            loss = loss_from(pred, px)
            records.append(dict(stall_prob=float(stall), gap_mode=float(gm), gap_high=float(gh),
                                roadshow_high=float(rh), slip_share=float(ss),
                                p_nov15=pred["November 15, 2026"], p_nov30=pred["November 30, 2026"],
                                p_dec15=pred[TARGET_LABEL], p_dec31=pred["December 31, 2026"], loss=loss))
            if loss < best[0]:
                best = loss, params.with_(stall_prob=float(stall))
    if best[1] is None:
        raise ValueError("No valid calibration grid cell")
    return best, records


def conditional_probability(target, elapsed):
    return (target-elapsed)/(1-elapsed) if elapsed < 1 else None


def main():
    rows, end, px = load_market()
    grid = dict(mode=[26., 33., 40.], high=[40., 55., 75., 95.], road=[16., 20., 25.],
                slip=[0., .1, .25], stall=np.round(np.arange(.06, .401, .02), 3))
    (_, best), coarse = sweep(end, px, grid, 12_000)
    fine = dict(mode=sorted({max(26., best.gap[1]+d) for d in (-3, 0, 3)}),
                high=[best.gap[2]+d for d in (-7, 0, 7)],
                road=sorted({max(14., best.roadshow[2]+d) for d in (-3, 0, 3)}),
                slip=sorted({min(1., max(0., best.slip_share+d)) for d in (-.05, 0, .05)}),
                stall=sorted({round(min(1., max(0., best.stall_prob+d)), 3) for d in np.arange(-.03, .031, .01)}))
    (_, best), detailed = sweep(end, px, fine, 40_000)
    write_csv("sensitivity_grid.csv", coarse+detailed)
    # Final fit loss is recomputed at the reported path count, not the search count.
    calibrated = simulate(best, 400_000, SEED)
    baseline = simulate(Params(), 400_000, SEED)
    fit_loss = loss_from({k: calibrated.cdf(v) for k, v in end.items()}, px)
    output = [dict(deadline=r["deadline"], end_date=r["end_date"], market_prob=px[r["deadline"]],
                   model_prob=calibrated.cdf(end[r["deadline"]]),
                   diff_pp=(calibrated.cdf(end[r["deadline"]])-px[r["deadline"]])*100,
                   role="held_out_target" if r["deadline"] == TARGET_LABEL else "fit" if r["deadline"] in dict(TARGETS) else "diagnostic",
                   closed=r["closed"]) for r in rows]
    write_csv("final_model_vs_market.csv", output)
    buckets = []
    prev, prev_px = AS_OF, 0.
    for label in ["October 31, 2026", "November 15, 2026", "November 30, 2026", TARGET_LABEL, "December 31, 2026"]:
        hi = end[label]+dt.timedelta(days=1)
        m, p = px[label]-prev_px, calibrated.bucket(prev, hi)
        buckets.append(dict(bucket=f"{prev:%m/%d}–{end[label]:%m/%d}", lo=prev.isoformat(), hi=hi.isoformat(), market_prob=m, model_prob=p, diff_pp=(p-m)*100))
        prev, prev_px = hi, px[label]
    p, m = calibrated.bucket(prev), 1-prev_px
    buckets.append(dict(bucket="2027年及以后（含流产）", lo=prev.isoformat(), hi="", market_prob=m, model_prob=p, diff_pp=(p-m)*100))
    if not np.isclose(sum(b["model_prob"] for b in buckets), 1):
        raise ValueError("Model buckets do not partition probability mass")
    write_csv("bucket_implied.csv", buckets)
    surface = []
    for gh in range(max(30, int(best.gap[1])+1), 101, 5):
        live = simulate(best.with_(stall_prob=0., gap=(26., best.gap[1], float(gh))), 40_000, SEED)
        cond = {k: live.cdf(v) for k, v in end.items()}
        for stall in np.round(np.arange(.06, .411, .01), 3):
            pred = {k: p*(1-stall) for k, p in cond.items()}
            surface.append(dict(stall_prob=float(stall), gap_mode=best.gap[1], gap_high=gh,
                                roadshow_high=best.roadshow[2], loss=loss_from(pred, px), p_dec15=pred[TARGET_LABEL]))
    write_csv("sensitivity_surface.csv", surface)
    slip_rows = []
    for share in (0., .05, .1, .15, .2, .25):
        res = simulate(best.with_(slip_share=share), 40_000, SEED)
        slip_rows.append(dict(slip_share=share, p_nov30=res.cdf(end["November 30, 2026"]),
                              p_dec15=res.cdf(TARGET_DATE), p_dec31=res.cdf(end["December 31, 2026"]),
                              loss=loss_from({k: res.cdf(v) for k, v in end.items()}, px)))
    write_csv("sensitivity_slip.csv", slip_rows)
    hist = np.bincount(calibrated.offset[~calibrated.stall])
    write_csv("listing_date_hist.csv", [dict(date=(best.investor_day+dt.timedelta(days=i)).isoformat(),
               count=int(c), prob=float(c)/calibrated.n_paths) for i, c in enumerate(hist)])

    # Pool uses evidence-only baseline, NEVER the market-fitted simulation.
    p_model, p_market, weight = baseline.cdf(TARGET_DATE), px[TARGET_LABEL], .35
    p_final = blend_logodds(p_model, p_market, weight)
    band = []
    for stall, gap_high, slip_share in itertools.product((.09, .12, .15), (48., 55., 62.), (0., .1)):
        alt = simulate(Params(stall_prob=stall, gap=(26., 26., gap_high), slip_share=slip_share), 100_000, SEED)
        band.extend(blend_logodds(alt.cdf(TARGET_DATE), p_market, w) for w in (.25, .35, .5))
    band.append(p_final)
    mkt_cdf, _ = market_cdf_fn(end, px, AS_OF)
    before_tg = THANKSGIVING-dt.timedelta(days=1)
    scenarios = {"A_conditional_after_thanksgiving": {
        "question": "若11/26之前仍未挂牌，则12/15（含）前挂牌的条件概率？",
        "market_implied": conditional_probability(p_market, mkt_cdf(before_tg)),
        "model": conditional_probability(calibrated.cdf(TARGET_DATE), calibrated.cdf_before(THANKSGIVING)),
        "evidence_model": conditional_probability(p_model, baseline.cdf_before(THANKSGIVING)),
        "note": "市场值依赖线性插值；模型值依赖流程假设。相邻期限节点能推算同类条件概率。"},
        "market_implied_p_by_thanksgiving": mkt_cdf(before_tg),
        "model_p_by_thanksgiving": calibrated.cdf_before(THANKSGIVING),
        "B_roadshow_delayed": {}}
    for weeks in (1, 2):
        alt = simulate(best.with_(gap=tuple(x+7*weeks for x in best.gap)), 400_000, SEED)
        scenarios["B_roadshow_delayed"][f"roadshow_delay_{weeks}w"] = dict(p_by_2026_12_15=alt.cdf(TARGET_DATE), median_listing_date=alt.date_at(.5).isoformat())
    update_path = ROOT / "data/updates" / f"{AS_OF}.json"
    update = json.loads(update_path.read_text(encoding="utf-8")) if update_path.exists() else None
    if update:
        for source in update["sources"]:
            if source.get("used_for_forecast") and dt.datetime.fromisoformat(source["published_utc"]) >= cutoff_utc():
                raise ValueError("Future news leakage")
    target_row = next(r for r in rows if r["deadline"] == TARGET_LABEL)
    forecast = dict(schema_version=2, as_of=AS_OF.isoformat(), information_cutoff_utc_exclusive=cutoff_utc().isoformat(),
        generated_utc=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        target_question="Anthropic是否在2026-12-15美东时间23:59前挂牌并开放交易？",
        target_date=TARGET_DATE.isoformat(),
        provenance=dict(seed=SEED, paths=400000, term_structure_sha256=hashlib.sha256((PROC/"term_structure.csv").read_bytes()).hexdigest()),
        market=dict(polymarket_event="anthropic-ipo-by / december-15-2026", yes_price=p_market,
                    quote_utc=target_row["quote_utc"], quote_source=target_row["quote_source"],
                    historical_liquidity_available=False, kalshi_cross_check=None),
        model=dict(kind="market_calibrated_milestone_diagnostic", calibrated_params=asdict(best),
                   fit_targets=dict(TARGETS), held_out_target=TARGET_LABEL, fit_loss_weighted=fit_loss,
                   p_by_target=calibrated.cdf(TARGET_DATE), p_before_thanksgiving=calibrated.cdf_before(THANKSGIVING),
                   median_listing_date=calibrated.date_at(.5).isoformat(), listing_date_quantiles=calibrated.quantiles(),
                   quantiles_conditioning="conditional_on_no_absorbing_failure"),
        evidence_model=dict(p_by_target=p_model, params=asdict(Params()),
                            monte_carlo_standard_error=math.sqrt(p_model*(1-p_model)/baseline.n_paths),
                            investor_day_status="reported_held" if update else "planned",
                            note="财务消息不自动映射为失败概率；参数为流程假设，尚无历史IPO样本估计。"),
        market_implied_median_listing_date=market_implied_median(end, px), scenarios=scenarios,
        blend_logodds_by_model_weight={str(w): blend_logodds(p_model, p_market, w) for w in (0., .25, .35, .5, .65, 1.)},
        final=dict(method="heuristic_logodds_pool_of_uncalibrated_evidence_model_and_market", model_weight=weight,
                   p_final=p_final, p_final_pct=round(p_final*100, 1),
                   sensitivity_range=[min(band), max(band)],
                   sensitivity_definition="evidence stall .09/.12/.15 × gap_high 48/55/62 × slip 0/.1 × weight .25/.35/.5; no coverage guarantee",
                   call="Yes" if p_final >= .5 else "No", edge_vs_market_pp=(p_final-p_market)*100,
                   independence_assumed=False),
        evidence_update=update,
        limitations=["意见池权重尚未做样本外验证；差值不代表可交易收益。", "拟合损失不是预测准确率。",
                     "市场中位数为无条件分位数，模型日期分位数以未流产为条件，不能直接比较。"])
    (PROC / "forecast.json").write_text(json.dumps(forecast, ensure_ascii=False, indent=2, default=lambda x: x.isoformat()), encoding="utf-8")
    print(f"as_of={AS_OF} evidence={p_model:.4%} market={p_market:.4%} diagnostic={calibrated.cdf(TARGET_DATE):.4%} final={p_final:.4%}")
    print("sensitivity_range=", forecast["final"]["sensitivity_range"], "fit_loss=", fit_loss)


if __name__ == "__main__":
    main()
