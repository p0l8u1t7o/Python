"""LLM 生成：把工具目錄＋影像＋ROI＋提示詞交給供應商（providers.py），產出 graph JSON。

四種任務共用同一份 system（可快取）：generate（從零生成）、refine（依回饋修改）、
edit（編輯器內的指令：改參數／增刪節點）、tune（依批次測試結果調整）。
輸出一律經 validate_graph 把關；無效輸出帶錯誤重試一次。
"""

from __future__ import annotations

import base64
import json
import logging
from functools import lru_cache
from typing import Any

import cv2
import numpy as np

from apps.vision.agent import providers
from apps.vision.agent.analysis import summarize_for_llm
from apps.vision.graph import validate_graph
from apps.vision.tools import base as tools

log = logging.getLogger("vision.agent")

_MAX_SIDE = 1024


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
            "params": {p.key: {"label": p.label, "kind": p.kind, "default": p.default, **({"options": [o["value"] for o in p.options]} if p.options else {})} for p in t.params},
            "inputs": {p.key: p.type for p in t.inputs},
            "outputs": {p.key: p.type for p in t.outputs},
        })
    return json.dumps(items, ensure_ascii=False, separators=(",", ":"))


def system_prompt() -> str:
    return f"""你是工業機器視覺流程設計專家。使用者上傳影像、圈選 ROI、描述檢測需求；你輸出一個可執行的資料流 DAG（graph JSON）。

## graph 格式
{{"nodes": [{{"id": "唯一字串", "type": "工具type", "label": "繁中標題", "enabled": true, "params": {{...}}, "position": {{"x": 40+欄*300, "y": 40+列*170}}}}], "edges": [{{"id": "e-<source>-<sh>-<target>-<th>", "source": "節點id", "target": "節點id", "source_handle": "輸出埠", "target_handle": "輸入埠"}}]}}

## 規則
1. 第一個節點必須是 image_source（params 只填 {{"mode": "auto"}}，不綁來源）。
2. 影像預設埠：source_handle/target_handle 留空字串代表「影像進／出」；具名埠必須用下方目錄裡的埠名。
3. 控制分支：判斷工具的 flow 型輸出（true/false、found/not_found、inside/outside、ok/ng、match/mismatch、pass/fail）接到目標節點的 "_flow" 輸入埠，決定該分支是否執行。
4. 一定要收尾：至少一個 judge（verdict=ok/ng/by_input）決定 OK/NG，重要數值用 output（params.name=英文鍵名）輸出；找不到特徵時接 not_found → judge(verdict=ng)。
5. ROI：工具的 roi 參數直接放使用者給的 region dict（座標是全圖像素座標，原樣使用、不要縮放）。多張影像時各 ROI 標明屬於哪張，生成的流程要對每張影像都合理。
6. 需要說明時放一個 note 節點：{{"id": "hint", "type": "note", "label": "AI 助手", "description": "說明文字", "position": {{...}}, "width": 320, "height": 120}}；note 不接任何邊。
7. 參數用目錄裡存在的 key；量測類（門檻、面積、公差）依影像特徵摘要給出合理數值。
8. 位置排版：主鏈由左到右（欄距 300px），分支往下（列距 170px）。
9. 修改既有流程時保留原節點 id 與位置，只動需要動的部分，並在 rationale 條列改了什麼。

## 工具目錄（type / params / inputs / outputs）
{_catalogue_text()}

## 輸出
只輸出一個 JSON 物件，不要任何其他文字或 markdown 圍欄：
{{"graph": {{...}}, "rationale": "繁體中文說明（生成理由／改了什麼）"}}"""


def encode_image(image: np.ndarray) -> str:
    h, w = image.shape[:2]
    scale = min(1.0, _MAX_SIDE / max(h, w))
    if scale < 1.0:
        image = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        raise RuntimeError("影像編碼失敗")
    return base64.standard_b64encode(buf.tobytes()).decode()


def parse_reply(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        cleaned = cleaned.rsplit("```", 1)[0]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start > 0 or end < len(cleaned) - 1:
        cleaned = cleaned[start:end + 1]
    return json.loads(cleaned)


def _user_text(task: str, prompt: str, regions: list[dict[str, Any]], analysis: dict[str, Any] | None,
               previous_graph: dict[str, Any] | None, feedback: str, batch_summary: str) -> str:
    lines: list[str] = []
    if task == "generate":
        lines.append(f"檢測需求：{prompt or '（未填，請依 ROI 與影像判斷最合理的檢測）'}")
    elif task == "refine":
        lines.append(f"原始需求：{prompt}")
    elif task == "edit":
        lines.append("使用者在流程編輯器裡要你修改目前的流程。")
    elif task == "tune":
        lines.append("使用者跑了一批影像，要你依結果調整流程或參數。")
    for i, r in enumerate(regions, start=1):
        hint = f"（{r['hint']}）" if r.get("hint") else ""
        lines.append(f"ROI{i:02d}{hint}（影像 {int(r.get('image', 0) or 0) + 1}）: {json.dumps(r.get('region'), ensure_ascii=False)}")
    if analysis:
        lines.append("影像特徵摘要：\n" + summarize_for_llm(analysis))
    if previous_graph is not None:
        lines.append("目前的 graph：\n" + json.dumps(previous_graph, ensure_ascii=False))
    if batch_summary:
        lines.append("批次測試結果：\n" + batch_summary)
    if feedback:
        lines.append(f"使用者{'指令' if task in ('edit', 'tune') else '回饋'}：{feedback}")
    return "\n".join(lines)


def generate(settings: providers.AgentSettings, images: list[np.ndarray], regions: list[dict[str, Any]], prompt: str,
             analysis: dict[str, Any] | None, *, task: str = "generate", previous_graph: dict[str, Any] | None = None,
             feedback: str = "", batch_summary: str = "") -> tuple[dict[str, Any], str]:
    """呼叫供應商產 graph；validate 失敗會把錯誤帶回去重試一次。回 (graph, rationale)。"""
    encoded = [encode_image(im) for im in images[:6]]
    text = _user_text(task, prompt, regions, analysis, previous_graph, feedback, batch_summary)
    history: list[dict[str, Any]] = []
    last_error = ""
    for attempt in range(2):
        reply = providers.complete(settings, system_prompt(), encoded, text, history)
        try:
            payload = parse_reply(reply)
            graph = validate_graph(payload["graph"])
            return graph, str(payload.get("rationale") or "")
        except Exception as exc:  # noqa: BLE001 - JSON 或 graph 驗證失敗都走重試
            last_error = str(exc)
            log.warning("agent LLM 第 %d 次輸出無效：%s", attempt + 1, last_error)
            history.append({"role": "assistant", "content": reply})
            history.append({"role": "user", "content": f"上面的輸出無法使用：{last_error}\n請修正後重新只輸出 JSON 物件。"})
    raise RuntimeError(f"LLM 產出的流程無法通過驗證：{last_error}")
