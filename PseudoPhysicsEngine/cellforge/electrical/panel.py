"""盤面排版：依軌道與順序由左至右排列盤內器件，算出位置並檢查寬度與上下間距。

檢查與盤面圖共用這份排版結果，圖上位置就是檢查所用的幾何。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .resolve import ResolvedElectrical


@dataclass
class Placement:
    device: str
    rail: str
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float


@dataclass
class RailBand:
    rail: str
    kind: str
    y_mm: float
    top_mm: float
    bottom_mm: float
    used_mm: float
    available_mm: float


@dataclass
class PanelResult:
    placements: dict[str, Placement] = field(default_factory=dict)
    bands: list[RailBand] = field(default_factory=list)
    unplaced: list[str] = field(default_factory=list)
    unsized: list[str] = field(default_factory=list)
    problems: list[tuple[str, list[str]]] = field(default_factory=list)


def layout_panel(resolved: ResolvedElectrical) -> PanelResult | None:
    panel = resolved.source.panel
    if panel is None:
        return None
    result = PanelResult()
    left = panel.margin_mm
    available = panel.width_mm - 2 * panel.margin_mm
    on_rail: dict[str, list] = {rail.id: [] for rail in panel.rails}
    for device in resolved.devices.values():
        if device.location != "panel":
            continue
        if device.panel is None or device.panel.rail not in on_rail:
            result.unplaced.append(device.id)
            continue
        if device.size_mm is None:
            result.unsized.append(device.id)
            continue
        on_rail[device.panel.rail].append(device)
    for rail in panel.rails:
        devices = sorted(on_rail[rail.id], key=lambda item: (item.panel.order, item.id))
        cursor = left
        for index, device in enumerate(devices):
            width, height = device.size_mm[0], device.size_mm[1]
            if index:
                cursor += panel.clearance_mm
            result.placements[device.id] = Placement(
                device.id, rail.id, cursor + width / 2, rail.y_mm, width, height
            )
            cursor += width
        used = cursor - left
        if rail.kind == "duct":
            half = (rail.height_mm or 0.0) / 2
            used = available  # 線槽橫跨整個盤面
        else:
            half = max((device.size_mm[1] for device in devices), default=0.0) / 2
        result.bands.append(
            RailBand(
                rail.id, rail.kind, rail.y_mm, rail.y_mm - half, rail.y_mm + half, used, available
            )
        )
        if rail.kind != "duct" and used > available:
            result.problems.append(
                (
                    f"盤面空間不足：軌道 {rail.id} 需 {used:.0f} mm，可用 {available:.0f} mm",
                    [device.id for device in devices],
                )
            )
    bands = sorted(result.bands, key=lambda band: band.y_mm)
    for band in bands:
        if band.top_mm < panel.margin_mm or band.bottom_mm > panel.height_mm - panel.margin_mm:
            result.problems.append(
                (f"軌道 {band.rail} 的器件超出盤面上下邊界（含邊距 {panel.margin_mm:g} mm）", [])
            )
    for upper, lower in zip(bands, bands[1:], strict=False):
        gap = lower.top_mm - upper.bottom_mm
        if gap < panel.clearance_mm:
            result.problems.append(
                (
                    f"軌道 {upper.rail} 與 {lower.rail} 上下間距 {gap:.0f} mm，"
                    f"小於要求 {panel.clearance_mm:g} mm",
                    [],
                )
            )
    return result
