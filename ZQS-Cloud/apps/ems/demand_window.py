"""需量窗口積分控制：把「現在超過上限」改成「這個 15 分鐘窗口的平均會不會超」。

台電計的是 15 分鐘**平均**功率。引擎在窗口第 10 分鐘看到 745 kW 才放電，
前 9 分鐘已經累積的用電救不回來；真實廠房的負載是階躍的（一台冰水主機
啟動就是 200 kW），瞬時比較會在上線後第一個被客戶抓到。這個模組回答的是：

    已累積 kWh(電表) + 剩餘時間 × 預測 native 功率 ＝ 窗口預期平均
    預期平均 > 上限 → 現在起放電 (預期平均 − 上限) × 0.25 / 剩餘小時

「已累積」用的是**電表**讀值（含電池動作），因為台電收的就是電表的平均；
「剩餘」用 native（不含電池）預測，因為那是沒有電池時會發生的事、也就是
電池接下來要對付的量。兩者混用會出事：累積量若用 native，已經在放電的
電池會被要求「補回」它其實已經削掉的能量，設定點愈追愈高直到放空。

四個邊界是真的會出事的地方，各自有處理：

* **窗口尾端** ``remaining_h → 0`` 會讓放電功率爆到無限大。低於
  ``MIN_REMAINING_H``（60 秒）就維持上一輪設定值到窗口結束，不重算。
* **窗口切換**：狀態歸零，但由呼叫端沿用上一個設定點到新窗口第一次
  評估，不在邊界瞬間歸零再重建——那會在每個 15 分鐘邊界產生一次功率突跳。
* **保險餘裕**由預測誤差的 P90 決定（W1），沒有誤差統計時退回契約 95%。
* **涵蓋率**：窗口內遙測涵蓋 < 0.8 就標記為不可信，呼叫端退回瞬時邏輯
  ——硬算一個沒有資料支撐的積分比不算還糟。

獨立成模組是因為 W6 的邊緣側要用同一套算術。這裡沒有任何 Django 以外的
相依，純函式的部分（:func:`required_discharge_kw`）連 ORM 都不碰。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from apps.ems.forecast import HOURS_PER_INTERVAL, INTERVAL, align_to_interval
from apps.telemetry.energy import integrate_kwh

#: 剩餘時間少於此就不重算（小時）。60 秒：再短的話一次取樣雜訊就會被
#: 除成幾百 kW 的設定點跳動。
MIN_REMAINING_H = 60 / 3600
#: 窗口內遙測涵蓋率低於此視為不可信。與 EnergyInterval 的「不完整區間」
#: 門檻一致，讀報表的人看到的是同一個數字。
MIN_COVERAGE = 0.8
#: 誤差統計至少要有這麼多樣本才拿來當餘裕：半天的 15 分鐘點。
MIN_STATS_SAMPLES = 48


@dataclass(slots=True)
class WindowState:
    window_start: dt.datetime
    #: 窗口起點到 moment 的電表累積 kWh（含電池動作，即台電會計的量）。
    accumulated_kwh: float
    #: 0–1，窗口起點到 moment 之間被遙測涵蓋的比例。
    coverage: float
    is_trustworthy: bool
    elapsed_h: float
    #: 最後一筆 native 功率（kW），預測缺席時的退路。
    last_native_kw: float | None = None
    reason: str = ""

    @property
    def remaining_h(self) -> float:
        return max(0.0, HOURS_PER_INTERVAL - self.elapsed_h)


def window_bounds(moment: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    start = align_to_interval(moment)
    return start, start + INTERVAL


def native_series(
    site, start: dt.datetime, end: dt.datetime, *, include_battery: bool = True
) -> tuple[list[tuple[dt.datetime, float]], tuple[dt.datetime, float] | None]:
    """功率（kW）時間序列。``include_battery=True`` 為 native（電表 + 電池放電），
    ``False`` 為電表本身。

    分別讀電表與電池的功率樣本，對齊成一條序列。回傳 ``(points, seed)``，
    ``seed`` 是窗口前最後一筆，讓前值保持能從窗口起點就算起。
    """
    from apps.ems.models import AssetRole, EnergyAsset
    from apps.telemetry.models import TelemetrySample

    roles = [AssetRole.GRID_METER, AssetRole.BATTERY] if include_battery else [AssetRole.GRID_METER]
    assets = list(
        EnergyAsset.objects.filter(site_id=getattr(site, "id", site), is_active=True, include_in_balance=True)
        .exclude(power_metric="")
        .filter(role__in=roles)
    )
    if not any(a.role == AssetRole.GRID_METER for a in assets):
        return [], None

    # 每個資產自己的序列（前值保持），再在聯集的時間點上相加。
    per_asset: list[list[tuple[dt.datetime, float]]] = []
    seeds: list[float | None] = []
    for asset in assets:
        rows = list(
            TelemetrySample.objects.filter(
                device_id=asset.device_id, metric_key=asset.power_metric,
                ts__gte=start - dt.timedelta(hours=1), ts__lt=end,
            ).order_by("ts").values_list("ts", "value")
        )
        # 電表正值 = 購電、電池正值 = 放電，兩者相加就是場域自身需量。
        series = [(ts, asset.normalize_power(value)) for ts, value in rows if value is not None]
        before = [p for p in series if p[0] < start]
        seeds.append(before[-1][1] if before else None)
        per_asset.append([p for p in series if p[0] >= start])

    if not per_asset:
        return [], None
    stamps = sorted({ts for series in per_asset for ts, _ in series})
    combined: list[tuple[dt.datetime, float]] = []
    cursors = [0] * len(per_asset)
    current = list(seeds)
    for ts in stamps:
        for i, series in enumerate(per_asset):
            while cursors[i] < len(series) and series[cursors[i]][0] <= ts:
                current[i] = series[cursors[i]][1]
                cursors[i] += 1
        if current[0] is None:  # 電表還沒有值，native 無意義
            continue
        combined.append((ts, sum(v for v in current if v is not None)))
    seed = None
    if seeds[0] is not None:
        seed = (start, sum(v for v in seeds if v is not None))
    return combined, seed


def window_state(site, moment: dt.datetime) -> WindowState:
    """目前 15 分鐘窗口到 ``moment`` 為止累積了多少 native 用電。"""
    start, _end = window_bounds(moment)
    elapsed_h = (moment - start).total_seconds() / 3600.0
    if elapsed_h <= 0:
        return WindowState(start, 0.0, 1.0, True, 0.0, None, "window just opened")

    points, seed = native_series(site, start, moment, include_battery=False)
    if not points and seed is None:
        return WindowState(start, 0.0, 0.0, False, elapsed_h, None, "no telemetry in window")
    result = integrate_kwh(points, start, moment, seed=seed)
    kwh = result.kwh or 0.0
    coverage = result.coverage or 0.0
    native_points, native_seed = native_series(site, start, moment, include_battery=True)
    last = native_points[-1][1] if native_points else (native_seed[1] if native_seed else None)
    trustworthy = coverage >= MIN_COVERAGE
    reason = "" if trustworthy else f"coverage {coverage:.2f} below {MIN_COVERAGE}"
    return WindowState(start, kwh, coverage, trustworthy, elapsed_h, last, reason)


def required_discharge_kw(
    state: WindowState,
    ceiling_kw: float,
    predicted_kw: float,
    moment: dt.datetime,
    *,
    previous_kw: float | None = None,
) -> float | None:
    """為了讓本窗口電表平均 ≤ ceiling，現在必須放多少 kW。負值代表有充電餘裕。

    ``predicted_kw`` 是剩餘時間的 **native** 功率（沒有電池時的需量）。

    ``None`` 表示「維持上一輪」：剩餘時間已短於 ``MIN_REMAINING_H``，
    重算只會把雜訊放大成設定點跳動。呼叫端拿到 ``None`` 就沿用
    ``previous_kw``（也一併回傳，方便呼叫端不必自己記）。
    """
    remaining_h = state.remaining_h
    if remaining_h < MIN_REMAINING_H:
        return previous_kw
    predicted_rest_kwh = remaining_h * max(predicted_kw, 0.0)
    projected_avg_kw = (state.accumulated_kwh + predicted_rest_kwh) / HOURS_PER_INTERVAL
    # 超出的能量必須在剩餘時間內全部削掉；有餘裕則回負值供回充判斷。
    excess_kwh = (projected_avg_kw - ceiling_kw) * HOURS_PER_INTERVAL
    return excess_kwh / remaining_h


#: 每個場域最後一次窗口決策：(window_start, kW)。引擎單一行程，放記憶體即可；
#: 重啟後第一輪會退回瞬時邏輯，那是可接受的。
_last_decision: dict = {}


def remember(site_id, window_start: dt.datetime, kw: float, *, memory: dict | None = None) -> None:
    (_last_decision if memory is None else memory)[site_id] = (window_start, kw)


def previous_for(
    site_id, window_start: dt.datetime, *, memory: dict | None = None
) -> tuple[float | None, bool]:
    """上一輪的放電 kW，以及它是否屬於同一個窗口。

    跨窗口時仍回傳上一個值：新窗口的第一次評估沿用它，避免邊界瞬間
    歸零再重建的功率突跳；``same_window=False`` 讓呼叫端知道狀態已歸零。
    """
    entry = (_last_decision if memory is None else memory).get(site_id)
    if entry is None:
        return None, False
    return entry[1], entry[0] == window_start


#: 誤差統計每小時重算一次就夠（它回看 14 天）；每 20 秒掃一次是自找麻煩。
_MARGIN_CACHE: dict = {}
MARGIN_TTL = dt.timedelta(hours=1)


def safety_margin_kw(site_id, *, stats=None) -> tuple[float, str]:
    """上限要往下留多少。預測誤差 P90 優先；沒有統計就不另外留。

    「沒有統計退回契約 95%」已經由 demand_cap 的上限退路鏈
    （``contract × DEFAULT_DEMAND_MARGIN``）實現；這裡再扣一次會變成打兩次折。
    使用者自己填的目標也不再打折——那是客戶的數字，不是引擎的。
    """
    if stats is None:
        from django.utils.timezone import now

        from apps.ems.forecast import forecast_error_stats

        cached = _MARGIN_CACHE.get(site_id)
        if cached is not None and now() - cached[0] < MARGIN_TTL:
            return cached[1]
        try:
            stats = forecast_error_stats(site_id, days=14)
        except Exception:  # noqa: BLE001 - 統計失敗不能讓調度掛掉
            stats = None
        result = safety_margin_kw(site_id, stats=stats) if stats is not None else (0.0, "no forecast error stats")
        _MARGIN_CACHE[site_id] = (now(), result)
        return result
    if stats is not None and stats.samples >= MIN_STATS_SAMPLES and stats.p90_abs_kw is not None:
        return float(stats.p90_abs_kw), f"forecast P90 error {stats.p90_abs_kw:.1f} kW ({stats.samples} samples)"
    return 0.0, "no forecast error stats; ceiling chain already holds the 95% contract margin"
