"""對話代理：工具呼叫迴圈。

流程與護欄
----------
1. 系統提示詞明確禁止 LLM 自行計算或估算任何數值
2. LLM 決定要呼叫哪些工具 → 由本模組執行（工具直接打服務層）
3. 工具結果回填 → LLM 組成人話
4. 迴圈上限 ``max_turns``，避免無限工具呼叫
5. 回傳值一併帶出「本次用了哪些工具、引用了哪些批次」，前端會顯示出來——
   工程師看得到答案是怎麼來的才會採信
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict, field

from ..logging_setup import get_logger
from .provider import LLMProvider, TemplateProvider, make_provider
from .tools import TOOL_SPECS, dispatch_tool

log = get_logger(__name__)

SYSTEM_PROMPT = """你是「高純銦金屬偏析純化製程分析平台」的技術助理，服務對象是製程工程師與專案經理。

## 絕對規則（違反會導致錯誤決策）

1. **你不做任何計算。** 回答中出現的每一個數字，都必須逐字取自工具回傳的結果。
   不准心算、不准估算、不准內插、不准把百分比換算成別的單位再重算。
   工具沒給的數字就說「目前沒有這項資料」，並建議該呼叫哪個功能取得。
2. **先查再答。** 任何涉及批次、k_eff、得料率、參數建議的問題，一律先呼叫工具。
   即使你覺得自己知道答案也一樣。
3. **標明來源。** 提到具體數字時，附上批次編號與製程條件；工具回傳的 `_source`
   欄位說明了該數字的計算方式，必要時據實轉述。
4. **不確定就說不確定。** 工具回傳的 warnings、note、in_training_range=false、
   信賴區間很寬——這些都要主動告訴使用者，不可略過。
5. **不做設備控制建議。** 本系統是離線決策輔助工具，不涉及閉迴路控制。
   使用者若問「能不能自動調機台」，說明本案範圍不含設備控制。

## 領域背景（回答時的用語與判讀依據）

- k_eff 是有效分配係數：**越低代表偏析純化效果越好**。
  k<0.15 易去除、0.15~0.4 中等、0.4~0.75 困難、>0.75 幾乎無法用偏析法去除。
- 熔區移動速率 v 越快，k_eff 越接近 1、純化效果越差。這是本製程的核心取捨：
  慢＝純，快＝產能。
- 6N = 總雜質 < 1 ppm。得料率是「從頭端算起連續合格的長度佔全錠的比例」。
- 頭端最乾淨、尾端是雜質濃縮區。
- 低於檢測極限的測值是左設限資料，系統已用 Tobit likelihood 處理，
  不是當成 0 也不是當成 LOD。

## 回答風格

- 繁體中文，簡潔，先給結論再給依據。
- 數字用表格或條列，不要塞在長句子裡。
- 若使用者問的是「為什麼」，先用模型量化「製程參數能解釋多少」，
  再指出剩下無法解釋的部分該往哪查。
"""


@dataclass
class AssistantReply:
    answer: str
    provider: str
    tools_used: list[str] = field(default_factory=list)
    tool_results: list[dict] = field(default_factory=list)
    cited_batches: list[str] = field(default_factory=list)
    turns: int = 0
    degraded: bool = False
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class AssistantAgent:
    def __init__(self, service, provider: LLMProvider | None = None,
                 max_turns: int = 6):
        self.service = service
        self.provider = provider or make_provider(service)
        self.max_turns = max_turns

    def ask(self, question: str, history: list[dict] | None = None) -> AssistantReply:
        """回答一個問題。history 為先前的 {role, content} 訊息（純文字）。"""
        messages: list[dict] = []
        for h in (history or [])[-8:]:
            if h.get("role") in ("user", "assistant") and isinstance(h.get("content"), str):
                messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": question})

        tools_used: list[str] = []
        tool_results: list[dict] = []
        provider = self.provider

        try:
            for turn in range(1, self.max_turns + 1):
                resp = provider.chat(SYSTEM_PROMPT, messages, TOOL_SPECS)

                if not resp.tool_calls:
                    return self._finish(resp.text, provider, tools_used,
                                        tool_results, turn)

                if isinstance(provider, TemplateProvider):
                    call = resp.tool_calls[0]
                    result = dispatch_tool(call["name"], call["arguments"], self.service)
                    tools_used.append(call["name"])
                    tool_results.append({"tool": call["name"],
                                         "arguments": call["arguments"],
                                         "result": result})
                    return self._finish(TemplateProvider.render(call["name"], result),
                                        provider, tools_used, tool_results, turn,
                                        degraded=True)

                messages.append(resp.raw_assistant_message)
                for call in resp.tool_calls:
                    result = dispatch_tool(call["name"], call["arguments"], self.service)
                    tools_used.append(call["name"])
                    tool_results.append({"tool": call["name"],
                                         "arguments": call["arguments"],
                                         "result": result})
                    messages.append(provider.tool_result_message(
                        call["id"], call["name"], result))

            return self._finish(
                "已達到工具呼叫次數上限仍未得出結論。請把問題拆得更具體一些，"
                "例如指定批次編號或元素。",
                provider, tools_used, tool_results, self.max_turns)

        except (RuntimeError, ValueError, KeyError) as exc:
            log.warning("LLM 路徑失敗（%s），退回本地模板模式", exc)
            fallback = TemplateProvider(self.service)
            resp = fallback.chat(SYSTEM_PROMPT, messages, TOOL_SPECS)
            call = resp.tool_calls[0]
            result = dispatch_tool(call["name"], call["arguments"], self.service)
            reply = self._finish(TemplateProvider.render(call["name"], result),
                                 fallback, tools_used + [call["name"]],
                                 tool_results + [{"tool": call["name"],
                                                  "arguments": call["arguments"],
                                                  "result": result}],
                                 1, degraded=True)
            reply.error = f"外部 LLM 無法使用（{exc}），已自動退回本地模板模式。"
            return reply

    # ── 內部 ────────────────────────────────────────────────────
    def _finish(self, answer: str, provider, tools_used, tool_results,
                turns: int, degraded: bool = False) -> AssistantReply:
        cited = sorted({m for r in tool_results
                        for m in re.findall(r"[A-Za-z]{2,4}-\d{3,6}",
                                            str(r.get("result", ""))[:20000])}
                       & set(self._known_batch_ids()))
        return AssistantReply(
            answer=answer or "（模型沒有回覆內容）",
            provider=provider.name,
            tools_used=list(dict.fromkeys(tools_used)),
            tool_results=tool_results,
            cited_batches=cited,
            turns=turns,
            degraded=degraded or provider.name == "template",
        )

    def _known_batch_ids(self) -> set[str]:
        try:
            return {b.batch_id for b in self.service.repo.list_batches()}
        except (RuntimeError, ValueError):
            return set()
