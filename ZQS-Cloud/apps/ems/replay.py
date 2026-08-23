"""回放注入點：讓策略程式碼在離線回測時讀合成資料，而不是 LatestSample。

回測（W3）要證明的是「同一份策略程式碼」在歷史負載上會怎麼做；如果回測
另外寫一份簡化邏輯，證明的就只是那份簡化邏輯。所以策略不改，改的是它
讀資料的三個入口：瞬時功率平衡、電池 SOC、需量窗口狀態。這裡用
``ContextVar`` 而不是 mock.patch——注入點明確寫在程式裡，grep 得到，
而且多執行緒下不會互相汙染。

正式調度路徑 ``REPLAY.get()`` 永遠是 ``None``，零成本、零行為差異。
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass(slots=True)
class ReplayContext:
    #: 場域的瞬時功率平衡（與 api._current_flow 同結構）。
    flow: Callable[[], dict]
    #: 電池 SOC（%）；None = 未知。
    soc: Callable[[], float | None]
    #: 需量窗口狀態；None = 讓 demand_cap 走瞬時邏輯。
    window_state: Callable[[dt.datetime], object | None] | None = None
    #: 剩餘時間的預測功率（kW）；None = 用瞬時值。
    forecast_kw: Callable[[dt.datetime], float | None] | None = None
    #: 需量餘裕（kW）；None = 不另外留。
    margin_kw: float | None = None
    #: 循環成本（每 kWh）；None = 照正式路徑讀資產。
    cycle_cost_per_kwh: float | None = None
    #: 回放期間 demand_window 的「上一輪設定點」記憶，與正式路徑隔離。
    memory: dict = field(default_factory=dict)


REPLAY: ContextVar[ReplayContext | None] = ContextVar("ems_replay", default=None)


@contextmanager
def replaying(context: ReplayContext):
    token = REPLAY.set(context)
    try:
        yield context
    finally:
        REPLAY.reset(token)
