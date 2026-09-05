"""資料夾外掛：把 .py 檔丟進專案根目錄的 plugins/ 就會自動掛載，不用改 .env。

支援三類物件（都用繼承，放同一個檔案裡也可以）：
    apps.vision.tools.base.Tool          自訂工具（畫布調色盤）
    apps.vision.sources.grabbers.Grabber 自訂影像來源（kind）
    apps.comm.writers.Writer             自訂整合輸出連線（kind）

外掛檔內可用變數控制掛載與顯示（見 plugins/ 下的範例）：
    ENABLED = False        模組層：整個檔案不掛載
    class X(...):
        enabled = False    類別層：只停用這個類別
        label = "顯示名稱"
        description = "說明"

規則：
- 檔名底線開頭（_xxx.py）跳過；掃描順序照檔名排序。
- 只認「該檔案自己定義」的類別；import 進來的基底不會被重複註冊。
- key／kind 已存在時跳過（內建優先），不覆蓋、不報錯，只記 log。
- 單一檔案載入失敗只記 log，不影響其他外掛與平台啟動。
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import logging
import sys
import threading
import time
from pathlib import Path
from types import ModuleType
from typing import Any

from django.conf import settings

log = logging.getLogger(__name__)

#: 已掃描過的資料夾（resolve 後的路徑），避免 ready() 被呼叫多次時重複 import。
_loaded_dirs: set[str] = set()

#: 外掛清單：檔名 → 這一次載入的結果（狀態、掛了什麼、錯在哪）。外掛頁讀它；
#: 以前錯誤只進日誌，現場沒有人會去翻日誌。
_inventory: dict[str, dict[str, Any]] = {}
_inventory_lock = threading.Lock()


def plugin_dir() -> Path:
    return Path(settings.VISION.get("PLUGIN_DIR") or (Path(settings.BASE_DIR) / "plugins"))


def load_folder_plugins(directory: str | Path | None = None, *, force: bool = False) -> list[str]:
    """掃描資料夾並掛載外掛。回傳掛載清單（"tool:key" / "source:kind" / "comm:kind"）。"""
    folder = Path(directory) if directory else plugin_dir()
    resolved = str(folder.resolve())
    if not force and resolved in _loaded_dirs:
        return []
    _loaded_dirs.add(resolved)
    if not folder.is_dir():
        return []
    mounted: list[str] = []
    for path in _entries(folder):
        # 重新掃描（force）只碰還沒載入過或上次失敗的檔案：Python 模組不能安全地熱重載，
        # 已載入的檔案改了要重啟伺服器（外掛頁會這樣提示）。
        previous = _inventory.get(path.name)
        if force and previous and previous["status"] != "error":
            continue
        mounted += _load_entry(path)
    return mounted


def _entries(folder: Path) -> list[Path]:
    """單檔外掛（x.py）＋資料夾型外掛（x/__init__.py，整個外掛專案丟進來）；底線開頭的跳過。"""
    entries = [p for p in folder.glob("*.py")] + [p for p in folder.iterdir() if p.is_dir() and (p / "__init__.py").exists()]
    return [p for p in sorted(entries, key=lambda p: p.name) if not p.name.startswith("_")]


def _load_entry(path: Path) -> list[str]:
    """載入一個外掛檔並把結果記進清單；回傳掛載清單。"""
    record: dict[str, Any] = {
        "name": path.name, "path": str(path), "kind": "package" if path.is_dir() else "file",
        "status": "ok", "error": "", "mounted": [], "requirements": _requirements_path(path) is not None,
        "loaded_at": time.time(),
    }
    found: list[str] = []
    try:
        module = _import(path)
    except ModuleNotFoundError as exc:
        hint = _requirements_hint(path)
        log.error("外掛 %s 載入失敗：缺少套件 %s。%s", path.name, exc.name, hint)
        record.update(status="error", error=f"Missing package '{exc.name}'. {hint}".strip())
    except Exception as exc:  # noqa: BLE001 — 單一外掛壞掉不影響其他外掛
        log.exception("外掛 %s 載入失敗，略過", path.name)
        record.update(status="error", error=f"{type(exc).__name__}: {str(exc)[:300]}")
    else:
        if not getattr(module, "ENABLED", True):
            log.info("外掛 %s 已停用（ENABLED = False），略過", path.name)
            record["status"] = "disabled"
        else:
            found = _register_module(module)
            record["mounted"] = list(found)
            if found:
                log.info("外掛 %s 掛載：%s", path.name, ", ".join(found))
            else:
                record["status"] = "empty"
    with _inventory_lock:
        _inventory[path.name] = record
    return found


def inventory() -> list[dict[str, Any]]:
    """外掛頁要的清單（照檔名排）。"""
    with _inventory_lock:
        return [dict(_inventory[name]) for name in sorted(_inventory)]


def rescan() -> list[str]:
    """掛載新放進 plugins/ 的檔案、重試上次失敗的；已載入的不重載。回傳這次新掛的。"""
    return load_folder_plugins(force=True)


def _requirements_path(path: Path) -> Path | None:
    req = (path / "requirements.txt") if path.is_dir() else path.with_suffix(".requirements.txt")
    return req if req.exists() else None


def _requirements_hint(path: Path) -> str:
    """外掛附 requirements.txt 時，在缺依賴的錯誤旁提示安裝指令。"""
    req = (path / "requirements.txt") if path.is_dir() else path.with_suffix(".requirements.txt")
    if req.exists():
        return f'Install the plugin dependencies first: .venv\\Scripts\\pip install -r "{req}"'
    return "A plugin's dependencies must be installed into the platform's .venv, because it loads in the same process; see the integration section of the plugins documentation."


def _import(path: Path) -> ModuleType:
    """優先用套件路徑 import（plugins/ 是專案根目錄下的套件）；其他位置用檔案路徑載入。
    path 是 .py 檔（單檔外掛）或含 __init__.py 的資料夾（資料夾型外掛，掛載點是它的 __init__）。"""
    package_root = Path(settings.BASE_DIR) / "plugins"
    if path.parent.resolve() == package_root.resolve() and (package_root / "__init__.py").exists():
        return importlib.import_module(f"plugins.{path.stem}")
    name = f"_vs_folder_plugin_{path.stem}"
    target = path / "__init__.py" if path.is_dir() else path
    locations = [str(path)] if path.is_dir() else None
    spec = importlib.util.spec_from_file_location(name, target, submodule_search_locations=locations)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _register_module(module: ModuleType) -> list[str]:
    from apps.comm import writers
    from apps.vision import sources
    from apps.vision.dl import base as dl_base
    from apps.vision.sources.grabbers import Grabber
    from apps.vision.tools import base

    out: list[str] = []
    for _, obj in inspect.getmembers(module, inspect.isclass):
        # 只認外掛自己定義的類別（單檔＝同模組；資料夾型＝套件底下的子模組），import 進來的基底不算。
        if obj.__module__ != module.__name__ and not obj.__module__.startswith(module.__name__ + "."):
            continue
        if not getattr(obj, "enabled", True):
            log.info("外掛類別 %s.%s 已停用（enabled = False），略過", module.__name__, obj.__name__)
            continue
        if issubclass(obj, base.Tool) and getattr(obj, "key", ""):
            if base.has(obj.key):
                log.warning("外掛工具 '%s' 已存在，略過 %s", obj.key, obj.__name__)
            else:
                base.register(obj())
                out.append(f"tool:{obj.key}")
        elif issubclass(obj, Grabber) and getattr(obj, "kind", ""):
            if sources.register_kind(obj):
                out.append(f"source:{obj.kind}")
        elif issubclass(obj, writers.Writer) and getattr(obj, "kind", ""):
            if writers.register_kind(obj):
                out.append(f"comm:{obj.kind}")
        elif issubclass(obj, dl_base.Trainer) and getattr(obj, "kind", ""):
            if dl_base.register_trainer(obj):
                out.append(f"dl:{obj.kind}")
    return out
