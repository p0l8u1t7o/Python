"""L5 — LLM 自然語言查詢與報告生成層。

**LLM 不做任何計算。**

    使用者提問
        ↓
    LLM 解讀意圖 → 轉成對資料庫/模型的工具呼叫
        ↓
    物理模型 + GP 算出數字  ← 所有數字只從這裡來
        ↓
    LLM 把數字組織成人話
        ↓
    回答（附上引用的批次 ID 與參數）

準確度風險為零，因為它根本不碰計算。它負責的是「翻譯」。
"""

from .provider import LLMProvider, ProviderResponse, make_provider
from .tools import TOOL_SPECS, dispatch_tool
from .agent import AssistantAgent, AssistantReply

__all__ = [
    "LLMProvider", "ProviderResponse", "make_provider",
    "TOOL_SPECS", "dispatch_tool",
    "AssistantAgent", "AssistantReply",
]
