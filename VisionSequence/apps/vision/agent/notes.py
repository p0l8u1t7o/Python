"""全域 AI 助手的長期記憶（每位使用者自己的，管理員也看不到別人的）：

- **事實**：使用者要它記住的一句話（「記住：產線 3 用流程「檢測 A」」／「remember: …」），問答時整段進現況；「忘記：…」刪掉含該字的事實。
- **問答**：每次說明問答都留一筆（問題、回答、當時的頁面），使用者可評分；之後遇到相似的問題，評過好的舊回答當範例給 LLM，
  離線時相似度夠高就直接用那個回答。

數量有上限（事實 50、問答 200，淘汰最舊且未評分的）；只屬於該使用者，刪帳號一起刪。"""

from __future__ import annotations

import re
from typing import Any

from django.utils import timezone

from apps.vision.agent.situation import norm_lang
from apps.vision.models import AssistantMemory

MAX_FACTS = 50
MAX_QA = 200
FACT_MAX_CHARS = 300
QUESTION_MAX_CHARS = 500
ANSWER_MAX_CHARS = 2000
#: 相似問答：至少這麼像才當範例；離線時至少這麼像才直接用舊回答
RECALL_MIN = 0.35
DIRECT_MIN = 0.6
RECALL_LIMIT = 2

_REMEMBER = re.compile(r"^\s*(?:記住|记住|remember)\s*[:：]\s*(.*)$", re.IGNORECASE | re.DOTALL)
_FORGET = re.compile(r"^\s*(?:忘記|忘记|forget)\s*[:：]\s*(.*)$", re.IGNORECASE | re.DOTALL)


def parse_command(message: str) -> tuple[str, str] | None:
    """「記住：…」→ ("remember", 文字)；「忘記：…」→ ("forget", 文字)；其他 None。"""
    m = _REMEMBER.match(message or "")
    if m:
        return "remember", m.group(1).strip()
    m = _FORGET.match(message or "")
    if m:
        return "forget", m.group(1).strip()
    return None


def _user_ok(user: Any) -> bool:
    return user is not None and getattr(user, "pk", None) is not None


def out(row: AssistantMemory) -> dict[str, Any]:
    return {"id": row.id, "kind": row.kind, "text": row.text, "answer": row.answer, "context": row.context or {}, "rating": row.rating, "hits": row.hits,
            "created_at": row.created_at.isoformat() if row.created_at else None, "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None}


# ---- 事實 ----
def add_fact(user: Any, text: str) -> AssistantMemory:
    text = " ".join((text or "").split())[:FACT_MAX_CHARS]
    if not text:
        raise ValueError("The fact is empty")
    row, created = AssistantMemory.objects.get_or_create(owner=user, kind="fact", text=text)
    if not created:
        row.save(update_fields=["updated_at"])
    extra = AssistantMemory.objects.filter(owner=user, kind="fact").order_by("-updated_at", "-id")[MAX_FACTS:]
    if extra:
        AssistantMemory.objects.filter(pk__in=[r.pk for r in extra]).delete()
    return row


def forget_facts(user: Any, text: str) -> int:
    text = (text or "").strip()
    if not text:
        return 0
    deleted, _ = AssistantMemory.objects.filter(owner=user, kind="fact", text__icontains=text).delete()
    return deleted


def facts(user: Any) -> list[AssistantMemory]:
    if not _user_ok(user):
        return []
    return list(AssistantMemory.objects.filter(owner=user, kind="fact").order_by("-updated_at", "-id")[:MAX_FACTS])


def facts_text(user: Any, limit_chars: int = 1500) -> str:
    lines = [f"- {f.text}" for f in facts(user)]
    text = "\n".join(lines)
    return text[:limit_chars]


def delete(user: Any, memory_id: int) -> bool:
    deleted, _ = AssistantMemory.objects.filter(owner=user, pk=memory_id).delete()
    return deleted > 0


# ---- 問答 ----
def record_qa(user: Any, question: str, answer: str, context: dict[str, Any] | None = None, provider: str = "") -> AssistantMemory | None:
    """留一筆問答（best-effort：沒登入、空回答都略過）；超過上限就淘汰最舊且未評分的。"""
    if not _user_ok(user):
        return None
    question = " ".join((question or "").split())[:QUESTION_MAX_CHARS]
    answer = (answer or "").strip()[:ANSWER_MAX_CHARS]
    if not question or not answer:
        return None
    ctx = context or {}
    keep = {k: ctx.get(k) for k in ("kind", "route", "flow_id", "flow_name", "node_type", "lang") if ctx.get(k)}
    keep["provider"] = provider
    row = AssistantMemory.objects.create(owner=user, kind="qa", text=question, answer=answer, context=keep)
    count = AssistantMemory.objects.filter(owner=user, kind="qa").count()
    if count > MAX_QA:
        victims = AssistantMemory.objects.filter(owner=user, kind="qa", rating=0).order_by("created_at", "id")[: count - MAX_QA]
        AssistantMemory.objects.filter(pk__in=[v.pk for v in victims]).delete()
    return row


def rate(user: Any, memory_id: int, rating: int) -> AssistantMemory | None:
    row = AssistantMemory.objects.filter(owner=user, pk=memory_id).first()
    if row is None:
        return None
    row.rating = max(-1, min(1, int(rating)))
    row.save(update_fields=["rating", "updated_at"])
    return row


def recent_qa(user: Any, limit: int = 30) -> list[AssistantMemory]:
    if not _user_ok(user):
        return []
    return list(AssistantMemory.objects.filter(owner=user, kind="qa").order_by("-created_at", "-id")[:limit])


def similarity(a: str, b: str) -> float:
    """問題相似度：兩邊的檢索 token 集合的 Jaccard（英數整詞＋中文雙字詞，與說明索引同一套）。"""
    from apps.vision.agent.help import tokenize

    ta, tb = set(tokenize(a)), set(tokenize(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def recall(user: Any, question: str, *, limit: int = RECALL_LIMIT, min_sim: float = RECALL_MIN) -> list[tuple[AssistantMemory, float]]:
    """這位使用者評過好的舊問答裡，跟這個問題最像的幾筆（相似度由高到低）；會記下被用到。"""
    if not _user_ok(user) or not (question or "").strip():
        return []
    rows = AssistantMemory.objects.filter(owner=user, kind="qa", rating__gt=0).order_by("-updated_at", "-id")[:MAX_QA]
    scored = [(r, similarity(question, r.text)) for r in rows]
    scored = sorted([x for x in scored if x[1] >= min_sim], key=lambda x: -x[1])[:limit]
    if scored:
        now = timezone.now()
        for r, _ in scored:
            AssistantMemory.objects.filter(pk=r.pk).update(hits=r.hits + 1, last_used_at=now)
    return scored


def examples_text(rows: list[tuple[AssistantMemory, float]]) -> str:
    if not rows:
        return ""
    parts = [f"Q: {r.text}\nA: {r.answer[:800]}" for r, _ in rows]
    return "Previously helpful answers this user rated up (reuse when they fit, adapt when the situation differs):\n" + "\n---\n".join(parts)


def confirmation(kind: str, text: str, deleted: int, lang: str) -> str:
    """「記住／忘記」指令的回覆（依介面語言）。"""
    norm = norm_lang(lang)
    zh_hant, zh_hans = norm == "zh-Hant", norm == "zh-Hans"
    if kind == "remember":
        if zh_hant:
            return f"已記住：{text}\n之後的回答會把它列入考慮；在助手視窗的「記憶」可查看或刪除。"
        if zh_hans:
            return f"已记住：{text}\n之后的回答会把它列入考虑；在助手窗口的「记忆」可查看或删除。"
        return f"Remembered: {text}\nLater answers take it into account; open the assistant's Memory panel to review or delete it."
    if deleted:
        return (f"已忘記 {deleted} 筆含「{text}」的記憶。" if zh_hant else f"已忘记 {deleted} 条含「{text}」的记忆。" if zh_hans else f"Forgot {deleted} memory item(s) containing \"{text}\".")
    return ("沒有含「{0}」的記憶。".format(text) if zh_hant else "没有含「{0}」的记忆。".format(text) if zh_hans else f"No memory item contains \"{text}\".")
