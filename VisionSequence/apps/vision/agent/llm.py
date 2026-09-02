"""Claude 供應器：把工具目錄＋影像＋ROI＋提示詞交給 LLM，產出 graph JSON。

可選功能：`pip install anthropic` 並在 .env 設 `VISION_AGENT_API_KEY` 才啟用
（延後 import，缺件不影響其他功能——與 yolo/torch 同一套慣例）。
影像會縮圖後送出；不想讓影像離開廠內就不要設金鑰，規則引擎完全離線。
"""

from __future__ import annotations

import base64
import json
import logging
from functools import lru_cache
from typing import Any

import cv2
import numpy as np
from django.conf import settings

from apps.vision.agent.analysis import summarize_for_llm
from apps.vision.graph import validate_graph
from apps.vision.tools import base as tools

log = logging.getLogger("vision.agent")

_MAX_SIDE = 1024


def _cfg(key: str, default: Any = None) -> Any:
    return settings.VISION.get(key, default)


def available() -> bool:
    if not _cfg("AGENT_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def model_name() -> str:
    return str(_cfg("AGENT_MODEL") or "claude-opus-5")


@lru_cache(maxsize=1)
def _catalogue_text() -> str:
    """工具目錄的精簡 JSON（穩定內容，放進可快取的 system 段）。"""
    items = []
    for t in sorted(tools.all_types(), key=lambda x: x.key):
        if t.key.startswith("dl_") or t.key == "write_modbus":
            continue  # 需要模型／連線，助手不生成
        items.append({
            "type": t.key,
            "label": t.label,
            "params": {p.key: {"kind": p.kind, "default": p.default, **({"options": [o["value"] for o in p.options]} if p.options else {})} for p in t.params},
            "inputs": {p.key: p.type for p in t.inputs},
            "outputs": {p.key: p.type for p in t.outputs},
        })
    return json.dumps(items, ensure_ascii=False, separators=(",", ":"))


def _system_prompt() -> str:
    return f"""你是工業機器視覺流程設計專家。使用者上傳影像、圈選 ROI、描述檢測需求；你輸出一個可執行的資料流 DAG（graph JSON）。

## graph 格式
{{"nodes": [{{"id": "唯一字串", "type": "工具type", "label": "繁中標題", "enabled": true, "params": {{...}}, "position": {{"x": 40+欄*300, "y": 40+列*170}}}}], "edges": [{{"id": "e-<source>-<sh>-<target>-<th>", "source": "節點id", "target": "節點id", "source_handle": "輸出埠", "target_handle": "輸入埠"}}]}}

## 規則
1. 第一個節點必須是 image_source（params 只填 {{"mode": "auto"}}，不綁來源）。
2. 影像預設埠：source_handle/target_handle 留空字串代表「影像進／出」；具名埠必須用下方目錄裡的埠名。
3. 控制分支：判斷工具的 flow 型輸出（true/false、found/not_found、inside/outside、ok/ng、match/mismatch、pass/fail）接到目標節點的 "_flow" 輸入埠，決定該分支是否執行。
4. 一定要收尾：至少一個 judge（verdict=ok/ng/by_input）決定 OK/NG，重要數值用 output（params.name=英文鍵名）輸出；找不到特徵時接 not_found → judge(verdict=ng)。
5. ROI：工具的 roi 參數直接放使用者給的 region dict（座標是全圖像素座標，原樣使用、不要縮放）。
6. 需要說明時放一個 note 節點：{{"id": "hint", "type": "note", "label": "AI 助手", "description": "說明文字", "position": {{...}}, "width": 320, "height": 120}}；note 不接任何邊。
7. 參數用目錄裡存在的 key；量測類（門檻、面積、公差）依影像特徵摘要給出合理數值。
8. 位置排版：主鏈由左到右（欄距 300px），分支往下（列距 170px）。

## 工具目錄（type / params / inputs / outputs）
{_catalogue_text()}

## 輸出
只輸出一個 JSON 物件，不要任何其他文字或 markdown 圍欄：
{{"graph": {{...}}, "rationale": "一句話說明為什麼這樣設計（繁體中文）"}}"""


def _encode_image(image: np.ndarray) -> str:
    h, w = image.shape[:2]
    scale = min(1.0, _MAX_SIDE / max(h, w))
    if scale < 1.0:
        image = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        raise RuntimeError("影像編碼失敗")
    return base64.standard_b64encode(buf.tobytes()).decode()


def _parse_reply(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        cleaned = cleaned.rsplit("```", 1)[0]
    return json.loads(cleaned)


def generate(image: np.ndarray, regions: list[dict[str, Any]], prompt: str, analysis: dict[str, Any],
             *, previous_graph: dict[str, Any] | None = None, feedback: str = "") -> tuple[dict[str, Any], str]:
    """呼叫 Claude 產 graph；validate 失敗會把錯誤帶回去重試一次。回 (graph, rationale)。"""
    import anthropic

    client = anthropic.Anthropic(api_key=str(_cfg("AGENT_API_KEY")))
    parts: list[dict[str, Any]] = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": _encode_image(image)}},
    ]
    lines = [f"檢測需求：{prompt or '（未填，請依 ROI 與影像判斷最合理的檢測）'}"]
    for i, r in enumerate(regions, start=1):
        hint = f"（{r['hint']}）" if r.get("hint") else ""
        lines.append(f"ROI{i}{hint}: {json.dumps(r.get('region'), ensure_ascii=False)}")
    lines.append("影像特徵摘要：\n" + summarize_for_llm(analysis))
    if previous_graph is not None:
        lines.append("目前的 graph（請依回饋修改，保留可用的部分）：\n" + json.dumps(previous_graph, ensure_ascii=False))
        lines.append(f"使用者回饋：{feedback}")
    parts.append({"type": "text", "text": "\n".join(lines)})

    messages: list[dict[str, Any]] = [{"role": "user", "content": parts}]
    system = [{"type": "text", "text": _system_prompt(), "cache_control": {"type": "ephemeral"}}]
    last_error = ""
    for attempt in range(2):
        response = client.messages.create(
            model=model_name(), max_tokens=16000, system=system, messages=messages,
        )
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            payload = _parse_reply(text)
            graph = validate_graph(payload["graph"])
            return graph, str(payload.get("rationale") or "")
        except Exception as exc:  # noqa: BLE001 - JSON 或 graph 驗證失敗都走重試
            last_error = str(exc)
            log.warning("agent LLM 第 %d 次輸出無效：%s", attempt + 1, last_error)
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": f"上面的輸出無法使用：{last_error}\n請修正後重新只輸出 JSON 物件。"})
    raise RuntimeError(f"LLM 產出的流程無法通過驗證：{last_error}")
