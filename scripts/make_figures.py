"""生成报告用图表。

运行（需要 matplotlib）：
    D:\\miniconda\\python.exe -X utf8 scripts/make_figures.py

输出到 figures/ 目录，全部使用 data/processed/ 下的中间结果，不重新联网。
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

plt.rcParams.update(
    {
        "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
        "axes.unicode_minus": False,
        "figure.dpi": 170,
        "savefig.dpi": 170,
        "axes.grid": True,
        "grid.alpha": 0.22,
        "grid.linestyle": "-",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.titlesize": 12,
        "axes.labelsize": 10,
        "legend.frameon": False,
    }
)

from project_config import PROC, ROOT, AS_OF
FIGS = str(ROOT / "figures")
os.makedirs(FIGS, exist_ok=True)

C_MKT = "#1f4e79"      # 市场
C_BASE = "#9aa4ad"     # 未校准基线
C_CAL = "#c0504d"      # 校准后模型
C_ACC = "#d98c1f"      # 强调
TARGET = dt.date(2026, 12, 15)
THANKSGIVING = dt.date(2026, 11, 26)

pct = FuncFormatter(lambda v, _: f"{v * 100:.0f}%")


def read_csv(name):
    with open(os.path.join(PROC, name), encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def load_json(name):
    with open(os.path.join(PROC, name), encoding="utf-8") as fh:
        return json.load(fh)


def save(fig, name):
    path = os.path.join(FIGS, name)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {path}")


# --- 图 1：市场期限结构 ----------------------------------------------------
def fig_term_structure():
    rows = read_csv("term_structure.csv")
    labels = [r["deadline"].replace(", 2026", "").replace(" ", "\n") for r in rows]
    probs = [float(r["yes_price"]) for r in rows]
    closed = [r["closed"] == "True" for r in rows]

    fig, ax = plt.subplots(figsize=(8.4, 3.6))
    xs = np.arange(len(rows))
    colors = [
        "#c9ced3" if c else (C_ACC if r["slug"] == "december-15-2026" else C_MKT)
        for c, r in zip(closed, rows)
    ]
    ax.bar(xs, probs, color=colors, width=0.62)
    for x, p, c in zip(xs, probs, closed):
        txt = "已到期" if c else f"{p * 100:.2f}%"
        ax.annotate(txt, (x, p), textcoords="offset points", xytext=(0, 4),
                    ha="center", fontsize=8, color="#555555")
    ax.set_xticks(xs)
    ax.set_xticklabels(labels, fontsize=8.5)
    ax.set_ylim(0, 1.0)
    ax.yaxis.set_major_formatter(pct)
    ax.set_ylabel("Yes 报价（隐含概率）")
    ax.set_title(f"Polymarket「Anthropic 是否会在该日期前正式 IPO」期限结构（{AS_OF} 美东）")
    handles = [
        Line2D([], [], color=C_ACC, lw=6, label="本题标的节点 12/15"),
        Line2D([], [], color=C_MKT, lw=6, label="其他活跃节点"),
        Line2D([], [], color="#c9ced3", lw=6, label="已到期节点"),
    ]
    ax.legend(handles=handles, fontsize=8.5, ncols=3, loc="upper left")
    save(fig, "fig1_term_structure.png")


# --- 图 2：关键节点的日度价格与跳变 ---------------------------------------
def fig_history():
    rows = read_csv("history_wide.csv")
    dates = [dt.date.fromisoformat(r["date"]) for r in rows]
    series = {
        "10/31": "october-31-2026",
        "11/15": "november-15-2026",
        "11/30": "november-30-2026",
        "12/15（本题）": "december-15-2026",
        "12/31": "december-31-2026",
    }
    style = {
        "10/31": (C_BASE, 1.2, 0.85),
        "11/15": ("#7f9c3f", 1.6, 1.0),
        "11/30": (C_MKT, 1.8, 1.0),
        "12/15（本题）": (C_ACC, 2.6, 1.0),
        "12/31": (C_CAL, 1.6, 1.0),
    }
    fig, ax = plt.subplots(figsize=(8.4, 4.0))
    for label, slug in series.items():
        ys = [
            float(r[slug]) if r.get(slug) not in (None, "") else np.nan for r in rows
        ]
        c, lw, alpha = style[label]
        ax.plot(dates, ys, color=c, lw=lw, alpha=alpha, label=label)

    # 事件用「竖虚线 + 序号」标注，具体说明统一放到图下方，避免文字与曲线重叠。
    events = [
        (dt.date(2026, 9, 19), "①", "① 9/19 WSJ：IPO 推迟至 11 月，全曲线重定价"),
        (dt.date(2026, 10, 1), "②", "② 10/1 Bloomberg：10/14 投资人说明日会、路演最快 11/9 当周启动"),
        (dt.date(2026, 10, 2), "③", "③ 10/2 11/15 节点由 0.230 跌至 0.115"),
        (dt.date(2026, 10, 14), "④", "④ 10/14 Reuters：说明会已举行（晚间报道；不据此推断价格变化的因果）"),
    ]
    for day, mark, _ in events:
        ax.axvline(day, color="#888888", lw=0.9, ls=":")
        ax.annotate(mark, (day, 0.985), ha="center", va="top",
                    fontsize=11, color="#444444")

    ax.set_ylim(0, 1.0)
    ax.yaxis.set_major_formatter(pct)
    ax.set_ylabel("Yes 报价（隐含概率）")
    ax.set_title(f"历史价格（UTC每日末次观测；末日未完结；截止美东 {AS_OF}）")
    ax.legend(fontsize=8.5, ncols=5, loc="upper center", bbox_to_anchor=(0.5, -0.13))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=3))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    ax.tick_params(axis="x", labelsize=8.5)
    ax.text(0.0, -0.27, "\n".join(t for _, _, t in events),
            transform=ax.transAxes, fontsize=7.8, color="#444444", va="top")
    save(fig, "fig2_history.png")


# --- 图 3：模型 vs 市场的 CDF ---------------------------------------------
def fig_cdf():
    base = read_csv("baseline_model_vs_market.csv")
    cal = read_csv("final_model_vs_market.csv")
    live = [r for r in cal if r["closed"] == "False" and int(r["end_date"][:4]) == 2026]

    def xy(rows):
        d = [dt.datetime.fromisoformat(r["end_date"]) for r in rows]
        return d, [float(r["market_prob"]) for r in rows], [float(r["model_prob"]) for r in rows]

    by_label = {r["deadline"]: r for r in base}
    db, mb, pb = xy([by_label[r["deadline"]] for r in live])
    _, _, pc = xy([r for r in cal if r["closed"] == "False" and int(r["end_date"][:4]) == 2026])

    fig, ax = plt.subplots(figsize=(8.4, 4.0))
    ax.plot(db, mb, "o-", color=C_MKT, lw=2.0, ms=5, label="市场（Polymarket 报价）")
    ax.plot(db, pb, "s--", color=C_BASE, lw=1.6, ms=4.5, label="未校准基线模型")
    ax.plot(db, pc, "^-", color=C_CAL, lw=2.0, ms=5, label="校准后模型")
    ax.axvline(dt.datetime(2026, 12, 15), color=C_ACC, lw=1.4, ls=":")
    ax.annotate("本题结算日 12/15", (dt.datetime(2026, 12, 15), 0.30),
                fontsize=8, color=C_ACC, ha="right", rotation=90, va="bottom")
    ax.axvline(dt.datetime(2026, 11, 26), color="#888888", lw=1.0, ls=":")
    ax.annotate("感恩节 11/26", (dt.datetime(2026, 11, 26), 0.02),
                fontsize=8, color="#666666", ha="right", rotation=90, va="bottom")
    ax.set_ylim(0, 1.0)
    ax.yaxis.set_major_formatter(pct)
    ax.set_ylabel("P(在该日期前完成 IPO)")
    ax.set_title("累计挂牌概率：市场、证据模型与市场拟合诊断（12/15留出）")
    ax.legend(fontsize=8.5, loc="upper left")
    fig.autofmt_xdate(rotation=0)
    save(fig, "fig3_model_vs_market.png")


# --- 图 4：分桶概率 --------------------------------------------------------
def fig_buckets():
    rows = read_csv("bucket_implied.csv")
    labels = [r["bucket"] for r in rows]
    mkt = [float(r["market_prob"]) for r in rows]
    mod = [float(r["model_prob"]) for r in rows]

    fig, ax = plt.subplots(figsize=(8.4, 3.8))
    xs = np.arange(len(rows))
    w = 0.38
    ax.bar(xs - w / 2, mkt, w, color=C_MKT, label="市场隐含（期限结构差分）")
    ax.bar(xs + w / 2, mod, w, color=C_CAL, label="校准后模型")
    for x, m, d in zip(xs, mkt, mod):
        ax.annotate(f"{m * 100:.1f}", (x - w / 2, m), xytext=(0, 3),
                    textcoords="offset points", ha="center", fontsize=7.8, color="#333333")
        ax.annotate(f"{d * 100:.1f}", (x + w / 2, d), xytext=(0, 3),
                    textcoords="offset points", ha="center", fontsize=7.8, color="#333333")
    ax.set_xticks(xs)
    ax.set_xticklabels(labels, fontsize=8.5)
    ax.yaxis.set_major_formatter(pct)
    ax.set_ylabel("挂牌概率")
    ax.set_title("挂牌时间窗口的隐含概率：市场 vs 模型")
    ax.legend(fontsize=8.5)
    save(fig, "fig4_buckets.png")


# --- 图 5：蒙特卡洛挂牌日分布 ---------------------------------------------
def fig_mc():
    rows = read_csv("listing_date_hist.csv")
    dates = [dt.date.fromisoformat(r["date"]) for r in rows]
    probs = np.array([float(r["prob"]) for r in rows])
    fc = load_json("forecast.json")

    fig, ax = plt.subplots(figsize=(8.4, 3.8))
    ax.bar(dates, probs, width=0.9, color=C_CAL, alpha=0.85)
    ax.axvline(THANKSGIVING, color="#888888", lw=1.2, ls="--")
    ax.axvline(TARGET, color=C_ACC, lw=1.6, ls="-")
    med_model = dt.date.fromisoformat(fc["model"]["median_listing_date"])
    med_mkt_text = fc["market_implied_median_listing_date"]["p50"]
    med_mkt = dt.date.fromisoformat(med_mkt_text) if med_mkt_text else None
    ax.axvline(med_model, color=C_CAL, lw=1.2, ls=":")
    if med_mkt:
        ax.axvline(med_mkt, color=C_MKT, lw=1.2, ls=":")
    ax.set_ylim(0, probs.max() * 1.34)
    ax.text(.02, .95, f"模型条件中位：{med_model:%m/%d}\n市场无条件中位：{med_mkt.strftime('%m/%d') if med_mkt else '未达到50%'}\n两者条件口径不同",
            transform=ax.transAxes, fontsize=8, color="#444444", va="top")
    ax.annotate("本题结算日\n12/15", (TARGET, probs.max() * 1.24), fontsize=8.5,
                color=C_ACC, ha="left", va="top")
    ax.set_ylabel("单日挂牌概率")
    ax.yaxis.set_major_formatter(pct)
    stall = fc["model"]["calibrated_params"]["stall_prob"]
    ax.set_title(f"市场拟合诊断的挂牌日分布（40万路径；失败概率参数 {stall:.0%}）")
    ax.set_xlim(dt.date(2026, 11, 8), max(dates)+dt.timedelta(days=2))
    fig.autofmt_xdate(rotation=0)
    save(fig, "fig5_listing_distribution.png")


# --- 图 6：敏感性热力图 ----------------------------------------------------
def fig_sensitivity():
    rows = read_csv("sensitivity_surface.csv")
    stalls = sorted({float(r["stall_prob"]) for r in rows})
    highs = sorted({float(r["gap_high"]) for r in rows})
    gm = float(rows[0]["gap_mode"])
    grid = np.full((len(highs), len(stalls)), np.nan)
    for r in rows:
        grid[highs.index(float(r["gap_high"])), stalls.index(float(r["stall_prob"]))] = (
            float(r["loss"])
        )

    fig, ax = plt.subplots(figsize=(8.0, 4.0))
    xg, yg = np.meshgrid(stalls, highs)
    im = ax.pcolormesh(xg, yg, grid, cmap="viridis_r", shading="nearest")
    i, j = np.unravel_index(np.nanargmin(grid), grid.shape)
    ax.scatter([stalls[j]], [highs[i]], marker="*", s=200, color="white",
               edgecolor="black", zorder=5)
    ax.annotate(
        f"切片网格最低点\nstall_prob={stalls[j]:.2f}\ngap_high={int(highs[i])} 天",
        (stalls[j], highs[i]), xytext=(10, 16), textcoords="offset points",
        fontsize=8.2, color="#111111",
    )
    ax.set_xlabel("stall_prob（交易流产概率）")
    ax.set_ylabel("路演启动右尾 gap_high（日历日）")
    ax.set_title(f"参数敏感性：加权平方误差（gap_mode={int(gm)} 天切片，颜色越深越差）")
    ax.grid(False)
    fig.colorbar(im, ax=ax, label="loss（加权平方误差）")
    save(fig, "fig6_sensitivity.png")


def main() -> None:
    fig_term_structure()
    fig_history()
    fig_cdf()
    fig_buckets()
    fig_mc()
    fig_sensitivity()


if __name__ == "__main__":
    main()
