"""相機參數在介面上的分組與命名（不含 Qt，方便測試）。

工業相機（Basler／IDS）的參數動輒上百項且分屬多層類別，介面用樹狀圖呈現：
`ParamSpec.group` 以「/」分層；沒有 group 的標準參數歸「基本」、其餘歸「進階」。
"""

from __future__ import annotations

from vscapture.cameras.base import ParamSpec
from vscapture.i18n import tr

#: 標準參數的名稱由介面翻譯（相機後端回的 label 是繁中）；其餘廠牌參數保持 SDK 原名
STANDARD_PARAMS = ("exposure_us", "gain_db", "fps", "pixel_format", "width", "height", "offset_x", "offset_y", "trigger_mode")
#: 改了要暫停取像才能套用的參數
NEEDS_STOP = frozenset({"width", "height", "offset_x", "offset_y", "pixel_format"})


def param_label(spec: ParamSpec) -> str:
    return tr(f"param.{spec.name}") if spec.name in STANDARD_PARAMS else (spec.label or spec.name)


def group_path(spec: ParamSpec) -> tuple[str, ...]:
    """參數在樹狀圖的位置（由外而內）。"""
    if not spec.group:
        return (tr("params.groupBasic") if spec.standard else tr("params.groupAdvanced"),)
    parts = tuple(part.strip() for part in str(spec.group).split("/") if part.strip())
    return parts or (tr("params.groupAdvanced"),)


def sort_key(spec: ParamSpec) -> tuple[bool, tuple[str, ...]]:
    """「基本」永遠排最前面，其餘依群組路徑排序。"""
    path = group_path(spec)
    return (path[0] != tr("params.groupBasic"), path)


def matches(spec: ParamSpec, needle: str) -> bool:
    """搜尋：比對顯示名稱與 SDK 原名（大小寫不拘）；空字串代表全部符合。"""
    needle = (needle or "").strip().lower()
    if not needle:
        return True
    return needle in f"{spec.name} {param_label(spec)}".lower()
