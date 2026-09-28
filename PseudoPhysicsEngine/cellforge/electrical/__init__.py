"""電控連接：electrical.yaml 的展開、點位配置、連通檢查與版本化報告。"""

from .checks import electrical_checks
from .report import electrical_report, required_modules
from .resolve import (
    ElectricalReferenceError,
    ResolvedElectrical,
    require_valid,
    resolve_electrical,
)

__all__ = [
    "ElectricalReferenceError",
    "ResolvedElectrical",
    "electrical_checks",
    "electrical_report",
    "require_valid",
    "required_modules",
    "resolve_electrical",
]
