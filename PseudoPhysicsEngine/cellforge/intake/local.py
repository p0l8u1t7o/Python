"""Deterministic intake used for tests and as an explicit offline fallback."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cellforge.schema import Questions
from cellforge.schema.models import Question
from cellforge.yamlio import dump_yaml


def run_local_intake(project: Path, extraction: dict[str, Any]) -> dict[str, Any]:
    files = extraction["files"]
    photos = [item for item in files if item["kind"] == "product_photo"]
    pdfs = [item for item in files if item["source"].lower().endswith(".pdf")]
    checklists = [item for item in files if item["kind"] == "checklist"]
    page_count = sum(int(item.get("page_count", 0)) for item in pdfs)
    (project / "analysis" / "intake.md").write_text(
        "# 資料解析摘要\n\n"
        f"- 共接收 {len(files)} 個檔案。\n"
        f"- 產品照片 {len(photos)} 張。\n"
        f"- PDF 共 {page_count} 頁，逐頁文字與影像位於 `analysis/extracted/`。\n"
        f"- Check List {len(checklists)} 份，已轉成逐列文字。\n"
        "- 本摘要由離線驗收 runner 產生；正式模式由 Claude Code 逐檔判讀。\n",
        encoding="utf-8",
    )
    mapping_lines = [
        "# Check List 自動化對照",
        "",
        "| 項次 | 原始列 | 可行性 | 自動化方法 | 建議站別 |",
        "|---:|---|---|---|---|",
    ]
    total = 0
    for checklist in checklists:
        for artifact in checklist.get("artifacts", []):
            source = project / artifact
            for line in source.read_text("utf-8").splitlines():
                if not line.startswith("- R"):
                    continue
                total += 1
                original = line.split(": ", 1)[-1].replace("|", "/")
                mapping_lines.append(
                    f"| {total} | {original} | medium | 工業相機取像＋規則判讀 | S2 |"
                )
    coverage = f"Coverage: {total}/{total} (100%)" if total else "Coverage: 0/0 (100%)"
    mapping_lines.extend(["", coverage])
    (project / "analysis" / "checklist_map.md").write_text(
        "\n".join(mapping_lines) + "\n", encoding="utf-8"
    )
    question_data = [
        (
            "workpiece",
            "各 SKU 的精確外形與重量為何？",
            "影響夾持、負載與換線",
            "外形 312×292×39 mm、重量 2.1 kg",
        ),
        ("workpiece", "各護蓋的開啟角度上限為何？", "影響末端進入路徑", "護蓋上限 110°"),
        (
            "process",
            "每一項外觀檢查允許的判定時間為何？",
            "影響站別節拍配置",
            "每次取像與判讀 2 秒",
        ),
        (
            "equipment",
            "DENSO 手臂的指定型號為何？",
            "影響可達與負載",
            "採用 VS-087，reach 905 mm、payload 7 kg",
        ),
        ("equipment", "力覺末端允許的最大接觸力為何？", "避免刮傷產品與護蓋", "接觸力上限 8 N"),
        ("site", "現場可用佔地與進出料方向為何？", "影響五站佈局", "佔地 8000×4000 mm，左進右出"),
        ("constraint", "目標節拍是否包含人工補料時間？", "影響產能計算邊界", "45 秒不含人工補料"),
        (
            "process",
            "背面翻面後的定位重複精度需求為何？",
            "影響翻面機構與相機校正",
            "定位重複精度 ±0.5 mm",
        ),
    ]
    questions = Questions(
        questions=[
            Question(
                id=f"Q-{index:03d}",
                topic=topic,
                text=text,
                why=why,
                default_if_skipped=default,
            )
            for index, (topic, text, why, default) in enumerate(question_data, 1)
        ]
    )
    dump_yaml(project / "analysis" / "questions.yaml", questions.model_dump(mode="json"))
    dump_yaml(project / "analysis" / "assumptions.yaml", {"assumptions": []})
    return {
        "status": "ok",
        "mode": "local",
        "files": len(files),
        "questions": len(question_data),
        "checklist_rows": total,
        "coverage_percent": 100,
    }
