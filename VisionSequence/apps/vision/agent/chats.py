"""助手對話（每位使用者的多條聊天）：建立、列出、載入、改寫、刪除。

規則：
- 訊息就是前端的 `ChatMessage` 陣列，原樣存 JSON（助手視窗要能完整還原：來源、動作、建議都在裡面）。
- 一位使用者最多留 `MAX_CHATS` 條，超過淘汰最舊的（依 updated_at）；每條最多 `MAX_MESSAGES` 則。
- 標題沒給就取第一句使用者的話（截斷），空對話顯示「新對話」由前端處理。
"""

from __future__ import annotations

import json
from typing import Any

from django.contrib.auth.models import User

from apps.vision.models import AssistantChat

#: 每位使用者保留幾條對話
MAX_CHATS = 50
#: 每條對話保留幾則訊息（與前端 MAX_MESSAGES 對齊）
MAX_MESSAGES = 60
#: 單條對話的 JSON 上限（避免截圖等大字串塞爆資料庫）
MAX_BYTES = 512 * 1024
TITLE_LEN = 60


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
    }
    if with_messages:
        data["messages"] = row.messages or []
    return data


def listing(user: User) -> list[dict[str, Any]]:
    return [out(row) for row in AssistantChat.objects.filter(owner=user)[:MAX_CHATS]]


def get(user: User, chat_id: int) -> AssistantChat | None:
    return AssistantChat.objects.filter(owner=user, pk=chat_id).first()


def create(user: User, messages: Any = None, title: str = "") -> AssistantChat:
    rows = clean(messages)
    row = AssistantChat.objects.create(owner=user, title=(title or title_from(rows))[:TITLE_LEN], messages=rows)
    prune(user)
    return row


def save(row: AssistantChat, messages: Any = None, title: str | None = None) -> AssistantChat:
    fields = ["updated_at"]
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
