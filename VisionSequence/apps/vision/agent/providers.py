"""AI 助手的 LLM 供應商：offline（規則引擎）／claude／openai／gemini。

設定解析順序：登入使用者自己的設定（UserPref.agent，各自儲存）→ 伺服器 .env
（VISION_AGENT_PROVIDER / VISION_AGENT_API_KEY / VISION_AGENT_MODEL）→ offline。
金鑰只在伺服器：API 只回「有沒有金鑰＋尾 4 碼」。

各供應商只實作一件事：`complete(settings, system, images, text) -> str`。
claude 走官方 anthropic SDK（可選安裝、延後 import）；openai／gemini 走 REST（標準庫 urllib，零依賴）。
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from django.conf import settings as dj_settings

log = logging.getLogger("vision.agent")

PROVIDERS = ("offline", "claude", "openai", "gemini")
DEFAULT_MODELS = {"claude": "claude-opus-5", "openai": "gpt-4o", "gemini": "gemini-2.0-flash"}
PROVIDER_LABELS = {"offline": "離線規則引擎", "claude": "Claude（Anthropic）", "openai": "GPT（OpenAI）", "gemini": "Gemini（Google）"}


@dataclass
class AgentSettings:
    provider: str = "offline"
    model: str = ""
    api_key: str = ""
    #: user | server | none：設定來自哪裡（回給前端顯示）。
    source: str = "none"

    @property
    def uses_llm(self) -> bool:
        return self.provider != "offline" and bool(self.api_key)

    def public(self) -> dict[str, Any]:
        return {
            "provider": self.provider, "model": self.model or DEFAULT_MODELS.get(self.provider, ""),
            "has_key": bool(self.api_key), "key_hint": f"…{self.api_key[-4:]}" if len(self.api_key) >= 8 else ("…" if self.api_key else ""),
            "source": self.source, "llm": self.uses_llm,
        }


def _cfg(key: str, default: Any = "") -> Any:
    return dj_settings.VISION.get(key, default)


def server_settings() -> AgentSettings:
    key = str(_cfg("AGENT_API_KEY") or "")
    provider = str(_cfg("AGENT_PROVIDER") or ("claude" if key else "offline"))
    if provider not in PROVIDERS:
        provider = "offline"
    return AgentSettings(provider=provider, model=str(_cfg("AGENT_MODEL") or ""), api_key=key, source="server" if key else "none")


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
    return AgentSettings(provider=provider, model=str(data.get("model") or ""), api_key=str(data.get("api_key") or ""), source="user")


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


def _claude(s: AgentSettings, system: str, images: list[str], text: str, history: list[dict[str, Any]]) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=s.api_key)
    parts: list[dict[str, Any]] = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}} for b64 in images]
    parts.append({"type": "text", "text": text})
    messages = [{"role": "user", "content": parts}, *history]
    response = client.messages.create(
        model=model_of(s), max_tokens=16000,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=messages,
    )
    return next((b.text for b in response.content if b.type == "text"), "")


def _openai(s: AgentSettings, system: str, images: list[str], text: str, history: list[dict[str, Any]]) -> str:
    content: list[dict[str, Any]] = [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}} for b64 in images]
    content.append({"type": "text", "text": text})
    messages = [{"role": "system", "content": system}, {"role": "user", "content": content}, *history]
    body = {"model": model_of(s), "messages": messages, "max_tokens": 8000}
    out = _post_json("https://api.openai.com/v1/chat/completions", body, {"Authorization": f"Bearer {s.api_key}"})
    return str(out["choices"][0]["message"]["content"])


def _gemini(s: AgentSettings, system: str, images: list[str], text: str, history: list[dict[str, Any]]) -> str:
    parts: list[dict[str, Any]] = [{"inline_data": {"mime_type": "image/jpeg", "data": b64}} for b64 in images]
    parts.append({"text": text})
    contents = [{"role": "user", "parts": parts}]
    for turn in history:
        contents.append({"role": "model" if turn["role"] == "assistant" else "user", "parts": [{"text": str(turn["content"])}]})
    body = {"system_instruction": {"parts": [{"text": system}]}, "contents": contents, "generationConfig": {"maxOutputTokens": 8000}}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_of(s)}:generateContent"
    out = _post_json(url, body, {"x-goog-api-key": s.api_key})
    return "".join(p.get("text", "") for p in out["candidates"][0]["content"]["parts"])


_IMPL = {"claude": _claude, "openai": _openai, "gemini": _gemini}


def complete(s: AgentSettings, system: str, images: list[str], text: str, history: list[dict[str, Any]] | None = None) -> str:
    """一次對話：system＋（影像 jpeg base64 們＋文字）＋可選的後續回合 → 文字回應。"""
    if s.provider not in _IMPL:
        raise RuntimeError(f"供應商 {s.provider} 不支援 LLM 生成")
    return _IMPL[s.provider](s, system, images, text, history or [])
