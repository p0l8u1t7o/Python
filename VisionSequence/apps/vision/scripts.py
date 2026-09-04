"""Python 腳本工具（python_script）的核准清單：只有管理員儲存過的程式碼才能在引擎裡執行。

- 核准單位是程式碼的 sha256（換行正規化後）；同一段程式碼在任何流程都算核准。
- 熱路徑（工具 execute）只查記憶體集合；集合第一次用到時從 DB 載入，之後由 approve() 在同一行程更新
  （平台只有一個 API 行程，見 CLAUDE.md）。
- 儲存流程（POST/PATCH /flows、匯入）時呼叫 check_graph_edit：新圖裡每段腳本要嘛已核准，要嘛由管理員此次儲存核准，
  否則 403。編輯器試執行（未儲存的圖）只有管理員可跑未核准的腳本（context `_script_admin`，由 preview 端點依身分放入）。
"""

from __future__ import annotations

import hashlib
import threading
from typing import Any

from apps.core.errors import PermissionDenied

SCRIPT_TOOL = "python_script"
ADMIN_CONTEXT_KEY = "_script_admin"

_approved: set[str] | None = None
_lock = threading.Lock()


def normalize(code: str) -> str:
    return str(code or "").replace("\r\n", "\n").replace("\r", "\n")


def code_hash(code: str) -> str:
    return hashlib.sha256(normalize(code).encode("utf-8")).hexdigest()


def _approved_set() -> set[str]:
    global _approved
    if _approved is None:
        with _lock:
            if _approved is None:
                from apps.vision.models import ScriptApproval

                _approved = set(ScriptApproval.objects.values_list("code_hash", flat=True))
    return _approved


def is_approved(code: str) -> bool:
    return code_hash(code) in _approved_set()


def approve(code: str, *, user: Any = None, flow: Any = None) -> str:
    """登記一段程式碼為已核准（管理員儲存流程時呼叫）。回 sha256。"""
    from apps.vision.models import ScriptApproval

    h = code_hash(code)
    approved = _approved_set()
    if h not in approved:
        ScriptApproval.objects.get_or_create(
            code_hash=h,
            defaults={"code": normalize(code), "approved_by": user if getattr(user, "pk", None) else None, "flow": flow if getattr(flow, "pk", None) else None},
        )
        approved.add(h)
    return h


def reset_cache() -> None:
    """測試用：下次查詢重新從 DB 載入。"""
    global _approved
    with _lock:
        _approved = None


def seed_cache(hashes: set[str] | None) -> None:
    """測試用：直接指定核准集合（SimpleTestCase 不能碰 DB）。None＝清掉、回到懶載入。"""
    global _approved
    with _lock:
        _approved = None if hashes is None else set(hashes)


def scripts_in(graph: dict[str, Any] | None) -> list[str]:
    """圖裡所有 python_script 節點的程式碼。"""
    return [str((n.get("params") or {}).get("code") or "") for n in (graph or {}).get("nodes") or [] if n.get("type") == SCRIPT_TOOL]


def check_graph_edit(p: Any, new_graph: dict[str, Any] | None, *, flow: Any = None) -> None:
    """儲存流程前的守門：新圖裡每段非空腳本要嘛已核准、要嘛由管理員此次儲存核准；一般使用者送未核准的腳本 → 403。"""
    codes = [c for c in scripts_in(new_graph) if c.strip()]
    if not codes:
        return
    approved = _approved_set()
    for code in codes:
        if code_hash(code) in approved:
            continue
        if not getattr(p, "is_admin", False):
            raise PermissionDenied("Only administrators may add or change Python scripts; ask one to save this flow first", code="script_not_approved")
        approve(code, user=getattr(p, "user", None), flow=flow)


def client_context(raw: dict[str, Any] | None, *, admin: bool = False) -> dict[str, Any]:
    """整理外部送來的 run context：`_` 開頭的鍵保留給平台內部（`_outputs`、`_script_admin`…），一律丟掉；管理員試執行才加上核准旗標。"""
    out = {str(k): v for k, v in (raw or {}).items() if not str(k).startswith("_")} if isinstance(raw, dict) else {}
    if admin:
        out[ADMIN_CONTEXT_KEY] = True
    return out
