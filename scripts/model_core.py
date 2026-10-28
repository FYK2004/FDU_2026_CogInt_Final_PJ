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
确认」时调整流程。因此本引擎对**每个剩余阶段的历时**建模：公开报道核实后，由
研究者更新锚点与参数，再重新模拟；当前尚未实现自动在线贝叶斯更新。

默认参数是证据与主观流程先验；校准参数另由市场拟合。
默认模型与市场也可能共享新闻，因此融合只解释为意见池，不声称统计独立。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, replace
from typing import Tuple

import numpy as np
from exchange_calendar import exchange_holidays

# --- 已经由公开证据锁定的「门」 -------------------------------------------
# 2026-10-14：Bloomberg 报道的旧金山总部 Pre-IPO 投资人说明日会
INVESTOR_DAY = dt.date(2026, 10, 14)
# 2026-11-26：美国感恩节（报道称「力争感恩节前挂牌」）
THANKSGIVING = dt.date(2026, 11, 26)
# 兼容旧版本的字段；不再用作失败路径的挂牌日
MAX_HORIZON = dt.date(2027, 6, 30)


@dataclass(frozen=True)
class Params:
    """模型参数。三元素元组均为三角分布的 (下界, 众数, 上界)，单位：日历日。"""

    investor_day: dt.date = INVESTOR_DAY
    thanksgiving: dt.date = THANKSGIVING
    # 投资人说明日会 -> 正式路演启动。
    # 依据：Bloomberg 报道「路演最快 11 月 9 日当周启动」，2026-10-14 + 26 天 = 11-09，
    # 因此下界与众数均取26；这是时程情景假设，不是公司保证。
    gap: Tuple[float, float, float] = (26.0, 26.0, 55.0)
    # 正式路演时长：超大型项目簿记约 2 周。
    roadshow: Tuple[float, float, float] = (8.0, 12.0, 18.0)
    # 定价 -> 首个交易日。
    listing_lag: Tuple[float, float, float] = (1.0, 1.0, 3.0)
    # 「延期支线」：有 slip_share 的概率，交易在路演结束后仍未定价，整体再顺延
    # 一段（重新接触投资人 / 补充材料 / 等待窗口），可能延至年底或跨年。
    slip_share: float = 0.0
    slip: Tuple[float, float, float] = (14.0, 28.0, 45.0)
    # 吸收态失败概率，是主观先验；普通延期由gap/slip另行建模。
    stall_prob: float = 0.12
    # 保留旧接口字段；不再把流产路径硬塞到这个日期。
    horizon: dt.date = MAX_HORIZON
    label: str = "baseline"

    def __post_init__(self):
        import math
        for name in ("gap", "roadshow", "listing_lag", "slip"):
            lo, mode, hi = getattr(self, name)
            if not all(math.isfinite(v) for v in (lo, mode, hi)) or not 0 <= lo <= mode <= hi or lo == hi:
                raise ValueError(f"Invalid triangular distribution {name}")
        for name in ("stall_prob", "slip_share"):
            if not 0 <= getattr(self, name) <= 1:
                raise ValueError(f"{name} must be in [0, 1]")

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
    """Roll forward over weekends and US equity exchange full-day closures."""
    off = np.asarray(offsets, dtype=np.int64).copy()
    first = (investor_day + dt.timedelta(days=int(off.min()))).year
    last = (investor_day + dt.timedelta(days=int(off.max()))).year
    holidays = set().union(*(exchange_holidays(y) for y in range(first, last+1)))
    holidays.add(thanksgiving)
    closed_days = [(day-investor_day).days for day in holidays]
    while True:
        off = _snap_to_monday(off, investor_day)
        closed = np.isin(off, closed_days)
        if not closed.any():
            return off
        off += closed.astype(np.int64)


class SimResult:
    """一次模拟的容器：保存每条路径的挂牌日偏移量，并提供 CDF 等查询。"""

    __slots__ = ("params", "n_paths", "seed", "offset", "stall")

    def __init__(self, params: Params, n_paths: int, seed: int,
                 offset: np.ndarray, stall: np.ndarray) -> None:
        self.params = params
        self.n_paths = n_paths
        self.seed = seed
        self.offset = offset      # 相对 investor_day 的潜在挂牌日偏移
        self.stall = stall        # True = 吸收态失败，不对应任何挂牌日

    def _off(self, day: dt.date) -> int:
        return (day - self.params.investor_day).days

    def cdf(self, deadline: dt.date) -> float:
        """P(在 deadline 当日或之前完成挂牌)。"""
        return float(((~self.stall) & (self.offset <= self._off(deadline))).mean())

    def cdf_before(self, day: dt.date) -> float:
        """P(严格早于 day 完成挂牌)。"""
        return self.cdf(day - dt.timedelta(days=1))

    def bucket(self, lo: dt.date, hi: dt.date | None = None) -> float:
        """Half-open P(lo <= T < hi); hi=None includes absorbing failures."""
        off = self.offset
        if hi is None:
            return float((self.stall | (off >= self._off(lo))).mean())
        if hi <= lo:
            raise ValueError("bucket requires lo < hi")
        return float(((~self.stall) & (off >= self._off(lo)) & (off < self._off(hi))).mean())

    @property
    def p_stall(self) -> float:
        return float(self.stall.mean())

    def date_at(self, q: float) -> dt.date | None:
        """日期分位数，以未进入吸收态失败为条件。"""
        if not 0 <= q <= 1:
            raise ValueError("q must be in [0, 1]")
        live = np.sort(self.offset[~self.stall])
        if not live.size:
            return None
        idx = int(np.clip(round(q * (live.size - 1)), 0, live.size - 1))
        return self.params.investor_day + dt.timedelta(days=int(live[idx]))

    def quantiles(self, probs=(0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)):
        return {f"p{int(p * 100)}": day.isoformat() if (day := self.date_at(p)) else None for p in probs}


def simulate(params: Params, n_paths: int = 400_000,
             seed: int = 20261007) -> SimResult:
    """跑一次蒙特卡洛。"""
    if not isinstance(n_paths, int) or n_paths <= 0:
        raise ValueError("n_paths must be a positive integer")
    rng = np.random.default_rng(seed)
    stall = rng.random(n_paths) < params.stall_prob
    # numpy 的 triangular 签名是 (left, mode, right)，与我们的 (下界, 众数, 上界) 一致
    gap = np.rint(rng.triangular(*params.gap, size=n_paths)).astype(np.int64)
    # 路演启动遇到休市则顺延，再叠加路演时长。
    gap = _adjust_offsets(gap, params.investor_day, params.thanksgiving)
    road = np.rint(rng.triangular(*params.roadshow, size=n_paths)).astype(np.int64)
    lag = np.rint(rng.triangular(*params.listing_lag, size=n_paths)).astype(np.int64)
    off = gap + road + lag
    # 延期支线
    # Draw even at share=0 so comparisons use common random numbers.
    slip_mask = rng.random(n_paths) < params.slip_share
    slip = np.rint(rng.triangular(*params.slip, size=n_paths)).astype(np.int64)
    off = off + np.where(slip_mask, slip, 0)
    off = _adjust_offsets(off, params.investor_day, params.thanksgiving)
    # Failures are excluded by cdf/bucket; never assign a fictitious listing date.
    return SimResult(params, n_paths, seed, off, stall)


# --- 与市场融合 ------------------------------------------------------------

def logit(p: float) -> float:
    if not np.isfinite(p) or not 0 <= p <= 1:
        raise ValueError("probability must be in [0, 1]")
    p = min(max(p, 1e-9), 1 - 1e-9)
    return float(np.log(p / (1.0 - p)))


def inv_logit(z: float) -> float:
    return float(1.0 / (1.0 + np.exp(-z))) if z >= 0 else float(np.exp(z)/(1+np.exp(z)))


def blend_logodds(p_model: float, p_market: float, w_model: float) -> float:
    """对数几率意见池：不要求、也不声称两个来源统计独立。

    w_model = 给模型的权重，0.5 表示等权，0 表示完全采信市场。
    """
    if not 0 <= w_model <= 1:
        raise ValueError("model weight must be in [0, 1]")
    logit(p_model), logit(p_market)
    if w_model in (0, 1):
        return p_market if w_model == 0 else p_model
    return inv_logit(w_model * logit(p_model) + (1.0 - w_model) * logit(p_market))
