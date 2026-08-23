"""負載與 PV 預測：從 ``EnergyInterval`` 歷史推出未來 N 個 15 分鐘區間。

整個系統在這之前沒有「未來」——每個策略都是反應式的。需量窗口積分控制
（W2）、SOC 日內規劃、策略疊加全都需要「接下來這一小時大概會用多少」，
這個模組就只回答這一題，而且刻意用最簡單、看得懂、算得快的方法：

* **同 weekday、同時段、最近 K 週的中位數**。廠房負載的規律性主要來自
  班表，而班表是以週為週期；中位數而不是平均，一次停機日不會把整週拉低。
* **漂移係數**：最近三天「實測 ÷ 同一套方法的事後預測」，抓住換季、產線
  增減這類緩慢的整體位移。夾在 0.5–1.5 之間，避免一天的異常把整個預測
  乘爆。
* **週末與工作日分開**（weekday 相同即分開），假日目前視為該 weekday——
  沒有假日表，與其猜不如承認。

沒有機器學習、沒有外部氣象 API，只留一個 ``weather_factor`` 可注入。
產線環境多一個依賴就是多一次離線安裝的麻煩；先把「有預測」這件事做出來，
再用回測（W3）決定值不值得加複雜度。

降級行為寫死在這裡，策略端不必猜：歷史不足兩週的區間回
``confidence="unknown"`` 且 ``load_kw=None``，**不會 raise**——預測掛了
不能讓調度跟著掛。
"""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass

from django.db import transaction

from apps.ems.models import EnergyInterval, ForecastConfidence, LoadForecast

INTERVAL = dt.timedelta(minutes=15)
HOURS_PER_INTERVAL = 0.25
#: 取最近幾週的同時段樣本。4 週夠平滑又不會把一個月前的換季狀態拖進來。
HISTORY_WEEKS = 4
#: 至少要有這麼多週的樣本才敢說「estimated」；少於此回 unknown。
MIN_WEEKS = 2
#: 漂移係數用最近幾天校正，與夾限範圍。
DRIFT_DAYS = 3
DRIFT_MIN, DRIFT_MAX = 0.5, 1.5


@dataclass(slots=True)
class ForecastPoint:
    starts_at: dt.datetime      # UTC，區間起點
    load_kw: float | None       # 該區間平均功率
    pv_kw: float | None
    confidence: str             # measured | estimated | unknown
    samples: int = 0


@dataclass(slots=True)
class ErrorStats:
    """最近一段期間的預測誤差分布（以「實測 − 預測」的 kW 計）。

    ``p90_abs_kw`` 是 W2 的保險餘裕來源：窗口控制把上限再往下留這麼多，
    十次裡有九次預測偏低都還壓得住。``mape`` 供驗收與回測比較。
    """

    site_id: object
    days: int
    samples: int
    mape: float | None
    p50_abs_kw: float | None
    p90_abs_kw: float | None
    bias_kw: float | None       # 正值 = 實測高於預測（預測偏低）


def align_to_interval(moment: dt.datetime) -> dt.datetime:
    """對齊到 15 分鐘邊界（UTC）。台電需量窗口就是這個邊界。"""
    moment = moment.astimezone(dt.timezone.utc)
    minute = (moment.minute // 15) * 15
    return moment.replace(minute=minute, second=0, microsecond=0)


def _history(site_id, start: dt.datetime, end: dt.datetime) -> dict[dt.datetime, EnergyInterval]:
    rows = EnergyInterval.objects.filter(
        site_id=site_id, interval_start__gte=start, interval_start__lt=end, interval_seconds=900
    ).only("interval_start", "load_kwh", "pv_kwh", "coverage")
    return {row.interval_start: row for row in rows}


def _native_load_kw(row: EnergyInterval) -> float:
    """區間的平均負載功率。``load_kwh`` 本來就是場域自身的用電（電池動作已
    在能源平衡裡分離），所以不需要再還原電池。"""
    return row.load_kwh / HOURS_PER_INTERVAL


def _same_slot_samples(
    history: dict[dt.datetime, EnergyInterval], target: dt.datetime, weeks: int
) -> list[EnergyInterval]:
    """``target`` 往前每 7 天一筆的同時段樣本。週期用 7 天而不是「同 weekday
    的本地時間」，夏令時間地區會差一小時——台灣沒有，但介面不該只對台灣對。"""
    out = []
    for k in range(1, weeks + 1):
        row = history.get(target - dt.timedelta(days=7 * k))
        if row is not None and row.coverage >= 0.5:
            out.append(row)
    return out


def _median_estimate(samples: list[EnergyInterval], field: str) -> float | None:
    values = [getattr(row, field) / HOURS_PER_INTERVAL for row in samples]
    if not values:
        return None
    return float(statistics.median(values))


def _drift(history: dict[dt.datetime, EnergyInterval], moment: dt.datetime, field: str) -> float:
    """最近 DRIFT_DAYS 天「實測 ÷ 同法預測」的比值，中位數後夾限。

    用的是與正式預測完全相同的估計式（同時段、往前 K 週中位數），所以它
    量到的是「這套方法最近整體偏高還是偏低」，而不是某一小時的雜訊。
    """
    ratios: list[float] = []
    cursor = align_to_interval(moment) - dt.timedelta(days=DRIFT_DAYS)
    end = align_to_interval(moment)
    while cursor < end:
        actual = history.get(cursor)
        if actual is not None and actual.coverage >= 0.5:
            estimate = _median_estimate(_same_slot_samples(history, cursor, HISTORY_WEEKS), field)
            measured = getattr(actual, field) / HOURS_PER_INTERVAL
            if estimate and estimate > 1e-6 and measured > 1e-6:
                ratios.append(measured / estimate)
        cursor += INTERVAL
    if len(ratios) < 8:  # 少於兩小時的樣本不值得校正
        return 1.0
    return max(DRIFT_MIN, min(DRIFT_MAX, float(statistics.median(ratios))))


def forecast_site(
    site_id,
    moment: dt.datetime,
    horizon_hours: int = 24,
    *,
    weather_factor: float = 1.0,
    record: bool = True,
) -> list[ForecastPoint]:
    """未來 ``horizon_hours`` 的負載與 PV 預測，15 分鐘解析度。

    歷史不足時回傳 ``confidence="unknown"`` 的點而不是拋例外——策略端必須
    能自己決定「沒有預測時怎麼辦」，而不是整個調度掛掉。

    ``record=True`` 時把每個點連同 ``made_at`` 寫進 ``LoadForecast``，之後
    :func:`forecast_error_stats` 才有東西可以回算。
    """
    made_at = moment.astimezone(dt.timezone.utc)
    first = align_to_interval(moment)
    horizon = max(1, int(horizon_hours * 4))
    targets = [first + INTERVAL * i for i in range(horizon)]

    # 一次把需要的歷史撈齊：往前 K 週 + 漂移用的幾天，一個查詢。
    history = _history(
        site_id,
        first - dt.timedelta(days=7 * HISTORY_WEEKS + 1),
        first,
    )
    load_drift = _drift(history, moment, "load_kwh")
    pv_drift = _drift(history, moment, "pv_kwh")

    points: list[ForecastPoint] = []
    for target in targets:
        samples = _same_slot_samples(history, target, HISTORY_WEEKS)
        if len(samples) < MIN_WEEKS:
            points.append(ForecastPoint(target, None, None, ForecastConfidence.UNKNOWN, len(samples)))
            continue
        load = _median_estimate(samples, "load_kwh")
        pv = _median_estimate(samples, "pv_kwh")
        points.append(ForecastPoint(
            target,
            None if load is None else round(load * load_drift, 3),
            None if pv is None else round(pv * pv_drift * weather_factor, 3),
            ForecastConfidence.ESTIMATED,
            len(samples),
        ))

    if record:
        _record(site_id, made_at, points)
    return points


def _record(site_id, made_at: dt.datetime, points: list[ForecastPoint]) -> None:
    rows = [
        LoadForecast(
            site_id=site_id, starts_at=p.starts_at, made_at=made_at,
            horizon_minutes=int((p.starts_at - align_to_interval(made_at)).total_seconds() // 60),
            load_kw=p.load_kw, pv_kw=p.pv_kw, confidence=p.confidence, samples=p.samples,
        )
        for p in points
    ]
    with transaction.atomic():
        LoadForecast.objects.bulk_create(rows, ignore_conflicts=True)


def forecast_error_stats(site_id, days: int = 14, *, max_horizon_minutes: int = 60) -> ErrorStats:
    """回算最近 ``days`` 天的預測誤差分布。W2 的保險餘裕由這裡來。

    只看 ``made_at`` 到 ``starts_at`` 不超過 ``max_horizon_minutes`` 的預測，
    因為窗口控制用的是「接下來一小時」的預測；把 24 小時前的預測混進來會把
    餘裕撐得太大，白白少削需量。每個區間只取最接近的一次預測。
    """
    now = dt.datetime.now(dt.timezone.utc)
    since = now - dt.timedelta(days=days)
    forecasts = (
        LoadForecast.objects.filter(
            site_id=site_id, starts_at__gte=since, starts_at__lt=align_to_interval(now),
            confidence=ForecastConfidence.ESTIMATED, horizon_minutes__lte=max_horizon_minutes,
            load_kw__isnull=False,
        )
        .order_by("starts_at", "-made_at")
        .values_list("starts_at", "made_at", "load_kw")
    )
    latest_per_slot: dict[dt.datetime, float] = {}
    for starts_at, _made_at, load_kw in forecasts:
        latest_per_slot.setdefault(starts_at, load_kw)
    if not latest_per_slot:
        return ErrorStats(site_id, days, 0, None, None, None, None)

    actual = _history(site_id, since, align_to_interval(now))
    errors: list[float] = []
    apes: list[float] = []
    for starts_at, predicted in latest_per_slot.items():
        row = actual.get(starts_at)
        if row is None or row.coverage < 0.8:
            continue
        measured = _native_load_kw(row)
        errors.append(measured - predicted)
        if measured > 1e-6:
            apes.append(abs(measured - predicted) / measured)
    if not errors:
        return ErrorStats(site_id, days, 0, None, None, None, None)

    absolute = sorted(abs(e) for e in errors)
    p50 = absolute[len(absolute) // 2]
    p90 = absolute[min(len(absolute) - 1, int(len(absolute) * 0.9))]
    return ErrorStats(
        site_id=site_id, days=days, samples=len(errors),
        mape=round(float(statistics.mean(apes)), 4) if apes else None,
        p50_abs_kw=round(p50, 3), p90_abs_kw=round(p90, 3),
        bias_kw=round(float(statistics.mean(errors)), 3),
    )


def backtest(site_id, start: dt.datetime, end: dt.datetime) -> ErrorStats:
    """對已知的歷史區間做事後預測，算 MAPE——驗收與回歸用。

    每個目標區間都只用它**之前**的歷史（同法、同 K 週、同漂移），所以
    結果等同於「當時真的做了預測」，不是用未來資料套未來。不寫資料庫。
    """
    start = align_to_interval(start)
    end = align_to_interval(end)
    history = _history(site_id, start - dt.timedelta(days=7 * HISTORY_WEEKS + DRIFT_DAYS + 1), end)
    errors: list[float] = []
    apes: list[float] = []
    cursor = start
    while cursor < end:
        actual = history.get(cursor)
        if actual is not None and actual.coverage >= 0.8:
            samples = _same_slot_samples(history, cursor, HISTORY_WEEKS)
            if len(samples) >= MIN_WEEKS:
                # _drift 只讀 cursor 之前的時段，不必另外過濾。
                drift = _drift(history, cursor, "load_kwh")
                estimate = _median_estimate(samples, "load_kwh")
                if estimate is not None:
                    predicted = estimate * drift
                    measured = _native_load_kw(actual)
                    errors.append(measured - predicted)
                    if measured > 1e-6:
                        apes.append(abs(measured - predicted) / measured)
        cursor += INTERVAL
    if not errors:
        return ErrorStats(site_id, int((end - start).days), 0, None, None, None, None)
    absolute = sorted(abs(e) for e in errors)
    return ErrorStats(
        site_id=site_id, days=int((end - start).days), samples=len(errors),
        mape=round(float(statistics.mean(apes)), 4) if apes else None,
        p50_abs_kw=round(absolute[len(absolute) // 2], 3),
        p90_abs_kw=round(absolute[min(len(absolute) - 1, int(len(absolute) * 0.9))], 3),
        bias_kw=round(float(statistics.mean(errors)), 3),
    )


def recorded_native_kw(site_id, starts_at: dt.datetime) -> float | None:
    """最近一次 record_forecasts 對這個時槽的 native 需量估計（load − pv），kW。

    給需量窗口控制用：一筆索引查詢，而不是重算整個預測。沒有紀錄、或
    信心為 unknown 時回 ``None``，呼叫端自己退回瞬時值。
    """
    from apps.ems.models import ForecastConfidence, LoadForecast

    row = (
        LoadForecast.objects.filter(site_id=site_id, starts_at=align_to_interval(starts_at))
        .exclude(confidence=ForecastConfidence.UNKNOWN)
        .order_by("-made_at")
        .values_list("load_kw", "pv_kw")
        .first()
    )
    if row is None or row[0] is None:
        return None
    return float(row[0]) - float(row[1] or 0.0)
