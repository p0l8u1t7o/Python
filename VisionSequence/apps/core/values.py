"""使用者看得到的「值」怎麼寫成一小段文字：稽核摘要、變數摘要、版本差異都用它。

以前是 f-string 直接塞 Python 物件，`None`／`True`／`[{'id': …}]` 這種 repr 就直接出現在操作紀錄裡
（PM-REVIEW-R2 L-4）。這裡統一成 JSON 記法（null／true／false／[…]），字串原樣、太長就截斷。
"""

from __future__ import annotations

import json
from typing import Any

#: 摘要裡單一個值最多幾個字（整列摘要另有 400 字上限）
MAX_VALUE_CHARS = 60


def fmt_value(value: Any, limit: int = MAX_VALUE_CHARS) -> str:
    """一個值的短文字：JSON 記法、非 ASCII 原樣、超過 limit 截斷加省略號。"""
    if value is None:
        text = "null"
    elif isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, (int, float)):
        text = str(value)
    elif isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))
        except (TypeError, ValueError):
            text = str(value)
    if limit and len(text) > limit:
        return text[: max(limit - 1, 1)] + "…"
    return text


def field_changes(changes: dict[str, Any]) -> list[dict[str, Any]]:
    """`{field: {before, after}}` → `[{field, before, after}]`（稽核 detail 的結構化形狀，前端畫成表格）。"""
    return [{"field": key, "before": entry.get("before"), "after": entry.get("after")}
            for key, entry in changes.items() if isinstance(entry, dict)]
