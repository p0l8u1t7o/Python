"""CellForge package."""

from __future__ import annotations

import importlib.machinery
import os
import sys
import types

__version__ = "0.1.0"

_NLOPT_DISABLED_MESSAGE = (
    "CellForge 在 Windows 停用 {name}：casadi 與 nlopt 同時載入會使 Python 結束時崩潰"
    "（ntdll 存取違規）。需要 cadquery 草圖約束求解時，請設定環境變數 CELLFORGE_ALLOW_NLOPT=1。"
)


class _UnavailableNlopt:
    """nlopt 的替身：讀取屬性時回傳替身，真正呼叫時才報錯。"""

    def __init__(self, name: str) -> None:
        self._name = name

    def __getattr__(self, item: str) -> _UnavailableNlopt:
        if item.startswith("__"):
            raise AttributeError(item)
        return _UnavailableNlopt(f"{self._name}.{item}")

    def __call__(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError(_NLOPT_DISABLED_MESSAGE.format(name=self._name))

    def __mro_entries__(self, bases: tuple[type, ...]) -> tuple[type, ...]:
        return (object,)


def _disable_nlopt_on_windows() -> None:
    """cadquery 會同時載入 casadi 與 nlopt；在 Windows 上兩者並存會讓 python.exe 結束時崩潰。

    nlopt 只給 cadquery 的草圖約束求解器使用，CellForge 用不到，所以在 cadquery 載入前換成替身。
    詳見 docs/DECISIONS.md D-011。
    """
    if sys.platform != "win32" or os.environ.get("CELLFORGE_ALLOW_NLOPT") == "1":
        return
    if "nlopt" in sys.modules:
        return
    module = types.ModuleType("nlopt")
    module.__spec__ = importlib.machinery.ModuleSpec("nlopt", None)

    def module_getattr(item: str) -> _UnavailableNlopt:
        if item.startswith("__"):
            raise AttributeError(item)
        return _UnavailableNlopt(f"nlopt.{item}")

    module.__getattr__ = module_getattr  # type: ignore[method-assign]
    sys.modules["nlopt"] = module


_disable_nlopt_on_windows()
