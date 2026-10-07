"""里程碑门控蒙特卡洛引擎（milestone-gated Monte-Carlo engine）。

用途
----
估计「Anthropic 是否会在日期 D 之前完成正式 IPO 并开始交易」的概率。

设计思想
--------
大型科技公司的 IPO 不是无记忆事件。它必须依次通过一组**可观测的门**：

    秘密递交 S-1  ->  公开招股书 / 投资人说明日会  ->  正式路演  ->  定价  ->  首个交易日

如果直接对「某天是否上市」设一个常数日概率（Poisson / 几何分布），得到的生存曲线
是指数形状，与 Polymarket 期限结构上明显的 S 形不符，也无法在「某道门被公开证据
确认」时条件化更新。因此本引擎对**每个剩余阶段的历时**建模：只要某个门的日期被
公开报道锁定（例如 2026-10-14 的 Pre-IPO 投资人说明日会），模型立即条件化在新信息上。

参数来自公开报道（见 docs/项目初步方案.md 第 3 节与 data/raw/articles/），
**不拟合市场价格**，以保证模型可作为与市场互相独立的「第二意见」参与融合。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, replace
from typing import Tuple

import numpy as np

# --- 已经由公开证据锁定的「门」 -------------------------------------------
# 2026-10-14：Bloomberg 报道的旧金山总部 Pre-IPO 投资人说明日会
INVESTOR_DAY = dt.date(2026, 10, 14)
# 2026-11-26：美国感恩节（报道称「力争感恩节前挂牌」）
THANKSGIVING = dt.date(2026, 11, 26)
# 报价曲线之外的兜底日期：代表 2026 年没有完成挂牌
MAX_HORIZON = dt.date(2027, 6, 30)


@dataclass(frozen=True)
class Params:
    """模型参数。三元素元组均为三角分布的 (下界, 众数, 上界)，单位：日历日。"""

    investor_day: dt.date = INVESTOR_DAY
    thanksgiving: dt.date = THANKSGIVING
    # 投资人说明日会 -> 正式路演启动。
    # 依据：Bloomberg 报道「路演最快 11 月 9 日当周启动」，2026-10-14 + 26 天 = 11-09，
    # 故众数取 26；右尾承载整周顺延（11/16、11/23 …）与流程重启。
    gap: Tuple[float, float, float] = (16.0, 26.0, 55.0)
    # 正式路演时长：超大型项目簿记约 2 周。
    roadshow: Tuple[float, float, float] = (8.0, 12.0, 18.0)
    # 定价 -> 首个交易日。
    listing_lag: Tuple[float, float, float] = (1.0, 1.0, 3.0)
    # 「延期支线」：有 slip_share 的概率，交易在路演结束后仍未定价，整体再顺延
    # 一段（重新接触投资人 / 补充材料 / 等待窗口），从而落在 12 月上中旬。
    # 没有这一支线时，时间线的硬右边界会让 P(12/15) 与 P(12/31) 相等，
    # 而市场的 12/31 节点比 12/15 节点高 4pp。
    slip_share: float = 0.0
    slip: Tuple[float, float, float] = (14.0, 28.0, 45.0)
    # 交易流产 / 被上市公司收购 / 估值谈崩 —— 对本题一律结算为 No。
    stall_prob: float = 0.12
    # 超过这个日期视为「2026 年内没有挂牌」。
    horizon: dt.date = MAX_HORIZON
    label: str = "baseline"

    def with_(self, **kw) -> "Params":
        return replace(self, **kw)


def _snap_to_monday(offsets: np.ndarray, investor_day: dt.date) -> np.ndarray:
    """把落在周末的日期推到下一个周一。"""
    base_wd = investor_day.weekday()  # 0=周一 … 6=周日
    off = offsets.astype(np.int64)
    for _ in range(3):
        wd = (base_wd + off) % 7
        # 周六 -> 周一（+2），周日 -> 周一（+1）
        push = np.where(wd == 5, 2, np.where(wd == 6, 1, 0))
        if not push.any():
            break
        off = off + push
    return off


def _adjust_offsets(offsets: np.ndarray, investor_day: dt.date,
                    thanksgiving: dt.date) -> np.ndarray:
    """把挂牌日推到工作日，并避开感恩节当天。"""
    off = _snap_to_monday(offsets, investor_day)
    tg = (thanksgiving - investor_day).days
    off = np.where(off == tg, tg + 1, off)
    return off


class SimResult:
    """一次模拟的容器：保存每条路径的挂牌日偏移量，并提供 CDF 等查询。"""

    __slots__ = ("params", "n_paths", "seed", "offset", "stall")

    def __init__(self, params: Params, n_paths: int, seed: int,
                 offset: np.ndarray, stall: np.ndarray) -> None:
        self.params = params
        self.n_paths = n_paths
        self.seed = seed
        self.offset = offset      # 相对 investor_day 的偏移；流产路径被推到 horizon
        self.stall = stall        # True = 2026 年内不挂牌

    def _off(self, day: dt.date) -> int:
        return (day - self.params.investor_day).days

    def cdf(self, deadline: dt.date) -> float:
        """P(在 deadline 当日或之前完成挂牌)。"""
        return float((self.offset <= self._off(deadline)).mean())

    def cdf_before(self, day: dt.date) -> float:
        """P(严格早于 day 完成挂牌)。"""
        return float((self.offset <= self._off(day) - 1).mean())

    def bucket(self, lo: dt.date, hi: dt.date) -> float:
        """P(lo <= 挂牌日 <= hi)。"""
        off = self.offset
        return float(((off >= self._off(lo)) & (off <= self._off(hi))).mean())

    @property
    def p_stall(self) -> float:
        return float(self.stall.mean())

    def date_at(self, q: float) -> dt.date:
        live = np.sort(self.offset[~self.stall])
        idx = int(np.clip(round(q * (live.size - 1)), 0, live.size - 1))
        return self.params.investor_day + dt.timedelta(days=int(live[idx]))

    def quantiles(self, probs=(0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)):
        return {f"p{int(p * 100)}": self.date_at(p).isoformat() for p in probs}


def simulate(params: Params, n_paths: int = 400_000,
             seed: int = 20261007) -> SimResult:
    """跑一次蒙特卡洛。"""
    rng = np.random.default_rng(seed)
    stall = rng.random(n_paths) < params.stall_prob
    # numpy 的 triangular 签名是 (left, mode, right)，与我们的 (下界, 众数, 上界) 一致
    gap = np.rint(rng.triangular(*params.gap, size=n_paths)).astype(np.int64)
    # 路演不会在周末启动：把启动日推到周一，再叠加路演时长
    gap = _snap_to_monday(gap, params.investor_day)
    road = np.rint(rng.triangular(*params.roadshow, size=n_paths)).astype(np.int64)
    lag = np.rint(rng.triangular(*params.listing_lag, size=n_paths)).astype(np.int64)
    off = gap + road + lag
    # 延期支线
    if params.slip_share > 0:
        slip_mask = rng.random(n_paths) < params.slip_share
        slip = np.rint(rng.triangular(*params.slip, size=n_paths)).astype(np.int64)
        off = off + np.where(slip_mask, slip, 0)
    off = _adjust_offsets(off, params.investor_day, params.thanksgiving)
    horizon_off = (params.horizon - params.investor_day).days
    off = np.where(stall, horizon_off, off)
    return SimResult(params, n_paths, seed, off, stall)


# --- 与市场融合 ------------------------------------------------------------

def logit(p: float) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return float(np.log(p / (1.0 - p)))


def inv_logit(z: float) -> float:
    return float(1.0 / (1.0 + np.exp(-z)))


def blend_logodds(p_model: float, p_market: float, w_model: float) -> float:
    """对数几率（log-odds）加权平均：融合两个来源的独立概率。

    w_model = 给模型的权重，0.5 表示等权，0 表示完全采信市场。
    """
    return inv_logit(w_model * logit(p_model) + (1.0 - w_model) * logit(p_market))
