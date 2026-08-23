"""AI 助理端點。"""

from __future__ import annotations

from fastapi import APIRouter

from ...assistant.agent import AssistantAgent
from ...assistant.provider import make_provider
from ...config import SETTINGS
from ...logging_setup import get_logger
from ...service import get_service
from ..schemas import ChatRequest

log = get_logger(__name__)
router = APIRouter(prefix="/api/assistant", tags=["assistant"])


@router.get("/status")
def status():
    """回報目前實際使用的 provider。金鑰**不會**外洩，只回報有沒有設定。"""
    svc = get_service()
    provider = make_provider(svc)
    return {
        "configured_provider": SETTINGS.llm_provider,
        "active_provider": provider.name,
        "anthropic_key_present": bool(SETTINGS.anthropic_api_key),
        "openai_key_present": bool(SETTINGS.openai_api_key),
        "model": (SETTINGS.anthropic_model if provider.name == "anthropic"
                  else SETTINGS.openai_model if provider.name == "openai" else None),
        "degraded": provider.name == "template",
        "note": ("目前為本地模板模式：未設定 API 金鑰時自動退回，介面照常運作、"
                 "數字完全正確，只是措辭較制式。在 .env 填入 "
                 "EXPA_ANTHROPIC_API_KEY 或 EXPA_OPENAI_API_KEY 即可切換。"
                 if provider.name == "template" else
                 "LLM 只負責把工具算出來的數字組織成人話，不參與任何計算。"),
    }


@router.post("/chat")
def chat(req: ChatRequest):
    svc = get_service()
    agent = AssistantAgent(svc, provider=make_provider(svc, req.provider))
    reply = agent.ask(req.question, [m.model_dump() for m in req.history])
    return reply.to_dict()


@router.get("/suggested-questions")
def suggested_questions():
    """給前端顯示的起手式問題。會依目前資料動態帶入實際批次編號。"""
    svc = get_service()
    ids = [b.batch_id for b in svc.repo.list_batches()]
    qs = [
        "整體資料狀況如何？各元素的偏析可去除性排序是什麼？",
        "哪個製程參數對純化效率影響最大？請用數字說明。",
        "請給我可以直接下給產線的參數建議，並說明風險。",
        "下一批實驗該跑什麼條件？為什麼？",
        "有哪些批次的資料看起來有問題？該怎麼處理？",
        "模型到底多準？AI 有沒有真的幫上忙？",
        "純化次數做到第幾次之後就沒有意義了？",
    ]
    if len(ids) >= 2:
        qs.insert(2, f"{ids[1]} 的 Cu 為什麼比 {ids[0]} 差？")
    return {"questions": qs}
