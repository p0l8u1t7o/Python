"""助手對話（每位使用者的多條聊天）：建立、列出、載入、改寫、刪除。

規則：
- 訊息就是前端的 `ChatMessage` 陣列，原樣存 JSON（助手視窗要能完整還原：來源、動作、建議都在裡面）。
- 一位使用者最多留 `MAX_CHATS` 條，超過淘汰最舊的（依 updated_at）；每條最多 `MAX_MESSAGES` 則。
- 標題沒給就取第一句使用者的話（截斷），空對話顯示「新對話」由前端處理。
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any

from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from apps.core.errors import NotFound, ValidationError
from apps.vision import graphdiff, versions
from apps.vision.models import AssistantChat, Flow

#: 每位使用者保留幾條對話
MAX_CHATS = 50
#: 每條對話保留幾則訊息（與前端 MAX_MESSAGES 對齊）
MAX_MESSAGES = 60
#: 單條對話的 JSON 上限（避免截圖等大字串塞爆資料庫）
MAX_BYTES = 512 * 1024
TITLE_LEN = 60
STATE_BYTES = 64 * 1024
log = logging.getLogger(__name__)
UNSET = object()


def _text(value: Any, limit: int = 1000) -> str:
    return value[:limit] if isinstance(value, str) else ""


def _value(value: Any, depth: int = 0) -> Any:
    """限制提案值的深度與寬度，影像與圖不可塞進工作狀態。"""
    if depth > 5:
        return None
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value if abs(value) < 1e100 and math.isfinite(value) else None
    if isinstance(value, str):
        return "" if value.startswith("data:") else value[:1000]
    if isinstance(value, list):
        return [_value(v, depth + 1) for v in value[:40]]
    if isinstance(value, dict):
        return {_text(k, 80): _value(v, depth + 1) for k, v in list(value.items())[:40]
                if isinstance(k, str) and k not in {"graph", "nodes", "edges", "image", "base64", "screenshot"}}
    return None


def clean_state(value: Any) -> dict[str, Any]:
    """封閉工作狀態欄位；不保存正式規格，UTF-8 JSON 不超過 64 KB。"""
    if not isinstance(value, dict) or not value:
        return {}
    if value.get("version", 1) != 1 or isinstance(value.get("version"), bool):
        raise ValidationError("Unsupported work state version", code="work_state_version")
    out: dict[str, Any] = {"version": 1}
    for key in ("flow_id", "flow_version"):
        item = value.get(key)
        out[key] = item if type(item) is int and item > 0 else None
    out["flow_updated_at"] = _text(value.get("flow_updated_at"), 80)
    def rows(key):
        items = value.get(key)
        return [r for r in items[-60:] if isinstance(r, dict)] if isinstance(items, list) else []
    out["pending_questions"] = []
    for r in rows("pending_questions"):
        if not _text(r.get("text")):
            continue
        out["pending_questions"].append({"id": _text(r.get("id"), 80), "text": _text(r.get("text")),
                                         "kind": r.get("kind") if r.get("kind") in ("text", "number", "choice", "roi") else "text",
                                         "options": _value(r.get("options", [])), "optional": r.get("optional") is True})
    out["assumptions"] = [{"task_id": _text(r.get("task_id"), 40), "field": _text(r.get("field"), 80),
                           "value": _value(r.get("value")), "note": _text(r.get("note"))}
                          for r in rows("assumptions") if _text(r.get("field"))]
    out["decisions"] = [{"at": _text(r.get("at"), 80), "text": _text(r.get("text")), "by": r["by"]}
                        for r in rows("decisions") if r.get("by") in ("user", "assistant") and _text(r.get("text"))]
    groups = value.get("sample_groups")
    out["sample_groups"] = {key: [_text(ref, 200) for ref in groups.get(key, [])[:100] if isinstance(ref, str) and not ref.startswith("data:")]
                            if isinstance(groups, dict) and isinstance(groups.get(key), list) else [] for key in ("tune", "accept")}
    trial = value.get("last_trial")
    if isinstance(trial, dict):
        out["last_trial"] = {"at": _text(trial.get("at"), 80), "status": _text(trial.get("status"), 30),
                             "summary": _text(trial.get("summary"), 2000), "per_task": []}
        items = trial.get("per_task")
        for r in items[:60] if isinstance(items, list) else []:
            if isinstance(r, dict) and _text(r.get("task_id")):
                out["last_trial"]["per_task"].append({"task_id": _text(r["task_id"], 40), "status": _text(r.get("status"), 30), "value": _value(r.get("value"))})
    out["drafts"] = []
    for r in rows("drafts"):
        if not _text(r.get("draft_id")) or r.get("op") not in ("add", "update", "remove", "answer", "run"):
            continue
        fields = r.get("fields")
        draft = {"draft_id": _text(r["draft_id"], 80), "op": r["op"], "kind": _text(r.get("kind"), 40),
                 "task_id": _text(r.get("task_id"), 40), "note": _text(r.get("note")), "fields": {}, "regions": []}
        for key, entry in list(fields.items())[:40] if isinstance(fields, dict) else []:
            if not isinstance(entry, dict) or entry.get("status") not in ("confirmed", "assumed", "missing"):
                continue
            draft["fields"][_text(key, 80)] = {"value": _value(entry.get("value")), "status": entry["status"],
                                              "source": entry.get("source") if entry.get("source") in ("user", "rule", "llm", "default") else "default",
                                              "note": _text(entry.get("note"))}
            if draft["fields"][_text(key, 80)]["value"] != entry.get("value"):
                draft["fields"][_text(key, 80)].update(value=None, status="missing", note="The saved value was too large or invalid. Enter it again.")
        for region in r.get("regions", [])[:20] if isinstance(r.get("regions"), list) else []:
            if isinstance(region, dict) and region.get("field") in draft["fields"]:
                field = draft["fields"][region["field"]]
                draft["regions"].append({"field": region["field"], "region": field["value"], "status": field["status"], "source": field["source"]})
        out["drafts"].append(draft)
    # 超量時捨棄最舊的完整項目，絕不切斷 JSON 或提案欄位。
    while len(json.dumps(out, ensure_ascii=False).encode("utf-8")) > STATE_BYTES:
        key = max((k for k in ("drafts", "decisions", "assumptions", "pending_questions") if out[k]),
                  key=lambda k: len(json.dumps(out[k], ensure_ascii=False)), default=None)
        if key:
            out[key].pop(0)
        elif out.get("last_trial", {}).get("per_task"):
            out["last_trial"]["per_task"].pop(0)
        else:
            for refs in out["sample_groups"].values():
                if refs:
                    refs.pop(0)
    return out


def bind(row: AssistantChat, flow_id: Any) -> None:
    """刪除流程後仍以狀態中的 id 記住原綁定，禁止重綁。"""
    previous = row.flow_id or (row.work_state or {}).get("flow_id")
    if previous and previous != flow_id:
        raise ValidationError("This conversation is already bound to a flow", code="chat_bound")
    if flow_id is None or previous:
        return
    flow = Flow.objects.filter(pk=flow_id).first()
    if flow is None:
        raise NotFound("The flow does not exist", code="flow_not_found")
    row.flow = flow
    versions.snapshot(flow)
    row.work_state = clean_state({**(row.work_state or {}), "flow_id": flow.pk,
                                  "flow_updated_at": flow.updated_at.isoformat(), "flow_version": flow.version})


def resume(row: AssistantChat) -> dict[str, Any]:
    state = clean_state(row.work_state)
    flow = row.flow
    if flow is None:
        return {"work_state": state, "flow": None, "changed": False, "flow_missing": bool(state.get("flow_id"))}
    changed = bool(state.get("flow_updated_at") and state["flow_updated_at"] != flow.updated_at.isoformat())
    result = {"work_state": state, "flow": {"id": flow.pk, "name": flow.name, "updated_at": flow.updated_at.isoformat(), "version": flow.version}, "changed": changed}
    if changed:
        old = flow.versions.filter(version=state.get("flow_version")).first()
        result["diff_summary"] = (graphdiff.summarize(graphdiff.diff(old.graph, flow.graph)) or "Flow details changed.") if old else "The previous flow version is no longer available."
    return result


def record(row: AssistantChat | None, update: dict[str, Any], decision: str = "") -> dict[str, Any] | None:
    """動作成功後盡力留存；紀錄失敗不得把已成功的動作變成錯誤。"""
    if row is None:
        return
    try:
        row.refresh_from_db()
        state = {**row.work_state, **update}
        if decision:
            state["decisions"] = [*state.get("decisions", []), {"at": timezone.now().isoformat(), "text": decision, "by": "assistant"}]
        return save(row, work_state=state).work_state
    except Exception:
        log.exception("助手工作狀態儲存失敗")


def title_from(messages: list[dict[str, Any]]) -> str:
    for m in messages:
        if isinstance(m, dict) and m.get("role") == "user" and str(m.get("text") or "").strip():
            return str(m["text"]).strip().replace("\n", " ")[:TITLE_LEN]
    return ""


def clean(messages: Any) -> list[dict[str, Any]]:
    """只留合法的訊息物件、最後 MAX_MESSAGES 則；整體超過 MAX_BYTES 再從最舊的丟。"""
    if not isinstance(messages, list):
        return []
    rows = [m for m in messages if isinstance(m, dict) and m.get("role") in ("user", "assistant")][-MAX_MESSAGES:]
    while rows and len(json.dumps(rows, ensure_ascii=False).encode("utf-8")) > MAX_BYTES:
        rows = rows[1:]
    return rows


def out(row: AssistantChat, *, with_messages: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": row.pk,
        "title": row.title,
        "count": len(row.messages or []),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "flow_id": row.flow_id or (row.work_state or {}).get("flow_id"),
        "flow_name": row.flow.name if row.flow_id else "",
    }
    if with_messages:
        data["messages"] = row.messages or []
        data["work_state"] = clean_state(row.work_state)
    return data


def listing(user: User) -> list[dict[str, Any]]:
    return [out(row) for row in AssistantChat.objects.filter(owner=user).select_related("flow")[:MAX_CHATS]]


def get(user: User, chat_id: int) -> AssistantChat | None:
    return AssistantChat.objects.filter(owner=user, pk=chat_id).first()


@transaction.atomic
def create(user: User, messages: Any = None, title: str = "", *, flow_id: int | None = None, work_state: Any = None) -> AssistantChat:
    rows = clean(messages)
    row = AssistantChat(owner=user, title=(title or title_from(rows))[:TITLE_LEN], messages=rows)
    bind(row, flow_id)
    row.save()
    if work_state is not None:
        row = save(row, work_state=work_state)
    prune(user)
    return row


@transaction.atomic
def save(row: AssistantChat, messages: Any = None, title: str | None = None, *, flow_id: Any = UNSET, work_state: Any = None) -> AssistantChat:
    row = AssistantChat.objects.select_for_update().get(pk=row.pk)
    fields = ["updated_at"]
    if flow_id is not UNSET:
        bind(row, flow_id)
        fields.extend(["flow", "work_state"])
    if work_state is not None and (work_state or row.work_state):
        state = clean_state({**(row.work_state or {}), **(work_state if isinstance(work_state, dict) else {})})
        # 前後端各自記錄成功動作；較早的訊息快照不得抹掉後端剛寫入的決策。
        decisions = [*(row.work_state or {}).get("decisions", []), *state.get("decisions", [])]
        state["decisions"] = list({json.dumps(d, sort_keys=True, ensure_ascii=False): d for d in decisions}.values())[-60:]
        # 綁定 id 由資料表控制；普通訊息儲存不能前移流程版本基準。
        state["flow_id"] = row.flow_id or (row.work_state or {}).get("flow_id")
        row.work_state = clean_state(state)
        if "work_state" not in fields:
            fields.append("work_state")
    if messages is not None:
        row.messages = clean(messages)
        fields.append("messages")
        if not (title or row.title):
            row.title = title_from(row.messages)
            fields.append("title")
    if title is not None:
        row.title = title[:TITLE_LEN]
        if "title" not in fields:
            fields.append("title")
    row.save(update_fields=fields)
    return row


def delete(user: User, chat_id: int) -> bool:
    return bool(AssistantChat.objects.filter(owner=user, pk=chat_id).delete()[0])


def prune(user: User) -> int:
    """超過上限就丟掉最舊的（updated_at 最小的）。"""
    ids = list(AssistantChat.objects.filter(owner=user).values_list("pk", flat=True)[MAX_CHATS:])
    return AssistantChat.objects.filter(pk__in=ids).delete()[0] if ids else 0
