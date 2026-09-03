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
            "source": self.source, "llm": self.uses_llm, "base_url": self.base_url,
        }


def _cfg(key: str, default: Any = "") -> Any:
    return dj_settings.VISION.get(key, default)


def server_settings() -> AgentSettings:
    key = str(_cfg("AGENT_API_KEY") or "")
    base_url = str(_cfg("AGENT_BASE_URL") or "")
    provider = str(_cfg("AGENT_PROVIDER") or ("claude" if key else "openai_compatible" if base_url else "offline"))
    if provider not in PROVIDERS:
        provider = "offline"
    return AgentSettings(provider=provider, model=str(_cfg("AGENT_MODEL") or ""), api_key=key, base_url=base_url,
                         source="server" if (key or base_url) else "none")


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
    return AgentSettings(provider=provider, model=str(data.get("model") or ""), api_key=str(data.get("api_key") or ""),
                         base_url=str(data.get("base_url") or ""), source="user")


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


def missing_reason(s: AgentSettings) -> str:
    if s.provider == "offline":
        return ""
    if s.provider == "openai_compatible":
        if not s.base_url:
            return "未填 base URL（例如 http://127.0.0.1:11434/v1）"
        if not s.model:
            return "未填模型名稱（可按「列出可用模型」）"
        return ""
    if not s.api_key:
        return "未填 API 金鑰"
    if s.provider == "claude":
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return "尚未安裝 anthropic 套件（pip install anthropic）"
    return ""


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


def _explain(exc: BaseException, timeout: float = TEST_TIMEOUT) -> str:
    """把供應商例外翻成使用者看得懂的一句話。timeout 用來寫進逾時訊息（連線測試 15 秒、生成可到 120 秒）。"""
    msg = str(exc)
    low = msg.lower()
    if isinstance(exc, ImportError):
        return "尚未安裝 anthropic 套件（pip install anthropic）"
    if "503" in msg or "high demand" in low or "overloaded" in low or "unavailable" in low:
        return "供應商目前過載（503），稍後再試或換一個模型（Gemini 建議 gemini-3.6-flash；「-latest」別名在高峰常過載）"
    if "401" in msg or "authentication" in low or "invalid x-api-key" in low or "api key not valid" in low or "incorrect api key" in low:
        return f"API 金鑰無效或被拒絕：{msg[:160]}"
    if "403" in msg or "permission" in low:
        return f"金鑰沒有權限：{msg[:160]}"
    if "404" in msg or "not_found" in low or "model" in low and ("not found" in low or "does not exist" in low or "no longer available" in low):
        hint = re.search(r"use models/([\w.\-]+)", msg)
        suggested = f"，供應商建議改用 {hint.group(1)}" if hint else ""
        return f"模型名稱不存在、已下架或無權使用{suggested}：{msg[:140]}"
    if "429" in msg or "rate" in low and "limit" in low:
        return f"超過供應商速率／額度限制：{msg[:160]}"
    if "timed out" in low or "timeout" in low:
        return f"供應商 {int(timeout)} 秒內沒回應：可能是模型過載或網路／代理問題，稍後再試或換模型"
    if "urlopen error" in low or "name or service not known" in low or "getaddrinfo" in low or "connection" in low:
        return f"無法連到供應商：{msg[:160]}"
    return msg[:200] or exc.__class__.__name__


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
        return {"ok": True, "models": [], "reason": ""}
    reason = missing_reason(s)
    if reason:
        return {"ok": False, "models": [], "reason": reason}
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
        return {"ok": False, "models": [], "reason": _explain(exc)}
    return {"ok": True, "models": names[:60], "reason": ""}


def test_connection(s: AgentSettings) -> dict[str, Any]:
    """打一個最小請求驗證設定；回 {ok, provider, model, latency_ms, reply, reason}。"""
    import time

    base = {"provider": s.provider, "model": model_of(s), "source": s.source}
    if s.provider == "offline":
        return {**base, "ok": True, "latency_ms": 0, "reply": "", "reason": "離線規則引擎不需連線"}
    reason = missing_reason(s)
    if reason:
        return {**base, "ok": False, "latency_ms": 0, "reply": "", "reason": reason}
    t0 = time.perf_counter()
    try:
        reply = complete(s, "你是連線測試。只回覆兩個字母：OK", [], "ping", timeout=TEST_TIMEOUT)
    except Exception as exc:  # noqa: BLE001 - 任何失敗都要翻成原因回前端
        log.warning("agent 供應商連線測試失敗（%s）：%s", s.provider, exc)
        return {**base, "ok": False, "latency_ms": round((time.perf_counter() - t0) * 1000), "reply": "", "reason": _explain(exc, TEST_TIMEOUT)}
    return {**base, "ok": True, "latency_ms": round((time.perf_counter() - t0) * 1000), "reply": reply.strip()[:80], "reason": ""}
