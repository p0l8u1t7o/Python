"""用 Claude 把自然語言描述轉成 build123d 產生器程式（text-to-cad 的「agent 寫碼」步驟）。

系統提示 = text-to-cad skill 的建模參考 + 本專案零件庫 API 摘要 + 輸出規範。
憑證：ANTHROPIC_API_KEY（或 `ant auth login` 的 profile）。
"""
from __future__ import annotations

import ast
import os
import re
from functools import lru_cache
from pathlib import Path

from django.conf import settings

ROOT = Path(settings.BASE_DIR).parent

# ---- Provider 設定（.env）----
# CAD_STUDIO_PROVIDER = gemini | openai_compat | claude   （預設 gemini）
# gemini        ：GEMINI_API_KEY，模型預設 gemini-2.5-pro（免費層可用）
# openai_compat ：CAD_STUDIO_BASE_URL + CAD_STUDIO_API_KEY（Groq / OpenRouter / Ollama…）
# claude        ：ANTHROPIC_API_KEY
PROVIDER = os.environ.get("CAD_STUDIO_PROVIDER", "gemini").lower()
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
# gemini-pro-latest 是 Google 的別名，指向目前的 Pro 版（避免像 gemini-2.5-pro 那樣被停用）
DEFAULT_MODELS = {"gemini": "gemini-pro-latest", "openai_compat": "", "claude": "claude-opus-5"}
# 模型不存在（404）或配額用盡（429）時依序改用
GEMINI_FALLBACKS = ["gemini-3.1-pro-preview", "gemini-flash-latest", "gemini-2.5-flash", "gemini-3.1-flash-lite"]
MODEL = os.environ.get("CAD_STUDIO_MODEL") or DEFAULT_MODELS.get(PROVIDER, "")


def provider_info() -> dict:
    """給前端顯示：provider、模型、是否已設定金鑰、缺什麼。"""
    if PROVIDER == "gemini":
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        return {"provider": "gemini", "model": MODEL, "ok": bool(key),
                "hint": "在 .env 填入 GEMINI_API_KEY（https://aistudio.google.com/apikey 免費申請）"}
    if PROVIDER == "openai_compat":
        base = os.environ.get("CAD_STUDIO_BASE_URL", "")
        key = os.environ.get("CAD_STUDIO_API_KEY", "")
        ok = bool(base and MODEL) and (bool(key) or "localhost" in base or "127.0.0.1" in base)
        return {"provider": "openai_compat", "model": MODEL, "ok": ok,
                "hint": "在 .env 填入 CAD_STUDIO_BASE_URL、CAD_STUDIO_MODEL 與 CAD_STUDIO_API_KEY（Ollama 本機不需金鑰）"}
    key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN") or (Path.home() / ".config" / "anthropic").exists()
    return {"provider": "claude", "model": MODEL, "ok": bool(key), "hint": "在 .env 填入 ANTHROPIC_API_KEY"}


@lru_cache(maxsize=1)
def parts_api_summary() -> str:
    """從 cad/lib/parts.py 抽出函式簽名與 docstring 第一行（不 import build123d）。"""
    src = ROOT / "cad" / "lib" / "parts.py"
    if not src.exists():
        return ""
    tree = ast.parse(src.read_text(encoding="utf-8"))
    lines = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            args = []
            defaults = [None] * (len(node.args.args) - len(node.args.defaults)) + list(node.args.defaults)
            for a, d in zip(node.args.args, defaults):
                args.append(f"{a.arg}={ast.unparse(d)}" if d is not None else a.arg)
            doc = (ast.get_docstring(node) or "").splitlines()
            lines.append(f"- parts.{node.name}({', '.join(args)})" + (f"  # {doc[0]}" if doc else ""))
    return "\n".join(lines)


@lru_cache(maxsize=1)
def modeling_reference() -> str:
    ref = ROOT / "cad" / "text-to-cad" / "skills" / "cad" / "references" / "build123d-modeling.md"
    if ref.exists():
        text = ref.read_text(encoding="utf-8")
        return text[:24000]
    return ""


def system_prompt() -> str:
    return f"""你是工業自動化設備的 CAD 工程師，使用 build123d（Python）建立參數化零件與組件。
使用者用中文或英文描述零件；你輸出「一個可直接執行的 build123d 產生器程式」。

## 輸出規範（嚴格遵守）
- 只輸出一個 ```python 程式碼區塊，前後可以有簡短說明（假設、尺寸依據）。
- 程式必須定義 `def gen_step():` 並回傳 build123d 的 Part／Solid／Compound（帶標籤的 Compound 最佳）。
- 單位 mm、+Z 向上、原點在零件底面中心（或功能基準面）。
- 必要的 import：`from build123d import *`；顏色用 `from cadgen import srgb`；組件用 `from cadgen.assembly import AssemblyHelper`。
- 可以直接使用本專案零件庫：`import parts` 後呼叫下列函式（已在 sys.path），也可組合它們。
- 布林運算把所有刀具放進「單一清單」一次相減：`body - (holes + [slot, bore])`。
- 對已定位形狀旋轉要加括號：`(Pos(x, y, z) * Cylinder(r, h)).rotate(Axis.Z, ang)`。
- `Cylinder`／`Box` 預設對齊是置中；要底面落在 z=0 用 `align=(Align.CENTER, Align.CENTER, Align.MIN)`。
- 不要寫檔、不要 print、不要用網路；不要用 `Plane.rotated()`。
- 尺寸不明時用工業常見型錄尺寸並在說明中列出假設。
- 使用者常只給「品牌＋型號」（例：DENSO HSR-048、SMC MHZ2-20D、Basler acA2500）。請用你對該產品的知識判斷它是什麼（類型、軸數、臂長／缸徑／尺寸），在說明中寫出解讀與假設，再建模；絕對不要因為資訊少就退回成無關的方塊。
  例：HSR-048 = DENSO HSR 系列四軸 SCARA、臂長 480 mm（第一臂 250 + 第二臂 230）、Z 行程 200 mm → 用 `parts.scara_arm(reach1=250, reach2=230, z_stroke=200)`。
- 機械手臂請直接用零件庫：四軸 SCARA → `parts.scara_arm(...)`；六軸垂直多關節 → `parts.articulated_arm(reach=...)`；可再加夾爪 `parts.gripper()`、`parts.vacuum_pads()` 等組成組件。
- 複雜設備（輸送機、電控櫃、氣缸、感測器…）優先用零件庫 builder 組合，再用 build123d 補細節。
- 零件庫 builder 的 `color` 參數是 "#RRGGBB" 字串（也接受 srgb() 物件）。單一零件可直接回傳 builder 的結果。不需要 `if __name__ == "__main__"`。
- AssemblyHelper 的正確用法（沒有 loc=/location=/position= 參數！定位要先 `.moved()`）：
  ```python
  from cadgen.assembly import AssemblyHelper
  asm = AssemblyHelper("my_cell")
  asm.add(parts.pedestal("pedestal", 500, 800), "pedestal")                      # 原地
  asm.add(parts.scara_arm(reach1=250, reach2=230).moved(Location((0, 0, 820))), "robot")   # 先位移再加入
  asm.add(parts.gripper().moved(Location((480, 0, 620), (0, 0, 30))), "gripper")  # Location((x, y, z), (rx, ry, rz) 度)
  return asm.compound()                                                            # 最後一定回傳 compound()
  ```

## 本專案零件庫（parts 模組）
{parts_api_summary()}

## build123d 建模參考（text-to-cad skill）
{modeling_reference()}
"""


def extract_code(text: str) -> str:
    m = re.search(r"```python\s*\n(.*?)```", text, re.S)
    if m:
        return m.group(1).strip()
    m = re.search(r"```\s*\n(.*?)```", text, re.S)
    return m.group(1).strip() if m else text.strip()


def _build_user_message(prompt: str, previous_code: str, previous_error: str) -> str:
    user = prompt.strip()
    if previous_code:
        user += "\n\n## 上一版程式\n```python\n" + previous_code + "\n```"
    if previous_error:
        user += "\n\n## 上一版建置錯誤（請修正）\n```\n" + previous_error[-4000:] + "\n```"
    return user


def _finish(text: str) -> tuple[str, str]:
    code = extract_code(text)
    notes = re.sub(r"```.*?```", "", text, flags=re.S).strip()
    if "def gen_step" not in code:
        raise RuntimeError("AI 回覆中沒有 gen_step()：\n" + text[:1500])
    return code, notes


def _generate_openai_compat(user: str, base_url: str, api_key: str, fallbacks: list[str] | None = None) -> tuple[str, str]:
    """Gemini / Groq / OpenRouter / Ollama 等 OpenAI 相容端點（chat.completions）。回傳 (text, 實際使用的模型)。
    模型不存在／配額用盡時依 fallbacks 依序重試。"""
    import openai

    if not MODEL:
        raise RuntimeError("未設定模型：請在 .env 填 CAD_STUDIO_MODEL。")
    client = openai.OpenAI(base_url=base_url, api_key=api_key or "none", timeout=600)
    tried: list[str] = []
    last_err: Exception | None = None
    for model in [MODEL] + [m for m in (fallbacks or []) if m != MODEL]:
        tried.append(model)
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system_prompt()}, {"role": "user", "content": user}],
                temperature=0.2,
            )
            return (resp.choices[0].message.content or ""), model
        except openai.AuthenticationError as e:
            raise RuntimeError(f"{PROVIDER} 金鑰無效（AuthenticationError），請檢查 .env。") from e
        except (openai.RateLimitError, openai.NotFoundError) as e:
            last_err = e  # 換下一個模型
            continue
        except openai.APIConnectionError as e:
            raise RuntimeError(f"無法連線到 {base_url}（網路或代理設定）。") from e
        except openai.APIStatusError as e:
            # Gemini 對無效金鑰回 400 "Please pass a valid API key" 而不是 401
            if "api key" in str(e).lower():
                raise RuntimeError(f"{PROVIDER} 金鑰無效或未生效，請檢查 .env 的金鑰（{str(e)[:120]}）。") from e
            if e.status_code in (500, 502, 503, 504, 529):
                last_err = e  # 高負載／暫時不可用 → 換下一個模型
                continue
            raise RuntimeError(f"{PROVIDER} API 錯誤 {e.status_code}：{str(e)[:300]}") from e
    kind = "配額用盡／速率限制" if isinstance(last_err, openai.RateLimitError) else ("模型暫時不可用（高負載）" if isinstance(last_err, openai.APIStatusError) and not isinstance(last_err, openai.NotFoundError) else "模型不存在")
    raise RuntimeError(f"{PROVIDER}：{kind}，已依序嘗試 {tried}。請稍後再試或在 .env 設定 CAD_STUDIO_MODEL。最後錯誤：{str(last_err)[:200]}")


def _generate_claude(user: str) -> str:
    import anthropic

    try:
        client = anthropic.Anthropic()
    except (anthropic.AnthropicError, TypeError) as e:
        raise RuntimeError("尚未設定 Claude 憑證：請在 .env 填入 ANTHROPIC_API_KEY。") from e
    try:
        with client.messages.stream(
            model=MODEL,
            max_tokens=16000,
            system=[{"type": "text", "text": system_prompt(), "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
        ) as stream:
            msg = stream.get_final_message()
    except anthropic.AuthenticationError as e:
        raise RuntimeError("Claude 憑證無效（AuthenticationError），請檢查 ANTHROPIC_API_KEY。") from e
    except anthropic.RateLimitError as e:
        raise RuntimeError("Claude API 速率限制，請稍後再試。") from e
    except anthropic.APIConnectionError as e:
        raise RuntimeError("無法連線到 Claude API（網路或代理設定）。") from e
    if msg.stop_reason == "refusal":
        raise RuntimeError("模型拒絕了這個請求。")
    return "".join(b.text for b in msg.content if b.type == "text")


def generate_code(prompt: str, previous_code: str = "", previous_error: str = "") -> tuple[str, str]:
    """回傳 (code, notes)。previous_code / previous_error 用於修訂。依 PROVIDER 分派。"""
    user = _build_user_message(prompt, previous_code, previous_error)
    info = provider_info()
    if not info["ok"]:
        raise RuntimeError(f"尚未設定 {info['provider']} 的金鑰：{info['hint']}，然後重新 start。")
    used = MODEL
    if PROVIDER == "gemini":
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
        text, used = _generate_openai_compat(user, GEMINI_BASE_URL, key, GEMINI_FALLBACKS)
    elif PROVIDER == "openai_compat":
        text, used = _generate_openai_compat(user, os.environ["CAD_STUDIO_BASE_URL"], os.environ.get("CAD_STUDIO_API_KEY", ""))
    else:
        text = _generate_claude(user)
    code, notes = _finish(text)
    return code, f"[模型：{used}]\n{notes}".strip()
