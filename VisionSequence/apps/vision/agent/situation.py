"""AI 助手的「現況」：把前端送來的頁面快照、操作軌跡與伺服器端知道的身分／鎖定，壓成一段給 LLM 與規則的文字。

前端送什麼就用什麼（它只看得到自己有權限看的東西）；伺服器端補的只有呼叫者自己的角色與功能、引擎鎖定——
兩者對任何登入者都不是秘密。全部有長度上限，避免一張大圖的快照把提示詞撐爆。"""

from __future__ import annotations

import json
from typing import Any

MAX_PAGE_CHARS = 4000
MAX_ACTIVITY = 20
MAX_ACTIVITY_CHARS = 2400
MAX_SCREEN_CHARS = 3000

def norm_lang(lang: Any) -> str:
    """介面語言 → en / zh-Hant / zh-Hans（zh-TW、zh-HK 算繁中；其他 zh 算簡中；其餘英文）。"""
    s = str(lang or "").strip()
    low = s.lower()
    if low.startswith(("zh-hant", "zh-tw", "zh-hk", "zh-mo")):
        return "zh-Hant"
    if low.startswith("zh"):
        return "zh-Hans"
    return "en"


KIND_LABELS = {"flow_editor": "flow editor", "tool": "tool page", "batch": "batch testing", "golden": "Golden Set", "agent": "AI assistant page",
               "dl": "deep learning", "sources": "image sources", "assets": "assets", "dashboard": "dashboard", "page": ""}


def _json(value: Any, limit: int) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + "…(truncated)"


def clean_activity(items: Any) -> list[dict[str, Any]]:
    """前端的操作軌跡：只留認得的欄位、限制筆數與長度。"""
    out: list[dict[str, Any]] = []
    for it in (items or [])[-MAX_ACTIVITY:]:
        if not isinstance(it, dict):
            continue
        kind = str(it.get("kind") or "")[:16]
        text = str(it.get("text") or "")[:200]
        if not kind or not text:
            continue
        row: dict[str, Any] = {"ago_s": int(it.get("ago_s") or 0), "kind": kind, "text": text}
        if it.get("detail"):
            row["detail"] = str(it["detail"])[:400]
        if it.get("route"):
            row["route"] = str(it["route"])[:120]
        if int(it.get("count") or 1) > 1:
            row["count"] = int(it["count"])
        out.append(row)
    return out


def recent_errors(activity: list[dict[str, Any]], *, within_s: int = 600) -> list[dict[str, Any]]:
    """最近幾分鐘內的錯誤／警告（新在前）。"""
    return [a for a in reversed(activity) if a["kind"] in ("error", "warning") and a["ago_s"] <= within_s]


def describe(context: dict[str, Any], *, principal: Any = None, lock: dict[str, Any] | None = None) -> str:
    """給 LLM 的現況段落（英文，與文件同語言；LLM 會依提問語言回答）。沒有任何資訊時回空字串。"""
    ctx = context or {}
    lines: list[str] = []
    kind = KIND_LABELS.get(str(ctx.get("kind") or ""), "")
    route = str(ctx.get("route") or "")
    where = " ".join(x for x in [f"Page: {kind}" if kind else "", f"(route {route})" if route else ""] if x).strip()
    if where:
        lines.append(where)
    if ctx.get("flow_name") or ctx.get("flow_id"):
        lines.append(f"Flow: {ctx.get('flow_name') or ''} (id {ctx.get('flow_id')})".replace("  ", " "))
    if ctx.get("node_type"):
        lines.append(f"Selected tool: {ctx.get('node_type')}" + (f" (node {ctx.get('node_id')})" if ctx.get("node_id") else ""))
    if ctx.get("batch_run_id"):
        lines.append(f"Batch run: #{ctx.get('batch_run_id')}")
    if ctx.get("lang"):
        lines.append(f"UI language: {ctx.get('lang')}")
    page = ctx.get("page")
    if isinstance(page, dict) and page:
        lines.append("What the page shows now (JSON): " + _json(page, MAX_PAGE_CHARS))
    activity = clean_activity(ctx.get("activity"))
    if activity:
        rows = [f"- {a['ago_s']}s ago [{a['kind']}] {a['text']}" + (f" — {a['detail']}" if a.get("detail") else "") + (f" (x{a['count']})" if a.get("count") else "") for a in activity]
        text = "\n".join(rows)
        if len(text) > MAX_ACTIVITY_CHARS:
            text = text[-MAX_ACTIVITY_CHARS:]
        lines.append("Recent activity (oldest first):\n" + text)
    screen = str(ctx.get("screen") or "").strip()
    if screen:
        lines.append("Screen text summary:\n" + screen[:MAX_SCREEN_CHARS])
    if principal is not None:
        who = _principal_line(principal)
        if who:
            lines.append(who)
    if lock and lock.get("locked"):
        lines.append(f"Engine lock: locked by {lock.get('holder') or 'unknown'}" + (f" ({lock.get('reason')})" if lock.get("reason") else "") + "; only the holder can run inspections until UNLOCK.")
    return "\n".join(lines)


def _principal_line(p: Any) -> str:
    try:
        kind = getattr(p, "kind", "")
        if kind == "integrator":
            return "Caller: integrator (API key; can always run and lock the engine)."
        if kind == "bootstrap":
            return "Caller: setup mode (no users exist yet)."
        from apps.accounts import permissions

        role = getattr(p, "role", "") or ""
        allowed = [k for k in permissions.FEATURES if p.can(k)]
        name = ""
        user = getattr(p, "user", None)
        if user is not None:
            name = getattr(user, "username", "") or ""
        parts = [f"Caller: {name or 'user'}", f"role {role}" if role else ""]
        if allowed:
            parts.append("allowed features: " + ", ".join(allowed))
        return ", ".join(x for x in parts if x) + ". Do not tell them to do something their role cannot; say which role can."
    except Exception:  # noqa: BLE001 - 現況只是輔助，取不到就不寫
        return ""
