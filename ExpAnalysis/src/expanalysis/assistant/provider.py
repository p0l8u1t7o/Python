"""LLM 供應商抽象層。

三種實作
--------
  anthropic  呼叫 Anthropic Messages API（原生 tool use）
  openai     呼叫 OpenAI Chat Completions（function calling）
  template   完全本地的規則式回覆，不呼叫任何外部服務

為什麼一定要有 template
-----------------------
demo 現場沒網路、客戶端資安不允許外連、API key 過期——這三件事都會發生。
未設定金鑰時自動退回 template 模式，介面照常運作、數字完全正確，只是
措辭比較制式。**寧可句子生硬，也不要在客戶面前開天窗。**

安全設計
--------
  * 逾時、重試、指數退避都在這一層處理，上層只看到成功或明確的失敗
  * 只送出工具回傳的結構化資料，不送原始資料庫內容
  * API key 只從環境變數讀取，永遠不寫進 log 或回傳給前端
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import httpx

from ..config import SETTINGS
from ..logging_setup import get_logger

log = get_logger(__name__)


@dataclass
class ProviderResponse:
    """一輪 LLM 回應。tool_calls 非空時代表模型要求呼叫工具。"""

    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)   # [{id, name, arguments}]
    raw_assistant_message: object = None
    stop_reason: str = ""
    usage: dict = field(default_factory=dict)


class LLMProvider:
    name = "base"
    supports_tools = False

    def chat(self, system: str, messages: list[dict],
             tools: list[dict] | None = None) -> ProviderResponse:
        raise NotImplementedError

    @staticmethod
    def tool_result_message(tool_use_id: str, name: str, content: dict) -> dict:
        raise NotImplementedError


# ─────────────────────────────────────────────────────────────────
#  Anthropic
# ─────────────────────────────────────────────────────────────────
class AnthropicProvider(LLMProvider):
    name = "anthropic"
    supports_tools = True

    def __init__(self, api_key: str, model: str, timeout_s: float = 60.0):
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s

    def chat(self, system, messages, tools=None) -> ProviderResponse:
        payload = {
            "model": self.model,
            "max_tokens": 2048,
            "system": system,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools

        data = _post_with_retry(
            "https://api.anthropic.com/v1/messages", payload, self.timeout_s,
            headers={"x-api-key": self.api_key,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
        )

        text_parts, tool_calls = [], []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block["text"])
            elif block.get("type") == "tool_use":
                tool_calls.append({"id": block["id"], "name": block["name"],
                                   "arguments": block.get("input", {})})
        return ProviderResponse(
            text="\n".join(text_parts).strip(),
            tool_calls=tool_calls,
            raw_assistant_message={"role": "assistant", "content": data.get("content", [])},
            stop_reason=data.get("stop_reason", ""),
            usage=data.get("usage", {}),
        )

    @staticmethod
    def tool_result_message(tool_use_id, name, content) -> dict:
        return {"role": "user", "content": [{
            "type": "tool_result", "tool_use_id": tool_use_id,
            "content": json.dumps(content, ensure_ascii=False, default=_json_default),
        }]}


# ─────────────────────────────────────────────────────────────────
#  OpenAI
# ─────────────────────────────────────────────────────────────────
class OpenAIProvider(LLMProvider):
    name = "openai"
    supports_tools = True

    def __init__(self, api_key: str, model: str, base_url: str, timeout_s: float = 60.0):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def chat(self, system, messages, tools=None) -> ProviderResponse:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}] + messages,
            "max_tokens": 2048,
        }
        if tools:
            payload["tools"] = [{
                "type": "function",
                "function": {"name": t["name"], "description": t["description"],
                             "parameters": t["input_schema"]},
            } for t in tools]

        data = _post_with_retry(
            f"{self.base_url}/chat/completions", payload, self.timeout_s,
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
        )
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message", {}) or {}
        calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            try:
                arguments = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                arguments = {}
            calls.append({"id": tc.get("id", ""), "name": fn.get("name", ""),
                          "arguments": arguments})
        return ProviderResponse(
            text=(msg.get("content") or "").strip(),
            tool_calls=calls,
            raw_assistant_message=msg,
            stop_reason=choice.get("finish_reason", ""),
            usage=data.get("usage", {}),
        )

    @staticmethod
    def tool_result_message(tool_use_id, name, content) -> dict:
        return {"role": "tool", "tool_call_id": tool_use_id, "name": name,
                "content": json.dumps(content, ensure_ascii=False, default=_json_default)}


# ─────────────────────────────────────────────────────────────────
#  本地模板（無外部相依）
# ─────────────────────────────────────────────────────────────────
class TemplateProvider(LLMProvider):
    """規則式回覆。不呼叫外部服務，離線可用，數字完全正確。

    運作方式：用關鍵字判斷意圖 → 直接指定要呼叫哪個工具 → 由 agent 執行 →
    再由 ``render`` 把結構化結果組成中文句子。**這一層也不做任何計算。**
    """

    name = "template"
    supports_tools = True

    # 順序即優先度：越具體的意圖放越前面，避免被泛用關鍵字（例如「參數」）攔截。
    _INTENTS: list[tuple[tuple[str, ...], str]] = [
        (("下一批", "接下來", "該跑", "實驗設計", "doe", "省批"), "suggest_next_experiments"),
        (("異常", "有問題", "不對", "重測", "稽核", "髒資料"), "get_anomalies"),
        (("多準", "誤差", "驗證", "交叉", "可信", "準確"), "get_validation"),
        (("關鍵參數", "哪個參數", "影響多大", "敏感", "映射", "k0", "分配係數",
          "delta", "δ"), "get_parameter_mapping"),
        (("為什麼", "差異", "比較", "比上", "跟上一批", " vs "), "compare_batches"),
        (("建議", "最佳", "最適", "怎麼設", "怎麼調", "最佳化"), "recommend_parameters"),
        (("預測", "模擬", "如果", "假設", "會怎樣"), "predict_profile"),
        (("這批", "批次詳情", "看一下批"), "get_batch"),
        (("批次", "列出", "清單", "哪些批"), "list_batches"),
    ]

    def __init__(self, service=None):
        self.service = service

    def chat(self, system, messages, tools=None) -> ProviderResponse:
        user_text = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                c = m.get("content")
                user_text = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
                break
        low = user_text.lower()

        for keys, tool in self._INTENTS:
            if any(k in low for k in keys):
                return ProviderResponse(
                    text="", stop_reason="tool_use",
                    tool_calls=[{"id": "tpl-1", "name": tool,
                                 "arguments": self._args_for(tool, user_text)}],
                )
        return ProviderResponse(
            text="", stop_reason="tool_use",
            tool_calls=[{"id": "tpl-1", "name": "get_overview", "arguments": {}}],
        )

    def _args_for(self, tool: str, text: str) -> dict:
        import re
        ids = re.findall(r"[A-Za-z]{2,4}-\d{3,6}", text)
        if tool == "compare_batches" and len(ids) >= 2:
            return {"batch_id_a": ids[0], "batch_id_b": ids[1]}
        if tool == "compare_batches" and len(ids) == 1 and self.service is not None:
            all_ids = [b.batch_id for b in self.service.repo.list_batches()]
            if ids[0] in all_ids:
                i = all_ids.index(ids[0])
                if i > 0:
                    return {"batch_id_a": all_ids[i - 1], "batch_id_b": ids[0]}
            return {"batch_id_a": ids[0], "batch_id_b": ids[0]}
        if tool == "get_batch" and ids:
            return {"batch_id": ids[0]}
        if tool == "get_parameter_mapping":
            for el in SETTINGS.elements:
                if el.lower() in text.lower():
                    return {"element": el}
            return {"element": SETTINGS.elements[0]}
        if tool == "predict_profile":
            nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", text)]
            return {"speed_mm_hr": nums[0] if nums else 2.0,
                    "temp_c": nums[1] if len(nums) > 1 else 185.0,
                    "n_passes": int(nums[2]) if len(nums) > 2 else 8}
        return {}

    @staticmethod
    def tool_result_message(tool_use_id, name, content) -> dict:
        return {"role": "user", "content": json.dumps(
            {"tool": name, "result": content}, ensure_ascii=False, default=_json_default)}

    @staticmethod
    def render(tool_name: str, result: dict) -> str:
        """把工具結果組成中文回答。所有數字直接取自 result，不做任何運算。"""
        from .templates import render_tool_result
        return render_tool_result(tool_name, result)


# ─────────────────────────────────────────────────────────────────
def _json_default(o):
    import numpy as np
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def _post_with_retry(url: str, payload: dict, timeout_s: float,
                     headers: dict, max_attempts: int = 3) -> dict:
    """帶指數退避的 POST。429 與 5xx 重試，4xx（除 429）直接失敗。"""
    delay = 1.0
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            with httpx.Client(timeout=timeout_s) as client:
                r = client.post(url, json=payload, headers=headers)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429 or r.status_code >= 500:
                last_exc = RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
                log.warning("LLM API 第 %d 次嘗試失敗（%s），%.1f 秒後重試",
                            attempt, r.status_code, delay)
            else:
                raise RuntimeError(f"LLM API 回應 HTTP {r.status_code}：{r.text[:300]}")
        except httpx.HTTPError as exc:
            last_exc = exc
            log.warning("LLM API 連線失敗（%s），%.1f 秒後重試", exc, delay)
        if attempt < max_attempts:
            time.sleep(delay)
            delay *= 2
    raise RuntimeError(f"LLM API 連續 {max_attempts} 次失敗：{last_exc}")


def make_provider(service=None, provider: str | None = None) -> LLMProvider:
    """依設定建立供應商。金鑰缺失或設定不明時一律退回 template。"""
    name = (provider or SETTINGS.llm_provider or "template").lower()
    if name == "anthropic" and SETTINGS.anthropic_api_key:
        return AnthropicProvider(SETTINGS.anthropic_api_key,
                                 SETTINGS.anthropic_model, SETTINGS.llm_timeout_s)
    if name == "openai" and SETTINGS.openai_api_key:
        return OpenAIProvider(SETTINGS.openai_api_key, SETTINGS.openai_model,
                              SETTINGS.openai_base_url, SETTINGS.llm_timeout_s)
    if name in ("anthropic", "openai"):
        log.warning("LLM provider 設為 %s 但未提供 API key，改用本地模板模式", name)
    return TemplateProvider(service)
