"""CSV / Excel 匯入與資料稽核。

這一層的價值不亞於模型本身。P1 階段最常見的失敗模式不是「模型不準」，
而是「資料根本對不齊」：取樣位置沒正規化、頭尾切除量沒記錄、C0 沒測、
LOD 當成 0。這些問題如果沒在匯入時攔下來，會一路傳到最佳化建議。

寬鬆輸入、嚴格檢核
------------------
接受長格式（long format）表格，一列 = 一個取樣點的一個元素。欄位別名做
模糊比對（大小寫、底線、常見中文欄名），但**單位與物理一致性一律嚴格檢查**，
不合格就擋下並說清楚哪一列、為什麼。

左設限（LOD）的三種輸入寫法都支援
---------------------------------
  1. value_ppm = "<0.05"        字串帶小於號
  2. value_ppm = 0.05 且 censored = 1
  3. value_ppm <= lod_ppm       數值小於等於檢測極限
三者都會被標記為 censored=True 並保留 lod_ppm，交由擬合層以 Tobit 處理。
"""

from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

import pandas as pd

from ..logging_setup import get_logger
from .models import Batch, ElementSpec, Measurement

log = get_logger(__name__)

TEMPLATE_COLUMNS = [
    "batch_id", "run_date", "ingot_len_mm", "zone_len_mm", "speed_mm_hr",
    "temp_c", "n_passes", "atmosphere", "head_crop_frac", "analysis_method",
    "x_mm", "x_norm", "element", "value_ppm", "lod_ppm", "censored", "c0_ppm",
]

# 欄位別名。key 為正規名，value 為可接受的寫法（比對前會先正規化）。
_ALIASES: dict[str, tuple[str, ...]] = {
    "batch_id": ("batchid", "batch", "lot", "lotid", "批次", "批號", "批次編號"),
    "run_date": ("date", "rundate", "日期", "實驗日期"),
    "ingot_len_mm": ("ingotlength", "ingotlen", "llength", "錠長", "錠長mm", "l"),
    "zone_len_mm": ("zonelength", "zonelen", "熔區長度", "熔區長"),
    "speed_mm_hr": ("speed", "v", "zonespeed", "rate", "移動速率", "速率", "熔區移動速率"),
    "temp_c": ("temp", "temperature", "t", "溫度", "熔區溫度"),
    "n_passes": ("passes", "npass", "pass", "純化次數", "次數"),
    "atmosphere": ("atm", "gas", "氣氛"),
    "head_crop_frac": ("headcrop", "頭端切除", "頭端切除比例"),
    "analysis_method": ("method", "分析方法"),
    "x_mm": ("position", "positionmm", "x", "距頭端", "取樣位置mm"),
    "x_norm": ("xnorm", "xoverl", "positionfrac", "歸一化位置", "位置分率"),
    "element": ("el", "impurity", "元素", "雜質元素"),
    "value_ppm": ("value", "ppm", "conc", "concentration", "濃度", "含量"),
    "lod_ppm": ("lod", "dl", "detectionlimit", "檢測極限"),
    "censored": ("iscensored", "belowlod", "低於檢測極限"),
    "c0_ppm": ("c0", "feedppm", "initialppm", "進料濃度", "初始濃度"),
}

_NUM_RE = re.compile(r"^\s*([<>]?)\s*([0-9]*\.?[0-9]+(?:[eE][-+]?\d+)?)\s*$")


def _num_or(raw, default):
    """把儲存格轉成 float。空白 / NaN 回傳 default；0 會被正確保留為 0.0。"""
    if raw is None:
        return default
    if isinstance(raw, bool):
        raise ValueError(f"預期數值，收到布林值 {raw!r}")
    if isinstance(raw, (int, float)):
        return default if math.isnan(float(raw)) else float(raw)
    txt = str(raw).strip()
    if txt in {"", "nan", "NaN", "None", "-", "—"}:
        return default
    return float(txt)


@dataclass
class ImportReport:
    """匯入結果。errors 非空時**不會寫入資料庫**。"""

    ok: bool = True
    batches: int = 0
    measurements: int = 0
    censored: int = 0
    elements: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    batch_ids: list[str] = field(default_factory=list)

    def error(self, msg: str) -> None:
        self.errors.append(msg)
        self.ok = False

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def to_dict(self) -> dict:
        return asdict(self)


def _norm_key(s: str) -> str:
    return re.sub(r"[\s_\-()/]", "", str(s)).lower()


def _resolve_columns(df: pd.DataFrame) -> dict[str, str]:
    """把實際欄名映射到正規名。回傳 {正規名: 實際欄名}。"""
    found: dict[str, str] = {}
    normalized = {_norm_key(c): c for c in df.columns}
    for canon, aliases in _ALIASES.items():
        candidates = (canon,) + aliases
        for cand in candidates:
            key = _norm_key(cand)
            if key in normalized:
                found[canon] = normalized[key]
                break
    return found


def _parse_value(raw) -> tuple[float, bool]:
    """解析濃度欄。回傳 (數值, 是否為左設限)。

    支援 "<0.05"、"< 0.05"、0.05、"0.05"。無法解析時丟 ValueError。
    """
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        if math.isnan(float(raw)):
            raise ValueError("空值")
        return float(raw), False
    m = _NUM_RE.match(str(raw))
    if not m:
        raise ValueError(f"無法解析為濃度：{raw!r}")
    sign, num = m.group(1), float(m.group(2))
    if sign == ">":
        # 右設限（「大於某值」）在偏析純化的量測裡不該出現，而且本專案的
        # Tobit likelihood 只實作了左設限。靜默當成精確值會讓 k_eff 被低估，
        # 所以直接擋下並說清楚。
        raise ValueError(f"不支援右設限寫法 {raw!r}（大於號）。"
                         f"本工具只處理低於檢測極限的左設限資料。")
    return num, sign == "<"


def _as_bool(raw) -> bool:
    """解析布林欄位。

    注意數值型別要先處理：pandas 讀進來的 0/1 欄位會是 float64，
    ``str(1.0)`` 是 ``"1.0"`` 而不是 ``"1"``，用字串比對會靜默失效——
    使用者明明填了 censored=1，設限旗標卻沒生效。
    """
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return False
    if isinstance(raw, (int, float)):
        return False if math.isnan(float(raw)) else float(raw) != 0.0
    return str(raw).strip().lower() in {"1", "1.0", "true", "yes", "y", "t", "是"}


def import_dataframe(df: pd.DataFrame, repo=None) -> ImportReport:
    """稽核並（在無錯誤時）寫入資料庫。

    Args:
        df: 長格式表格。
        repo: BatchRepository；None 表示只稽核不寫入（dry run）。

    Returns:
        ImportReport
    """
    rep = ImportReport()
    cols = _resolve_columns(df)

    required = ["batch_id", "element", "value_ppm"]
    missing = [c for c in required if c not in cols]
    if missing:
        rep.error(f"缺少必要欄位：{', '.join(missing)}。"
                  f"可用欄位範本見 docs/03-data-spec.html。")
        return rep
    if "x_norm" not in cols and "x_mm" not in cols:
        rep.error("必須提供取樣位置：x_norm（歸一化）或 x_mm + ingot_len_mm。")
        return rep

    def col(name: str, row) -> object:
        return row[cols[name]] if name in cols else None

    batches: dict[str, Batch] = {}
    measurements: dict[str, list[Measurement]] = {}
    c0_map: dict[tuple[str, str], float] = {}
    seen_points: set[tuple[str, str, float]] = set()
    param_conflicts: dict[str, set] = {}

    for idx, row in df.iterrows():
        line = int(idx) + 2                      # 對應試算表列號（含標題列）
        bid = str(col("batch_id", row)).strip()
        if not bid or bid.lower() == "nan":
            rep.error(f"第 {line} 列：batch_id 為空")
            continue

        # ── 批次層級參數 ────────────────────────────────────────
        # 注意：不能寫成 float(col(...) or 500.0)。0 在 Python 裡是 falsy，
        # 「錠長 = 0」這種明顯錯誤的資料會被靜默換成預設值 500，後面的
        # ingot <= 0 檢查就永遠看不到它。一律用 _num_or 明確區分「空白」與「0」。
        try:
            ingot = _num_or(col("ingot_len_mm", row), 500.0)
            zone = _num_or(col("zone_len_mm", row), 50.0)
            speed = _num_or(col("speed_mm_hr", row), None)
            temp = _num_or(col("temp_c", row), None)
            npass = int(_num_or(col("n_passes", row), 1.0))
            crop = _num_or(col("head_crop_frac", row), 0.0)
        except (TypeError, ValueError) as exc:
            rep.error(f"第 {line} 列：製程參數無法解析（{exc}）")
            continue

        if speed is None:
            rep.error(f"第 {line} 列：缺少熔區移動速率 speed_mm_hr")
            continue
        if temp is None:
            rep.error(f"第 {line} 列：缺少熔區溫度 temp_c。溫度是 (v,T) → k_eff "
                      f"映射的自變數之一，不可留空；若確實沒記錄，請在匯入前"
                      f"與客戶確認該批的實際設定值。")
            continue
        # 銦熔點 156.6 °C。低於熔點的熔區溫度在物理上不成立，通常是欄位對錯
        # 或單位是 K 而不是 °C。
        if not 100.0 <= temp <= 900.0:
            rep.error(f"第 {line} 列：熔區溫度 {temp} °C 超出合理範圍 [100, 900]。"
                      f"銦熔點為 156.6 °C；請確認單位是攝氏而非凱氏，且欄位沒有對錯。")
            continue

        if ingot <= 0:
            rep.error(f"第 {line} 列：錠長必須為正數，收到 {ingot}")
            continue
        if not 0 < zone < ingot:
            rep.error(f"第 {line} 列：熔區長度 {zone} mm 必須在 (0, 錠長 {ingot} mm) 之間")
            continue
        if speed <= 0:
            rep.error(f"第 {line} 列：熔區移動速率必須為正數，收到 {speed}")
            continue
        if npass < 1:
            rep.error(f"第 {line} 列：純化次數必須 >= 1，收到 {npass}")
            continue
        if not 0.0 <= crop < 0.5:
            rep.error(f"第 {line} 列：頭端切除比例需在 [0, 0.5)，收到 {crop}")
            continue

        b = Batch(
            batch_id=bid,
            run_date=str(col("run_date", row) or "")[:10],
            ingot_len_mm=ingot, zone_len_mm=zone, speed_mm_hr=speed,
            temp_c=temp, n_passes=npass,
            atmosphere=str(col("atmosphere", row) or "Ar"),
            head_crop_frac=crop,
            analysis_method=str(col("analysis_method", row) or "GDMS"),
        )
        sig = (round(ingot, 6), round(zone, 6), round(speed, 6),
               round(temp, 6), npass, round(crop, 6))
        param_conflicts.setdefault(bid, set()).add(sig)
        batches.setdefault(bid, b)

        # ── 取樣位置 ────────────────────────────────────────────
        if "x_norm" in cols and not _is_blank(col("x_norm", row)):
            try:
                xn = float(col("x_norm", row))
            except (TypeError, ValueError):
                rep.error(f"第 {line} 列：x_norm 無法解析")
                continue
        else:
            try:
                xn = float(col("x_mm", row)) / ingot
            except (TypeError, ValueError):
                rep.error(f"第 {line} 列：x_mm 無法解析且未提供 x_norm")
                continue
        if not 0.0 <= xn <= 1.0:
            rep.error(f"第 {line} 列：歸一化位置 {xn:.4f} 超出 [0,1]。"
                      f"常見原因是 x_mm 與錠長單位不一致。")
            continue

        element = str(col("element", row)).strip()
        if not element or element.lower() == "nan":
            rep.error(f"第 {line} 列：element 為空")
            continue

        key = (bid, element, round(xn, 6))
        if key in seen_points:
            rep.error(f"第 {line} 列：批次 {bid} 的元素 {element} 在位置 "
                      f"{xn:.4f} 重複出現")
            continue
        seen_points.add(key)

        # ── 濃度與 LOD ──────────────────────────────────────────
        try:
            val, cen_from_str = _parse_value(col("value_ppm", row))
        except ValueError as exc:
            rep.error(f"第 {line} 列：{exc}")
            continue
        if val < 0:
            rep.error(f"第 {line} 列：濃度不可為負（{val}）")
            continue

        lod_raw = col("lod_ppm", row)
        lod = 0.0
        if not _is_blank(lod_raw):
            try:
                lod = float(lod_raw)
            except (TypeError, ValueError):
                rep.warn(f"第 {line} 列：lod_ppm 無法解析，視為 0")
        censored = cen_from_str or _as_bool(col("censored", row)) or (lod > 0 and val <= lod)
        if censored and lod <= 0:
            lod = val if val > 0 else 1e-3
            rep.warn(f"第 {line} 列：標記為低於檢測極限但未提供 lod_ppm，"
                     f"以測值 {lod:g} ppm 作為 LOD。建議補上實際 LOD。")
        if censored and val <= 0:
            val = lod

        measurements.setdefault(bid, []).append(
            Measurement(batch_id=bid, element=element, x_norm=xn, value_ppm=val,
                        lod_ppm=lod, censored=censored)
        )
        if censored:
            rep.censored += 1

        c0_raw = col("c0_ppm", row)
        if not _is_blank(c0_raw):
            try:
                c0v = float(c0_raw)
                if c0v > 0:
                    c0_map[(bid, element)] = c0v
            except (TypeError, ValueError):
                rep.warn(f"第 {line} 列：c0_ppm 無法解析，已忽略")

    # ── 批次層級一致性檢查 ──────────────────────────────────────
    for bid, sigs in param_conflicts.items():
        if len(sigs) > 1:
            rep.error(f"批次 {bid} 的製程參數在不同列不一致（{len(sigs)} 組不同值）。"
                      f"同一批次的 L / l / v / T / pass 必須相同。")

    for bid, rows in measurements.items():
        by_el: dict[str, list[Measurement]] = {}
        for m in rows:
            by_el.setdefault(m.element, []).append(m)
        for el, pts in by_el.items():
            if len(pts) < 3:
                rep.warn(f"批次 {bid} 的 {el} 只有 {len(pts)} 個取樣點，"
                         f"擬合 k_eff 至少需要 3 點、建議 6 點以上。")
            if (bid, el) not in c0_map:
                rep.warn(f"批次 {bid} 的 {el} 未提供進料濃度 C0，"
                         f"擬合時將以曲線質量守恆推估（會標示為推估值）。")
            xs = sorted(p.x_norm for p in pts)
            if xs and xs[0] > 0.25:
                rep.warn(f"批次 {bid} 的 {el} 最靠頭端的取樣點在 x/L={xs[0]:.2f}，"
                         f"缺少頭端資料會讓 k_eff 的不確定度顯著變大。")

    if not batches:
        rep.error("沒有任何可用的批次資料")

    rep.batches = len(batches)
    rep.measurements = sum(len(v) for v in measurements.values())
    rep.elements = sorted({m.element for rows in measurements.values() for m in rows})
    rep.batch_ids = sorted(batches)

    if not rep.ok or repo is None:
        return rep

    # ── 寫入 ────────────────────────────────────────────────────
    for bid, b in batches.items():
        repo.upsert_batch(b)
        repo.replace_measurements(bid, measurements.get(bid, []))
        specs = []
        for el in sorted({m.element for m in measurements.get(bid, [])}):
            c0v = c0_map.get((bid, el))
            specs.append(ElementSpec(batch_id=bid, element=el,
                                     c0_ppm=c0v if c0v else _estimate_c0(measurements[bid], el),
                                     c0_measured=c0v is not None))
        repo.replace_element_specs(bid, specs)
    log.info("匯入完成：%d 批次、%d 量測點（%d 為設限值）",
             rep.batches, rep.measurements, rep.censored)
    return rep


def _estimate_c0(rows: list[Measurement], element: str) -> float:
    """C0 未提供時的推估：以取樣點的位置加權平均近似全錠平均濃度。

    偏析純化不會消滅雜質，只是重新分布，所以全錠平均 ≈ C0。取樣點通常
    偏向頭端且不含尾端尖峰，這個推估會**低估** C0，故一律標記 c0_measured=False
    並在 UI 上顯示警示。真正的解法是請客戶量 C0。
    """
    pts = sorted([m for m in rows if m.element == element], key=lambda m: m.x_norm)
    if not pts:
        return 1.0
    xs = [p.x_norm for p in pts]
    ys = [p.value_ppm for p in pts]
    if len(pts) == 1:
        return max(ys[0], 1e-6)
    # 梯形積分後除以涵蓋長度
    area = sum((ys[i] + ys[i + 1]) / 2 * (xs[i + 1] - xs[i]) for i in range(len(xs) - 1))
    span = xs[-1] - xs[0]
    return max(area / span if span > 0 else ys[0], 1e-6)


def _is_blank(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    return str(v).strip() in {"", "nan", "None", "NaN"}


def import_csv(source: str | Path | bytes, repo=None) -> ImportReport:
    """從 CSV 檔案路徑或位元組內容匯入。"""
    if isinstance(source, bytes):
        try:
            df = pd.read_csv(io.BytesIO(source))
        except UnicodeDecodeError:
            df = pd.read_csv(io.BytesIO(source), encoding="big5")
    else:
        path = Path(source)
        if path.suffix.lower() in {".xlsx", ".xls"}:
            df = pd.read_excel(path)
        else:
            try:
                df = pd.read_csv(path)
            except UnicodeDecodeError:
                df = pd.read_csv(path, encoding="big5")
    return import_dataframe(df, repo)


def template_csv() -> str:
    """回傳可下載的空白範本（含一列範例）。"""
    example = [
        "IN-2501,2025-01-14,500,50,2.0,175,8,Ar,0.03,GDMS,25,,Cu,0.42,0.05,0,8.5",
        "IN-2501,2025-01-14,500,50,2.0,175,8,Ar,0.03,GDMS,75,,Cu,<0.05,0.05,1,8.5",
    ]
    return ",".join(TEMPLATE_COLUMNS) + "\n" + "\n".join(example) + "\n"
