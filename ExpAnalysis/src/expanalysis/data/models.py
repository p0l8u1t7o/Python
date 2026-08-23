"""資料模型（純 dataclass，與資料庫與 API 解耦）。

單位約定（全專案一致，違反者在匯入層就會被擋下）：
    ingot_len_mm    錠長 L               [mm]
    zone_len_mm     熔區長度 l           [mm]
    speed_mm_hr     熔區移動速率 v       [mm/hr]
    temp_c          熔區溫度 T           [°C]
    value_ppm       雜質濃度             [ppm, 質量比]
    x_norm          取樣位置 x/L         [無因次, 0=頭端]
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Batch:
    """一個純化批次的製程條件。"""

    batch_id: str
    run_date: str = ""                  # ISO 8601 日期字串
    ingot_len_mm: float = 500.0
    zone_len_mm: float = 50.0
    speed_mm_hr: float = 2.0
    temp_c: float = 180.0
    n_passes: int = 1
    atmosphere: str = "Ar"              # Ar / Vacuum / N2 / Air
    head_crop_frac: float = 0.0         # 頭端固定切除比例
    feed_purity_note: str = ""
    analysis_method: str = "GDMS"       # GDMS / ICP-MS
    operator: str = ""
    notes: str = ""

    @property
    def zone_len_frac(self) -> float:
        """l / L。物理模型真正需要的是這個無因次量。"""
        if self.ingot_len_mm <= 0:
            raise ValueError(f"批次 {self.batch_id} 的錠長無效：{self.ingot_len_mm}")
        return self.zone_len_mm / self.ingot_len_mm

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["zone_len_frac"] = self.zone_len_frac
        return d


@dataclass
class Measurement:
    """單一取樣點、單一元素的分析結果。

    censored 為 True 表示測值低於檢測極限（LOD）。這是**左設限資料**，
    真值落在 [0, lod_ppm] 區間內，不是一個數字。當成 0 會低估 k、
    當成 LOD 會高估 k——兩種都是錯的。擬合層以 Tobit likelihood 處理。
    """

    batch_id: str
    element: str
    x_norm: float
    value_ppm: float                    # censored 時此欄存 LOD 值供顯示用
    lod_ppm: float = 0.0
    censored: bool = False
    pass_index: int | None = None       # 若某批在不同 pass 後都有取樣
    sample_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ElementSpec:
    """元素的進料濃度與規格上限。"""

    batch_id: str
    element: str
    c0_ppm: float                       # 進料初始濃度；沒測就無法對齊曲線
    spec_ppm: float | None = None       # 個別元素規格上限
    c0_measured: bool = True            # False 表示是推估值，會在 UI 標示

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BatchDetail:
    """一個批次的完整資料包，分析層的統一輸入。"""

    batch: Batch
    measurements: list[Measurement] = field(default_factory=list)
    element_specs: list[ElementSpec] = field(default_factory=list)

    @property
    def elements(self) -> list[str]:
        return sorted({m.element for m in self.measurements})

    def c0(self, element: str) -> float | None:
        for spec in self.element_specs:
            if spec.element == element:
                return spec.c0_ppm
        return None

    def points(self, element: str) -> list[Measurement]:
        pts = [m for m in self.measurements if m.element == element]
        return sorted(pts, key=lambda m: m.x_norm)

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch": self.batch.to_dict(),
            "measurements": [m.to_dict() for m in self.measurements],
            "element_specs": [s.to_dict() for s in self.element_specs],
            "elements": self.elements,
        }
