"""AI 助手評測基準：一組（影像、ROI、提示詞、期望意圖、每張影像期望判定）案例，離線可跑。

用途：
- `manage.py agent_bench` 量化規則引擎（或 --llm 指定供應商）的意圖準確率、判定準確率、graph 有效率；
- `tests/test_agent_bench.py` 以門檻守住回歸；
- 之後候選排名／自動調參／記憶先驗都用同一把尺比較有無改善。

案例影像來自 apps/vision/demo_images.py 的合成樣本（與範本畫廊共用）與這裡的幾個小合成器；
不依賴磁碟上的 data/samples。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

import cv2
import numpy as np

from apps.golden.regress import evaluate_expect
from apps.vision import demo_images


def part_image(holes: int = 5) -> np.ndarray:
    img = np.full((480, 640, 3), 200, np.uint8)
    for i in range(holes):
        cv2.circle(img, (100 + i * 110, 240), 30, (40, 40, 40), -1)
    return img


def red_block_image(orange: bool = False) -> np.ndarray:
    img = np.full((480, 640, 3), 220, np.uint8)
    cv2.rectangle(img, (200, 150), (440, 330), (40, 130, 220) if orange else (40, 40, 200), -1)
    return img


def print_image(stain: bool) -> np.ndarray:
    img = np.full((480, 640, 3), 225, np.uint8)
    cv2.rectangle(img, (120, 100), (520, 380), (60, 70, 80), 4)
    cv2.circle(img, (220, 240), 60, (50, 60, 200), -1)
    if stain:
        cv2.circle(img, (420, 300), 25, (30, 30, 30), -1)
    return img


def text_image(present: bool) -> np.ndarray:
    """標籤上有／沒有印字。"""
    img = np.full((480, 640, 3), 235, np.uint8)
    cv2.rectangle(img, (120, 160), (520, 320), (250, 250, 250), -1)
    cv2.rectangle(img, (120, 160), (520, 320), (90, 90, 90), 2)
    if present:
        cv2.putText(img, "LOT A123", (150, 260), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (30, 30, 30), 4, cv2.LINE_AA)
    return img


def holes_pair_image(spacing: int = 300) -> np.ndarray:
    """兩個暗孔，中心距 = spacing。"""
    img = np.full((480, 640, 3), 205, np.uint8)
    cv2.circle(img, (200, 240), 30, (40, 40, 40), -1)
    cv2.circle(img, (200 + spacing, 240), 30, (40, 40, 40), -1)
    return img


def logo_image(present: bool, shift: int = 0) -> np.ndarray:
    """有／沒有一個「圓內方」圖案（位置可小幅位移）。"""
    img = np.full((480, 640, 3), 225, np.uint8)
    cv2.rectangle(img, (60, 60), (580, 420), (200, 200, 205), 3)
    if present:
        cx, cy = 320 + shift, 240 - shift
        cv2.circle(img, (cx, cy), 60, (40, 60, 160), -1)
        cv2.rectangle(img, (cx - 25, cy - 25), (cx + 25, cy + 25), (240, 240, 240), -1)
    return img


def flat_image(value: int = 128) -> np.ndarray:
    img = np.full((300, 400, 3), value, np.uint8)
    rng = np.random.default_rng(1)
    return np.clip(img.astype(np.int16) + rng.normal(0, 3, img.shape).astype(np.int16), 0, 255).astype(np.uint8)


@dataclass
class BenchCase:
    key: str
    title: str
    images: Callable[[], list[np.ndarray]]
    prompt: str
    expect_intent: str
    #: 每張影像的期望判定：ok | ng | any（長度與影像數一致；短了以 any 補）。
    expect_status: list[str]
    regions: list[dict[str, Any]] = field(default_factory=list)
    answers: list[dict[str, Any]] = field(default_factory=list)
    #: 每張影像的期望標記（候選排名／自動調參用；空字串＝不標）。
    labels: list[str] = field(default_factory=list)
    tags: tuple[str, ...] = ()


def _rect(x: int, y: int, w: int, h: int, image: int = 0, hint: str = "") -> dict[str, Any]:
    return {"region": {"shape": "rect", "x": x, "y": y, "w": w, "h": h}, "image": image, "hint": hint}


CASES: list[BenchCase] = [
    BenchCase("count_5", "計數：5 孔合成件", lambda: [part_image(5), part_image(4)], "應該有 5 個孔", "count", ["ok", "ng"], tags=("count",)),
    BenchCase("count_vague_answers", "計數：不明確提示＋問答補齊", lambda: [part_image(5)], "看一下這個", "count", ["ok"],
              answers=[{"id": "goal", "answer": "count"}, {"id": "count", "answer": "5"}, {"id": "roi_scope", "answer": "whole"}], tags=("count", "clarify")),
    BenchCase("count_multi_circles", "計數：多圓幾何樣本", demo_images.multi_circles, "這裡應該有 5 個孔", "count", ["ok", "ok", "ok", "ng"], tags=("count", "samples")),
    BenchCase("diameter_circle_part", "直徑：圓孔量測樣本（mm）", demo_images.circle_part, "量孔的直徑 17.5±0.4mm，0.05mm=1px", "diameter", ["ok", "ok", "ok", "ng"],
              regions=[{"region": {"shape": "circle", "cx": 640, "cy": 480, "r": 175}, "image": 0}], tags=("measure", "samples")),
    BenchCase("diameter_px", "直徑：只回報 px", lambda: [part_image(1)], "量這個孔的直徑", "diameter", ["ok"],
              regions=[{"region": {"shape": "circle", "cx": 100, "cy": 240, "r": 30}, "image": 0}], tags=("measure",)),
    BenchCase("width_marker", "寬度：定位板亮帶", demo_images.marker_plate, "量寬度 160±10", "width", ["ok", "ok", "ok", "ng"],
              regions=[{"region": {"shape": "rotated_rect", "cx": 690, "cy": 480, "w": 300, "h": 60, "angle": 90}, "image": 0}], tags=("measure", "samples")),
    BenchCase("angle_bracket", "角度：L 形工件", demo_images.l_bracket, "兩條邊的夾角 90±1", "angle", ["ok", "ok", "ok", "ng"],
              regions=[_rect(460, 500, 460, 120), _rect(200, 280, 200, 340)], tags=("measure", "samples")),
    BenchCase("golden_print", "良品比對：兩張影像＋ROI 角色", lambda: [print_image(False), print_image(True)],
              "ROI01 是好品，ROI02 是壞品，找出差異", "golden", ["ok", "ng"],
              regions=[_rect(100, 80, 440, 320, 0, "好品"), _rect(100, 80, 440, 320, 1, "壞品")], tags=("defect",)),
    BenchCase("defect_textile", "缺陷：織紋刮痕（頻域）", demo_images.textile, "表面有沒有刮痕", "defect", ["ok", "ok", "ok", "ng"], tags=("defect", "samples")),
    BenchCase("defect_flat", "缺陷：均勻面無缺陷", lambda: [flat_image()], "表面有沒有刮痕", "defect", ["ok"], tags=("defect",)),
    BenchCase("color_match", "顏色比對：紅色塊", lambda: [red_block_image(), red_block_image(orange=True)], "這一塊的顏色對不對", "color_match", ["ok", "ng"],
              regions=[_rect(220, 170, 200, 140)], tags=("color",)),
    BenchCase("color_presence", "顏色有無：色塊樣本", demo_images.color_blocks, "紅色膠塞有沒有", "color_presence", ["ok", "ok", "ok", "ng"],
              regions=[_rect(150, 330, 240, 300)], tags=("color", "samples")),
    BenchCase("presence_part", "有無：合成件", lambda: [part_image(3), np.full((480, 640, 3), 200, np.uint8)], "檢查有沒有零件", "presence", ["ok", "ng"], tags=("presence",)),
    BenchCase("brightness_range", "亮度：指定範圍", lambda: [flat_image(128), flat_image(30)], "亮度是否正常 80~180", "brightness", ["ok", "ng"], tags=("brightness",)),
    BenchCase("barcode_label", "讀碼：標籤樣本", demo_images.label_qr, "讀取條碼", "barcode", ["any", "any", "any", "ng"], tags=("identify", "samples")),
    BenchCase("generic_vague", "不明確：只驗意圖", lambda: [flat_image()], "看一下這個", "generic", ["any"], tags=("clarify",)),
    BenchCase("text_label", "印字有無：標籤", lambda: [text_image(True), text_image(False)], "標籤上有沒有印字", "text", ["ok", "ng"],
              regions=[_rect(130, 170, 380, 140)], tags=("identify",)),
    BenchCase("distance_holes", "兩孔中心距：合成件", lambda: [holes_pair_image(300), holes_pair_image(300), holes_pair_image(330)],
              "兩孔中心距離 300±10", "distance", ["ok", "ok", "ng"],
              regions=[{"region": {"shape": "circle", "cx": 200, "cy": 240, "r": 30}, "image": 0}, {"region": {"shape": "circle", "cx": 500, "cy": 240, "r": 30}, "image": 0}],
              tags=("measure",)),
    BenchCase("template_logo", "圖案有無：範本比對", lambda: [logo_image(True), logo_image(True, 5), logo_image(True, -4), logo_image(False)],
              "有沒有這個圖案", "template_presence", ["ok", "ok", "ok", "ng"], regions=[_rect(240, 160, 160, 160)], tags=("presence",)),
    BenchCase("locate_width", "定位＋卡尺：定位量測樣本", demo_images.marker_plate, "量亮帶的寬度 160±10，工件位置會變", "width", ["ok", "ok", "ok", "ng"],
              regions=[_rect(190, 150, 140, 140, 0, "定位"), {"region": {"shape": "rotated_rect", "cx": 690, "cy": 480, "w": 300, "h": 60, "angle": 90}, "image": 0}],
              tags=("measure", "locate", "samples")),
    BenchCase("count_labels_pick", "計數＋標記：候選排名與自動調參", lambda: [part_image(5), part_image(4)], "數一下有幾個孔", "count", ["ok", "ng"],
              answers=[{"id": "count", "answer": "5"}], labels=["ok", "ng"], tags=("count", "labels")),
]


def run_case(case: BenchCase, settings: Any = None, *, use_llm: bool | None = False) -> dict[str, Any]:
    from apps.vision.agent import service

    images = case.images()
    t0 = time.perf_counter()
    row: dict[str, Any] = {"key": case.key, "title": case.title, "tags": list(case.tags)}
    try:
        result = service.generate(images, case.regions, case.prompt, settings, use_llm=use_llm, answers=case.answers, labels=case.labels or None)
    except Exception as exc:  # noqa: BLE001 - 基準要能把炸掉的案例列出來，不能中斷整批
        row.update(intent="", intent_ok=False, valid=False, status_ok=False, statuses=[], expected=case.expect_status,
                   error=f"{exc.__class__.__name__}: {exc}", ms=round((time.perf_counter() - t0) * 1000))
        return row
    reports = result.get("reports") or [result["report"]]
    statuses = [r.get("status", "") for r in reports]
    expected = list(case.expect_status) + ["any"] * (len(statuses) - len(case.expect_status))
    matches = [evaluate_expect(exp, None, st, {})[0] for st, exp in zip(statuses, expected)]
    errors = [nid for r in reports for nid, nr in (r.get("nodes") or {}).items() if nr.get("status") == "error"]
    row.update(
        intent=result.get("intent", ""), intent_ok=(result.get("intent") == case.expect_intent) if case.expect_intent else True,
        valid=not errors, error_nodes=sorted(set(errors)), statuses=statuses, expected=expected, status_ok=all(matches),
        status_matches=matches, provider=result.get("provider"), warnings=result.get("warnings", []),
        ms=round((time.perf_counter() - t0) * 1000), error="",
    )
    return row


def run_bench(settings: Any = None, *, use_llm: bool | None = False, keys: list[str] | None = None) -> dict[str, Any]:
    cases = [c for c in CASES if not keys or c.key in keys]
    rows = [run_case(c, settings, use_llm=use_llm) for c in cases]
    n = len(rows) or 1
    per_image = [m for r in rows for m in r.get("status_matches", [])]
    summary = {
        "n": len(rows),
        "intent_acc": round(sum(r["intent_ok"] for r in rows) / n, 3),
        "status_acc": round(sum(r["status_ok"] for r in rows) / n, 3),
        "image_acc": round(sum(per_image) / max(1, len(per_image)), 3),
        "valid_rate": round(sum(r["valid"] for r in rows) / n, 3),
        "failed": [r["key"] for r in rows if not (r["intent_ok"] and r["status_ok"] and r["valid"])],
        "total_ms": sum(r["ms"] for r in rows),
    }
    return {"cases": rows, "summary": summary}
