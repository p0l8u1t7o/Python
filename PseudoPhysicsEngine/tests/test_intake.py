from pathlib import Path

import pymupdf

from cellforge.intake import prepare_intake
from cellforge.intake.pdf_pages import extract_pdf_pages
from cellforge.questions import update_questions
from cellforge.schema import Questions
from cellforge.schema.models import Question
from cellforge.yamlio import dump_yaml, load_yaml


def test_pdf_pages_extracts_text_and_png(tmp_path: Path):
    pdf = tmp_path / "source.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "CellForge inspection page")
    document.save(pdf)
    document.close()

    pages = extract_pdf_pages(pdf, tmp_path / "pages", dpi=96)

    assert len(pages) == 1
    assert Path(pages[0].text_path).read_text("utf-8").strip() == "CellForge inspection page"
    assert Path(pages[0].image_path).read_bytes().startswith(b"\x89PNG")


def test_prepare_intake_reports_an_unreadable_photo(tmp_path: Path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "photo.jpg").write_bytes(b"not-a-jpeg")
    dump_yaml(
        inputs / "manifest.yaml",
        {
            "files": [
                {
                    "path": "inputs/photo.jpg",
                    "kind": "product_photo",
                    "note": "damaged fixture",
                }
            ]
        },
    )

    report = prepare_intake(tmp_path)

    assert report["file_count"] == 1
    assert report["files"][0]["artifacts"] == []
    assert report["files"][0]["extraction_error"].startswith("unreadable product photo")


def test_skip_all_creates_one_assumption_per_question(tmp_path: Path):
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    questions = Questions(
        questions=[
            Question(
                id=f"Q-{index:03d}",
                topic="workpiece",
                text=f"Question {index}",
                why="Required for geometry",
                default_if_skipped=f"Default {index}",
            )
            for index in range(1, 6)
        ]
    )
    dump_yaml(analysis / "questions.yaml", questions.model_dump(mode="json"))
    dump_yaml(analysis / "assumptions.yaml", {"assumptions": []})

    changed = update_questions(tmp_path, None, skip_all=True)

    assert len(changed) == 5
    stored_questions = load_yaml(analysis / "questions.yaml")["questions"]
    assumptions = load_yaml(analysis / "assumptions.yaml")["assumptions"]
    assert all(item["status"] == "skipped" for item in stored_questions)
    assert [item["text"] for item in assumptions] == [f"Default {index}" for index in range(1, 6)]
