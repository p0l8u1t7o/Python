"""AI 助手的 LLM 供應商：offline（規則引擎）／claude／openai／gemini／openai_compatible（Ollama、vLLM、LM Studio 等本地端點）。

設定解析順序：登入使用者自己的設定（UserPref.agent，各自儲存）→ 伺服器 .env
（VISION_AGENT_PROVIDER / VISION_AGENT_API_KEY / VISION_AGENT_MODEL）→ offline。
金鑰只在伺服器：API 只回「有沒有金鑰＋尾 4 碼」。

各供應商只實作一件事：`complete(settings, system, images, text) -> str`。
claude 走官方 anthropic SDK（可選安裝、延後 import）；openai／gemini 走 REST（標準庫 urllib，零依賴）。
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from django.conf import settings as dj_settings

log = logging.getLogger("vision.agent")

PROVIDERS = ("offline", "claude", "openai", "gemini", "openai_compatible")
#: 各供應商預設模型。供應商會下架舊模型（Gemini 2.0/2.5 flash 已停），404 時 _explain 會提示改用建議名稱。
DEFAULT_MODELS = {"claude": "claude-opus-5", "openai": "gpt-4o", "gemini": "gemini-3.6-flash", "openai_compatible": ""}
MODES = ("single", "agentic")
PROVIDER_LABELS = {"offline": "離線規則引擎", "claude": "Claude（Anthropic）", "openai": "GPT（OpenAI）", "gemini": "Gemini（Google）", "openai_compatible": "OpenAI 相容端點（Ollama／vLLM／LM Studio）"}


@dataclass
class AgentSettings:
    provider: str = "offline"
    model: str = ""
    api_key: str = ""
    #: openai_compatible 專用：例如 http://127.0.0.1:11434/v1（Ollama）。
    base_url: str = ""
    #: user | server | none：設定來自哪裡（回給前端顯示）。
    source: str = "none"
    #: single（一次生成）| agentic（代理迴圈）。
    mode: str = "single"

    @property
    def uses_llm(self) -> bool:
        if self.provider == "offline":
            return False
        if self.provider == "openai_compatible":
            return bool(self.base_url)  # 本地端點通常不需要金鑰
        return bool(self.api_key)

    def public(self) -> dict[str, Any]:
        return {
            "provider": self.provider, "model": self.model or DEFAULT_MODELS.get(self.provider, ""),
            "has_key": bool(self.api_key), "key_hint": f"…{self.api_key[-4:]}" if len(self.api_key) >= 8 else ("…" if self.api_key else ""),
            "source": self.source, "llm": self.uses_llm, "base_url": self.base_url, "mode": self.mode if self.mode in MODES else "single",
        }


def _cfg(key: str, default: Any = "") -> Any:
    return dj_settings.VISION.get(key, default)


def server_settings() -> AgentSettings:
    key = str(_cfg("AGENT_API_KEY") or "")
    base_url = str(_cfg("AGENT_BASE_URL") or "")
    provider = str(_cfg("AGENT_PROVIDER") or ("claude" if key else "openai_compatible" if base_url else "offline"))
    if provider not in PROVIDERS:
        provider = "offline"
    mode = str(_cfg("AGENT_MODE") or "single")
    return AgentSettings(provider=provider, model=str(_cfg("AGENT_MODEL") or ""), api_key=key, base_url=base_url,
                         source="server" if (key or base_url) else "none", mode=mode if mode in MODES else "single")


def user_settings(user: Any) -> AgentSettings | None:
    """登入使用者自己的設定；沒設過回 None。"""
    if user is None:
        return None
    from apps.accounts.models import UserPref

    row = UserPref.objects.filter(user=user).only("agent").first()
    data = dict(row.agent or {}) if row else {}
    if not data:
        return None
    provider = str(data.get("provider") or "offline")
    if provider not in PROVIDERS:
        provider = "offline"
    mode = str(data.get("mode") or "single")
    return AgentSettings(provider=provider, model=str(data.get("model") or ""), api_key=str(data.get("api_key") or ""),
                         base_url=str(data.get("base_url") or ""), source="user", mode=mode if mode in MODES else "single")


def resolve(user: Any) -> AgentSettings:
    """使用者設定優先（明確選 offline 也算），沒設過才用伺服器設定。"""
    mine = user_settings(user)
    if mine is not None:
        return mine
    return server_settings()


def available(s: AgentSettings) -> bool:
    if not s.uses_llm:
        return False
    if s.provider == "claude":
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
    return True


def missing(s: AgentSettings) -> tuple[str, str]:
    """設定還缺什麼：(原因碼, 英文一句話)；都齊了回 ("", "")。"""
    if s.provider == "offline":
        return "", ""
    if s.provider == "openai_compatible":
        if not s.base_url:
            return "no_base_url", "No base URL yet (for example http://127.0.0.1:11434/v1)"
        if not s.model:
            return "no_model", "No model name yet (use List models)"
        return "", ""
    if not s.api_key:
        return "no_key", "No API key yet"
    if s.provider == "claude":
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return "no_package", "The anthropic package is not installed (pip install anthropic)"
    return "", ""


def missing_reason(s: AgentSettings) -> str:
    return missing(s)[1]


def model_of(s: AgentSettings) -> str:
    return s.model or DEFAULT_MODELS.get(s.provider, "")


# ---------------------------------------------------------------------------
# 各供應商
# ---------------------------------------------------------------------------
def _post_json(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float = 120.0) -> dict[str, Any]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - 固定的供應商網址
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from None


#: 生成用的逾時（秒）；連線測試另用短逾時，免得使用者對著轉圈等兩分鐘。
GENERATE_TIMEOUT = 120.0
TEST_TIMEOUT = 15.0


def generate_timeout() -> float:
    """生成用逾時（秒）：VISION_AGENT_TIMEOUT_S，預設 120；本地模型慢可拉長。"""
    try:
        return float(_cfg("AGENT_TIMEOUT_S") or GENERATE_TIMEOUT)
    except (TypeError, ValueError):
        return GENERATE_TIMEOUT


def is_reasoning_model(model: str) -> bool:
    """OpenAI o 系列／gpt-5 系列：只吃 max_completion_tokens，且不接受 temperature 等取樣參數。"""
    return bool(re.match(r"^(o\d|gpt-5)", (model or "").lower()))


def openai_body(model: str, messages: list[dict[str, Any]], *, json_mode: bool = False, max_tokens: int = 8000) -> dict[str, Any]:
    """OpenAI／相容端點的請求 body（純函式，方便測試）。"""
    body: dict[str, Any] = {"model": model, "messages": messages}
    if is_reasoning_model(model):
        body["max_completion_tokens"] = max_tokens
    else:
        body["max_tokens"] = max_tokens
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    return body


def _claude(s: AgentSettings, system: str, images: list[str], text: str, history: list[dict[str, Any]], timeout: float, json_mode: bool = False) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=s.api_key, timeout=timeout, max_retries=1)
    parts: list[dict[str, Any]] = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}} for b64 in images]
    parts.append({"type": "text", "text": text})
    messages = [{"role": "user", "content": parts}, *history]
    response = client.messages.create(
        model=model_of(s), max_tokens=16000,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=messages,
    )
    return next((b.text for b in response.content if b.type == "text"), "")


def _openai_chat(url: str, key: str, model: str, system: str, images: list[str], text: str, history: list[dict[str, Any]],
                 timeout: float, json_mode: bool) -> str:
    content: list[dict[str, Any]] = [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}} for b64 in images]
    content.append({"type": "text", "text": text})
    messages = [{"role": "system", "content": system}, {"role": "user", "content": content}, *history]
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    out = _post_json(url, openai_body(model, messages, json_mode=json_mode), headers, timeout=timeout)
    msg = out["choices"][0]["message"]
    return str(msg.get("content") or "")


def _openai(s: AgentSettings, system: str, images: list[str], text: str, history: list[dict[str, Any]], timeout: float, json_mode: bool = False) -> str:
    return _openai_chat("https://api.openai.com/v1/chat/completions", s.api_key, model_of(s), system, images, text, history, timeout, json_mode)


def compat_url(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + "/" + path.lstrip("/")


def _openai_compatible(s: AgentSettings, system: str, images: list[str], text: str, history: list[dict[str, Any]], timeout: float, json_mode: bool = False) -> str:
    return _openai_chat(compat_url(s.base_url, "chat/completions"), s.api_key, model_of(s), system, images, text, history, timeout, json_mode)


def _gemini(s: AgentSettings, system: str, images: list[str], text: str, history: list[dict[str, Any]], timeout: float, json_mode: bool = False) -> str:
    parts: list[dict[str, Any]] = [{"inline_data": {"mime_type": "image/jpeg", "data": b64}} for b64 in images]
    parts.append({"text": text})
    contents = [{"role": "user", "parts": parts}]
    for turn in history:
        contents.append({"role": "model" if turn["role"] == "assistant" else "user", "parts": [{"text": str(turn["content"])}]})
    gen_cfg: dict[str, Any] = {"maxOutputTokens": 8000}
    if json_mode:
        gen_cfg["responseMimeType"] = "application/json"
    body = {"system_instruction": {"parts": [{"text": system}]}, "contents": contents, "generationConfig": gen_cfg}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_of(s)}:generateContent"
    out = _post_json(url, body, {"x-goog-api-key": s.api_key}, timeout=timeout)
    return "".join(p.get("text", "") for p in out["candidates"][0]["content"]["parts"])


_IMPL = {"claude": _claude, "openai": _openai, "gemini": _gemini, "openai_compatible": _openai_compatible}


def complete(s: AgentSettings, system: str, images: list[str], text: str, history: list[dict[str, Any]] | None = None,
             *, timeout: float | None = None, json_mode: bool = False) -> str:
    """一次對話：system＋（影像 jpeg base64 們＋文字）＋可選的後續回合 → 文字回應。
    json_mode：OpenAI／Gemini 要求 JSON 物件輸出（Claude 沒有此參數，靠 system 指示）。"""
    if s.provider not in _IMPL:
        raise RuntimeError(f"供應商 {s.provider} 不支援 LLM 生成")
    return _IMPL[s.provider](s, system, images, text, history or [], timeout or generate_timeout(), json_mode)


#: 失敗原因碼：訊息本身是英文（產品表面），前端用 `agent.reason.<code>` 翻成介面語言。
#: 新增一個碼要同步三語系字典與 docs/agent.html。
REASON_CODES = (
    "no_package", "no_key", "no_base_url", "no_model",           # 還沒設定完
    "bad_key", "forbidden", "bad_model", "no_credit", "rate_limit",  # 供應商拒絕
    "overloaded", "timeout", "network", "unknown",                # 暫時性
)


def explain(exc: BaseException, timeout: float = TEST_TIMEOUT) -> tuple[str, str]:
    """把供應商例外翻成 (原因碼, 英文一句話)。timeout 用來寫進逾時訊息（連線測試 15 秒、生成可到 120 秒）。"""
    msg = str(exc)
    low = msg.lower()
    detail = msg[:160]
    if isinstance(exc, ImportError):
        return "no_package", "The anthropic package is not installed (pip install anthropic)"
    if "503" in msg or "high demand" in low or "overloaded" in low or "unavailable" in low:
        return "overloaded", "The provider is overloaded (503). Try again shortly, or pick another model"
    if "401" in msg or "authentication" in low or "invalid x-api-key" in low or "api key not valid" in low or "incorrect api key" in low:
        return "bad_key", f"The API key was rejected: {detail}"
    if "403" in msg or "permission" in low:
        return "forbidden", f"This key is not allowed to use it: {detail}"
    if "404" in msg or "not_found" in low or "model" in low and ("not found" in low or "does not exist" in low or "no longer available" in low):
        hint = re.search(r"use models/([\w.\-]+)", msg)
        suggested = f"; the provider suggests {hint.group(1)}" if hint else ""
        return "bad_model", f"That model does not exist, is retired, or is not available to this key{suggested}: {msg[:140]}"
    # 額度用完與速率限制都是 429，但要做的事完全不同（儲值 vs 等一下再試）
    if "no credits" in low or "insufficient_quota" in low or "insufficient quota" in low or "exceeded your current quota" in low or "billing" in low or "credit balance" in low:
        return "no_credit", f"The account has no credit left: top it up with the provider, then try again ({detail})"
    if "429" in msg or "rate" in low and "limit" in low:
        return "rate_limit", f"Too many requests for now (rate limit): wait a moment and try again ({detail})"
    if "timed out" in low or "timeout" in low:
        return "timeout", f"No answer from the provider within {int(timeout)} s: the model may be busy, or the network or proxy is in the way"
    if "urlopen error" in low or "name or service not known" in low or "getaddrinfo" in low or "connection" in low:
        return "network", f"Cannot reach the provider: {detail}"
    return "unknown", msg[:200] or exc.__class__.__name__


def _explain(exc: BaseException, timeout: float = TEST_TIMEOUT) -> str:
    """只要訊息（流程／助手的警告字串用）。"""
    return explain(exc, timeout)[1]


def _get_json(url: str, headers: dict[str, str], timeout: float) -> dict[str, Any]:
    req = urllib.request.Request(url, method="GET", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - 固定的供應商網址
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:500]}") from None


def list_models(s: AgentSettings) -> dict[str, Any]:
    """列出這把金鑰能用的模型名（給設定視窗選）。回 {ok, models:[...], reason}。"""
    if s.provider == "offline":
        return {"ok": True, "models": [], "reason": "", "reason_code": ""}
    code, reason = missing(s)
    if code:
        return {"ok": False, "models": [], "reason": reason, "reason_code": code}
    try:
        if s.provider == "claude":
            import anthropic

            client = anthropic.Anthropic(api_key=s.api_key, timeout=TEST_TIMEOUT, max_retries=1)
            names = [m.id for m in client.models.list()]
        elif s.provider == "openai":
            out = _get_json("https://api.openai.com/v1/models", {"Authorization": f"Bearer {s.api_key}"}, TEST_TIMEOUT)
            names = sorted(m["id"] for m in out.get("data", []) if any(t in m["id"] for t in ("gpt", "o1", "o3", "o4")))
        elif s.provider == "openai_compatible":
            headers = {"Authorization": f"Bearer {s.api_key}"} if s.api_key else {}
            out = _get_json(compat_url(s.base_url, "models"), headers, TEST_TIMEOUT)
            names = sorted(str(m.get("id") or m.get("name") or "") for m in out.get("data", []) if isinstance(m, dict))
        else:  # gemini：只留支援 generateContent 的
            out = _get_json("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200", {"x-goog-api-key": s.api_key}, TEST_TIMEOUT)
            names = [m["name"].removeprefix("models/") for m in out.get("models", []) if "generateContent" in (m.get("supportedGenerationMethods") or [])]
    except Exception as exc:  # noqa: BLE001
        code, reason = explain(exc)
        return {"ok": False, "models": [], "reason": reason, "reason_code": code}
    return {"ok": True, "models": names[:60], "reason": "", "reason_code": ""}


def test_connection(s: AgentSettings) -> dict[str, Any]:
    """打一個最小請求驗證設定；回 {ok, provider, model, latency_ms, reply, reason}。"""
    import time

    base = {"provider": s.provider, "model": model_of(s), "source": s.source}
    if s.provider == "offline":
        return {**base, "ok": True, "latency_ms": 0, "reply": "", "reason": "", "reason_code": ""}
    code, reason = missing(s)
    if code:
        return {**base, "ok": False, "latency_ms": 0, "reply": "", "reason": reason, "reason_code": code}
    t0 = time.perf_counter()
    try:
        reply = complete(s, "你是連線測試。只回覆兩個字母：OK", [], "ping", timeout=TEST_TIMEOUT)
    except Exception as exc:  # noqa: BLE001 - 任何失敗都要翻成原因回前端
        log.warning("agent 供應商連線測試失敗（%s）：%s", s.provider, exc)
        code, reason = explain(exc, TEST_TIMEOUT)
        return {**base, "ok": False, "latency_ms": round((time.perf_counter() - t0) * 1000), "reply": "", "reason": reason, "reason_code": code}
    return {**base, "ok": True, "latency_ms": round((time.perf_counter() - t0) * 1000), "reply": reply.strip()[:80], "reason": "", "reason_code": ""}


# ---------------------------------------------------------------------------
# 工具呼叫（代理迴圈用）：中立歷史格式 → 各供應商原生格式
#
# 中立歷史：
#   {"role": "user", "content": [{"type": "text", "text": ...} | {"type": "image", "data": b64jpeg}, ...]}
#   {"role": "assistant", "content": "文字", "tool_calls": [{"id", "name", "args"}]}
#   {"role": "tool", "tool_call_id", "name", "content": "JSON 文字"}
# 工具規格：{"name", "description", "input_schema"}（JSON Schema 子集：type/properties/required/items/enum/description）。
# tool_choice 一律 auto（新模型強制指定會 400）。
# ---------------------------------------------------------------------------
@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class ToolReply:
    text: str
    calls: list[ToolCall]
    #: 供應商原生的回覆片段（Gemini 3 的 functionCall 帶 thoughtSignature，下一回合必須原樣回傳，否則 400）。
    raw: Any = None


def _parse_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            out = json.loads(raw)
            return out if isinstance(out, dict) else {"value": out}
        except ValueError:
            return {"_raw": raw}
    return {}


def claude_messages(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """中立歷史 → Claude messages（連續的 tool 回合合併成一則 user 訊息）。"""
    out: list[dict[str, Any]] = []
    for turn in history:
        role = turn["role"]
        if role == "user":
            blocks = []
            for part in turn["content"]:
                if part.get("type") == "image":
                    blocks.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": part["data"]}})
                else:
                    blocks.append({"type": "text", "text": str(part.get("text", ""))})
            out.append({"role": "user", "content": blocks})
        elif role == "assistant":
            blocks = []
            if turn.get("content"):
                blocks.append({"type": "text", "text": str(turn["content"])})
            for c in turn.get("tool_calls") or []:
                blocks.append({"type": "tool_use", "id": c["id"], "name": c["name"], "input": c.get("args") or {}})
            out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": "（無）"}]})
        else:
            block = {"type": "tool_result", "tool_use_id": turn["tool_call_id"], "content": str(turn.get("content", ""))}
            if out and out[-1]["role"] == "user" and out[-1]["content"] and out[-1]["content"][0].get("type") == "tool_result":
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
    return out


def parse_claude_reply(blocks: list[Any]) -> ToolReply:
    text, calls = [], []
    for b in blocks:
        btype = getattr(b, "type", None) or (b.get("type") if isinstance(b, dict) else None)
        if btype == "text":
            text.append(getattr(b, "text", None) or (b.get("text") if isinstance(b, dict) else ""))
        elif btype == "tool_use":
            get = (lambda k: getattr(b, k)) if not isinstance(b, dict) else (lambda k: b.get(k))
            calls.append(ToolCall(str(get("id")), str(get("name")), _parse_args(get("input"))))
    return ToolReply("".join(t for t in text if t), calls)


def _claude_tools(s: AgentSettings, system: str, history: list[dict[str, Any]], tools: list[dict[str, Any]], timeout: float) -> ToolReply:
    import anthropic

    client = anthropic.Anthropic(api_key=s.api_key, timeout=timeout, max_retries=1)
    response = client.messages.create(
        model=model_of(s), max_tokens=8000,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        tools=[{"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]} for t in tools],
        messages=claude_messages(history),
    )
    return parse_claude_reply(list(response.content))


def openai_messages(system: str, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for turn in history:
        role = turn["role"]
        if role == "user":
            content = []
            for part in turn["content"]:
                if part.get("type") == "image":
                    content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{part['data']}"}})
                else:
                    content.append({"type": "text", "text": str(part.get("text", ""))})
            out.append({"role": "user", "content": content})
        elif role == "assistant":
            msg: dict[str, Any] = {"role": "assistant", "content": str(turn.get("content") or "") or None}
            calls = turn.get("tool_calls") or []
            if calls:
                msg["tool_calls"] = [{"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c.get("args") or {}, ensure_ascii=False)}} for c in calls]
            out.append(msg)
        else:
            out.append({"role": "tool", "tool_call_id": turn["tool_call_id"], "content": str(turn.get("content", ""))})
    return out


def parse_openai_reply(msg: dict[str, Any]) -> ToolReply:
    calls = []
    for i, c in enumerate(msg.get("tool_calls") or []):
        fn = c.get("function") or {}
        calls.append(ToolCall(str(c.get("id") or f"call_{i}"), str(fn.get("name", "")), _parse_args(fn.get("arguments"))))
    return ToolReply(str(msg.get("content") or ""), calls)


def _openai_tools_at(url: str, key: str, model: str, system: str, history: list[dict[str, Any]], tools: list[dict[str, Any]], timeout: float) -> ToolReply:
    body = openai_body(model, openai_messages(system, history))
    body["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}} for t in tools]
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    out = _post_json(url, body, headers, timeout=timeout)
    return parse_openai_reply(out["choices"][0]["message"])


def _openai_tools(s: AgentSettings, system: str, history: list[dict[str, Any]], tools: list[dict[str, Any]], timeout: float) -> ToolReply:
    return _openai_tools_at("https://api.openai.com/v1/chat/completions", s.api_key, model_of(s), system, history, tools, timeout)


def _compat_tools(s: AgentSettings, system: str, history: list[dict[str, Any]], tools: list[dict[str, Any]], timeout: float) -> ToolReply:
    return _openai_tools_at(compat_url(s.base_url, "chat/completions"), s.api_key, model_of(s), system, history, tools, timeout)


def _gemini_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Gemini 的 parameters 只吃 OpenAPI 子集：去掉空 properties／required、遞迴整理。"""
    out: dict[str, Any] = {}
    for k, v in schema.items():
        if k == "properties" and isinstance(v, dict):
            props = {pk: _gemini_schema(pv) for pk, pv in v.items()}
            if props:
                out["properties"] = props
        elif k == "items" and isinstance(v, dict):
            out["items"] = _gemini_schema(v)
        elif k == "required":
            if v:
                out["required"] = list(v)
        elif k in ("type", "description", "enum"):
            out[k] = v
    if out.get("type") == "object" and "properties" not in out:
        out["properties"] = {"_": {"type": "string", "description": "未使用"}}
    return out


def gemini_contents(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for turn in history:
        role = turn["role"]
        if role == "user":
            parts = []
            for part in turn["content"]:
                if part.get("type") == "image":
                    parts.append({"inline_data": {"mime_type": "image/jpeg", "data": part["data"]}})
                else:
                    parts.append({"text": str(part.get("text", ""))})
            out.append({"role": "user", "parts": parts})
        elif role == "assistant":
            raw = turn.get("raw")
            if isinstance(raw, list) and raw:
                out.append({"role": "model", "parts": raw})  # 原樣回傳（含 thoughtSignature）
                continue
            parts = []
            if turn.get("content"):
                parts.append({"text": str(turn["content"])})
            for c in turn.get("tool_calls") or []:
                parts.append({"functionCall": {"name": c["name"], "args": c.get("args") or {}}})
            out.append({"role": "model", "parts": parts or [{"text": "（無）"}]})
        else:
            try:
                payload = json.loads(str(turn.get("content", "")))
            except ValueError:
                payload = {"text": str(turn.get("content", ""))}
            if not isinstance(payload, dict):
                payload = {"result": payload}
            part = {"functionResponse": {"name": turn.get("name", ""), "response": payload}}
            if out and out[-1]["role"] == "user" and out[-1]["parts"] and "functionResponse" in out[-1]["parts"][0]:
                out[-1]["parts"].append(part)
            else:
                out.append({"role": "user", "parts": [part]})
    return out


def parse_gemini_reply(candidate: dict[str, Any]) -> ToolReply:
    text, calls = [], []
    parts = list((candidate.get("content") or {}).get("parts") or [])
    for i, part in enumerate(parts):
        if "functionCall" in part:
            fc = part["functionCall"] or {}
            calls.append(ToolCall(f"{fc.get('name', 'call')}_{i}", str(fc.get("name", "")), _parse_args(fc.get("args"))))
        elif part.get("text"):
            text.append(str(part["text"]))
    keep = [p for p in parts if isinstance(p, dict) and ("functionCall" in p or p.get("text") or p.get("thoughtSignature"))]
    return ToolReply("".join(text), calls, raw=keep or None)


def _gemini_tools(s: AgentSettings, system: str, history: list[dict[str, Any]], tools: list[dict[str, Any]], timeout: float) -> ToolReply:
    body = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": gemini_contents(history),
        "tools": [{"functionDeclarations": [{"name": t["name"], "description": t["description"], "parameters": _gemini_schema(t["input_schema"])} for t in tools]}],
        "generationConfig": {"maxOutputTokens": 8000},
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_of(s)}:generateContent"
    out = _post_json(url, body, {"x-goog-api-key": s.api_key}, timeout=timeout)
    return parse_gemini_reply(out["candidates"][0])


_TOOL_IMPL = {"claude": _claude_tools, "openai": _openai_tools, "gemini": _gemini_tools, "openai_compatible": _compat_tools}


def complete_tools(s: AgentSettings, system: str, history: list[dict[str, Any]], tools: list[dict[str, Any]], *, timeout: float | None = None) -> ToolReply:
    """一回合工具呼叫對話：回模型文字＋要執行的工具呼叫（可能為空＝模型認為講完了）。"""
    if s.provider not in _TOOL_IMPL:
        raise RuntimeError(f"供應商 {s.provider} 不支援工具呼叫")
    return _TOOL_IMPL[s.provider](s, system, history, tools, timeout or generate_timeout())
