"""Prepare uploaded documents in formats an engineering agent can inspect."""

from __future__ import annotations

import csv
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import openpyxl
import xlrd
from PIL import Image, ImageOps

from cellforge.yamlio import load_yaml

from .pdf_pages import extract_pdf_pages

Progress = Callable[[str], None]


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip().replace("\r\n", " / ").replace("\n", " / ")


def _spreadsheet_rows(path: Path) -> list[list[str]]:
    suffix = path.suffix.lower()
    if suffix == ".xls":
        book = xlrd.open_workbook(path)
        rows: list[list[str]] = []
        for sheet in book.sheets():
            rows.append([f"工作表：{sheet.name}"])
            rows.extend(
                [_cell_text(value) for value in sheet.row_values(i)] for i in range(sheet.nrows)
            )
        return rows
    if suffix == ".xlsx":
        book = openpyxl.load_workbook(path, read_only=True, data_only=True)
        rows = []
        for sheet in book.worksheets:
            rows.append([f"工作表：{sheet.title}"])
            rows.extend(
                [_cell_text(value) for value in row] for row in sheet.iter_rows(values_only=True)
            )
        book.close()
        return rows
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [[_cell_text(value) for value in row] for row in csv.reader(handle)]


def _write_spreadsheet_markdown(path: Path, output: Path) -> int:
    rows = [[cell for cell in row] for row in _spreadsheet_rows(path)]
    nonempty = [row for row in rows if any(row)]
    lines = [f"# {path.name}", ""]
    for index, row in enumerate(nonempty, 1):
        cells = [cell for cell in row if cell]
        lines.append(f"- R{index:03d}: " + " | ".join(cells))
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(nonempty)


def _prepare_photo(path: Path, output: Path, max_edge: int = 1024) -> tuple[int, int]:
    output.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(path) as original:
        image = ImageOps.exif_transpose(original)
        image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        if image.mode != "RGB":
            image = image.convert("RGB")
        image.save(output, format="JPEG", quality=88, optimize=True)
        return image.size


def prepare_intake(project: Path, progress: Progress | None = None) -> dict[str, Any]:
    """Extract every supported input and return a machine-readable inventory."""
    project = project.resolve()
    manifest = load_yaml(project / "inputs" / "manifest.yaml") or {"files": []}
    extracted_root = project / "analysis" / "extracted"
    extracted_root.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    files = manifest.get("files", [])
    for index, entry in enumerate(files, 1):
        relative = str(entry["path"])
        source = (project / relative).resolve()
        if project not in source.parents or not source.is_file():
            raise ValueError(f"輸入檔案不存在或超出案子目錄：{relative}")
        if progress:
            progress(f"前處理檔案 {index}/{len(files)}：{source.name}")
        record: dict[str, Any] = {
            "source": relative,
            "kind": entry.get("kind", "other"),
            "note": entry.get("note", ""),
            "artifacts": [],
        }
        if source.suffix.lower() == ".pdf":
            destination = extracted_root / source.stem
            pages = extract_pdf_pages(source, destination)
            combined_text = destination / "all-pages.txt"
            combined_text.write_text(
                "\n\n".join(
                    f"===== PAGE {page.number:03d} =====\n"
                    + Path(page.text_path).read_text("utf-8")
                    for page in pages
                ),
                encoding="utf-8",
            )
            record["page_count"] = len(pages)
            record["combined_text"] = combined_text.relative_to(project).as_posix()
            record["artifacts"] = [
                {
                    "page": page.number,
                    "text": Path(page.text_path).relative_to(project).as_posix(),
                    "image": Path(page.image_path).relative_to(project).as_posix(),
                    "characters": page.characters,
                }
                for page in pages
            ]
        elif source.suffix.lower() in {".xls", ".xlsx", ".csv"}:
            destination = extracted_root / f"{source.stem}.md"
            row_count = _write_spreadsheet_markdown(source, destination)
            record["row_count"] = row_count
            record["artifacts"] = [destination.relative_to(project).as_posix()]
        elif entry.get("kind") == "product_photo":
            destination = extracted_root / "photos" / f"{source.stem}.jpg"
            try:
                width, height = _prepare_photo(source, destination)
            except OSError as exc:
                # Upload validation is intentionally permissive. Keep intake usable
                # when a mislabeled or damaged photo is present, but expose the
                # omission to the engineering agent and UI instead of hiding it.
                record["extraction_error"] = f"unreadable product photo: {exc}"
            else:
                record["review_size"] = {"width": width, "height": height}
                record["artifacts"] = [destination.relative_to(project).as_posix()]
        else:
            record["artifacts"] = [relative]
        records.append(record)
    report = {"file_count": len(files), "files": records}
    (project / "analysis" / "extraction.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report
