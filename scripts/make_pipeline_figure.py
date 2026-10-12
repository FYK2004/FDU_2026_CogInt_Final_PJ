"""生成项目整体流程示意图（figures/fig0_pipeline.png）。

运行（需要 matplotlib）：
    D:\\miniconda\\python.exe -X utf8 scripts\\make_pipeline_figure.py

这张图只描述流程结构，不读取数据、不需要联网；
其中引用的数字（84.67% / 80.96% / 79.4% 等）与 data/processed/forecast.json 一致，
改模型后若数字变动，请同步更新本脚本里的 CARDS 文本。
"""

from __future__ import annotations

import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import to_rgb  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle  # noqa: E402

plt.rcParams.update(
    {
        "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
        "axes.unicode_minus": False,
        "figure.dpi": 170,
        "savefig.dpi": 170,
    }
)

FIGS = "figures"
os.makedirs(FIGS, exist_ok=True)

INK = "#2f2f2f"
MUTED = "#6b7480"
ARROW = "#9aa4ad"

# 四个阶段及其主色（与 make_figures.py 的配色体系一致：深蓝 / 青绿 / 砖红 / 琥珀）
STAGES = [
    ("① 数据采集", "#1f4e79"),
    ("② 数据处理", "#2f7f6f"),
    ("③ 建模与校准", "#b0473f"),
    ("④ 结果输出", "#c9851c"),
]

# 每个阶段三张卡片：(标题, [正文行])
CARDS = [
    [
        (
            "collect_polymarket.py",
            [
                "Gamma：事件 + 10 个子市场",
                "CLOB：小时级 Yes 价历史",
                "Kalshi：对照市场 1 个",
                "→ data/raw/（history/gamma/clob）",
            ],
        ),
        (
            "collect_news.py",
            [
                "Google News RSS 多轮检索",
                "→ news_*.xml（4 份）",
                "→ news_index.csv（286 条）",
            ],
        ),
        (
            "fetch_articles.py",
            [
                "抓取关键报道正文（15 篇留存）",
                "html_to_text.py：HTML → TXT",
                "→ articles/ + _manifest.csv",
            ],
        ),
    ],
    [
        (
            "analyze_term_structure.py",
            [
                "期限结构 + 隐含危险率",
                "→ term_structure.csv",
            ],
        ),
        (
            "宽表重建",
            [
                "各节点日度价格对齐",
                "→ history_wide.csv",
            ],
        ),
        (
            "跳变检测",
            [
                "识别市场重定价事件",
                "→ jump_events.csv（图 2）",
            ],
        ),
    ],
    [
        (
            "model_core.py",
            [
                "门控蒙特卡洛引擎",
                "路演启动 → 挂牌 → 流产",
                "40 万路径 / 种子 20261007",
            ],
        ),
        (
            "milestone_model.py",
            [
                "未校准基线（只用公开报道参数）",
                "→ 84.67%（中位挂牌 11/30）",
            ],
        ),
        (
            "calibrate_model.py",
            [
                "三阶段网格校准 → 80.96%",
                "log-odds 融合（权重 0.35）",
                "→ forecast.json",
            ],
        ),
    ],
    [
        (
            "最终预测",
            [
                "79.4%（80% 区间 78.3–81.4%）",
                "判定 Yes，edge +0.89pp",
            ],
        ),
        (
            "核心增量：条件概率",
            [
                "感恩节（11/26）前未挂牌 →",
                "模型 64.3% vs 市场 55.8%",
            ],
        ),
        (
            "图表与报告",
            [
                "make_figures.py → fig1–fig6",
                "build_report_docx.py → 期末报告",
            ],
        ),
    ],
]

# 底部关键时间点：(x 位置百分比, 日期, 说明, 是否红色强调)
MILESTONES = [
    (11.5, "10/14", "投资人说明日会", False),
    (37.2, "11/09", "路演最快启动", False),
    (62.8, "11/26", "感恩节（最关键判决点）", True),
    (88.5, "12/15", "本题结算日", True),
]


def _blend(color, target, factor):
    """把 color 朝 target 混 factor（0~1）。"""
    src = to_rgb(color)
    dst = to_rgb(target)
    return tuple(s + (d - s) * factor for s, d in zip(src, dst))


def tint(color, factor=0.90):
    return _blend(color, "#ffffff", factor)


def shade(color, factor=0.15):
    return _blend(color, "#000000", factor)


def card(ax, x, y, w, h, title, lines, color, fs_title=8.0, fs_body=7.0):
    """一张卡片：浅色底 + 左侧色条 + 加粗标题 + 正文行。"""
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0,rounding_size=1.0",
            linewidth=0.9,
            edgecolor=tint(color, 0.55),
            facecolor=tint(color),
            zorder=2,
        )
    )
    # 左侧色条：叠一个小矩形，圆角处被卡片底裁掉也无所谓，视觉上仍是「色带」
    ax.add_patch(
        Rectangle((x + 0.35, y + 0.9), 0.5, h - 1.8, facecolor=color,
                  edgecolor="none", zorder=3)
    )
    ax.text(
        x + 1.7, y + h - 1.9, title,
        fontsize=fs_title, fontweight="bold", color=shade(color),
        va="top", ha="left", zorder=4,
    )
    ax.text(
        x + 1.7, y + h - 1.9 - fs_title * 0.52, "\n".join(lines),
        fontsize=fs_body, color=INK, va="top", ha="left",
        linespacing=1.55, zorder=4,
    )


def stage_header(ax, x, y, w, h, label, color):
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0,rounding_size=1.2",
            linewidth=0,
            facecolor=color,
            zorder=3,
        )
    )
    ax.text(
        x + w / 2, y + h / 2, label,
        fontsize=10.5, fontweight="bold", color="white",
        va="center", ha="center", zorder=4,
    )


def main() -> None:
    fig, ax = plt.subplots(figsize=(13.2, 7.4))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    # ---- 标题 ----
    ax.text(
        50, 98.4, "项目整体流程：从市场报价到最终预测",
        fontsize=15.5, fontweight="bold", color="#1b1b1b",
        va="center", ha="center",
    )
    ax.text(
        50, 95.4,
        "数据截止 2026-10-07 ｜ 随机种子 20261007 ｜ 建模与出图全程离线可复现",
        fontsize=8.6, color=MUTED, va="center", ha="center",
    )

    # ---- 四列布局 ----
    col_w = 22.0
    gap = 3.67
    x_left = [0.5 + i * (col_w + gap) for i in range(4)]
    header_y, header_h = 88.5, 5.0
    card_top, card_h, card_gap = 85.5, 14.0, 6.0

    for i, (label, color) in enumerate(STAGES):
        x = x_left[i]
        stage_header(ax, x, header_y, col_w, header_h, label, color)
        for j, (title, lines) in enumerate(CARDS[i]):
            y = card_top - card_h - j * (card_h + card_gap)
            card(ax, x, y, col_w, card_h, title, lines, color)

    # ---- 阶段之间的箭头 ----
    arrow_y = 58.5
    for i in range(3):
        x0 = x_left[i] + col_w + 0.6
        x1 = x_left[i + 1] - 0.6
        ax.add_patch(
            FancyArrowPatch(
                (x0, arrow_y), (x1, arrow_y),
                arrowstyle="-|>", mutation_scale=15,
                color=ARROW, lw=2.0, shrinkA=0, shrinkB=0, zorder=5,
            )
        )

    # ---- 底部判决点时间线 ----
    line_y = 19.0
    ax.plot([6.0, 95.0], [line_y, line_y], color="#c3cad1", lw=1.6,
            solid_capstyle="round", zorder=2)
    for x, day, desc, hot in MILESTONES:
        c = "#b0473f" if hot else "#1f4e79"
        ax.plot([x], [line_y], marker="o", ms=9, mfc="white", mec=c, mew=2.0,
                zorder=4)
        ax.text(x, line_y + 3.4, day, fontsize=10.5, fontweight="bold",
                color=c, va="center", ha="center", zorder=4)
        ax.text(x, line_y - 3.2, desc, fontsize=7.6, color=MUTED,
                va="top", ha="center", zorder=4, linespacing=1.5)

    # ---- 判决点回路：刷新数据 → 重跑模型 ----
    loop_y = 7.6
    ax.plot(
        [95.0, 97.6, 97.6, 3.0, 3.0],
        [line_y, line_y, loop_y, loop_y, 29.5],
        color=ARROW, lw=1.5, ls=(0, (4, 3)), zorder=1,
        solid_capstyle="round",
    )
    ax.add_patch(
        FancyArrowPatch(
            (3.0, 29.5), (3.0, 30.9),
            arrowstyle="-|>", mutation_scale=13,
            color=ARROW, lw=1.5, shrinkA=0, shrinkB=0, zorder=1,
        )
    )
    ax.text(
        50, loop_y,
        "判决点（10/14 · 11/09 · 11/26）过后：刷新数据 → 重跑模型 → 更新预测",
        fontsize=8.0, color=MUTED, va="center", ha="center",
        bbox=dict(boxstyle="round,pad=0.45", facecolor="white",
                  edgecolor="none"),
        zorder=3,
    )

    path = os.path.join(FIGS, "fig0_pipeline.png")
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
