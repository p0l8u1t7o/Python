"""Extract PDF pages to UTF-8 text and PNG files for engineering agents."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import pymupdf


@dataclass(frozen=True)
class ExtractedPage:
    number: int
    text_path: str
    image_path: str
    characters: int


def extract_pdf_pages(
    pdf_path: Path,
    output_dir: Path,
    *,
    dpi: int = 72,
) -> list[ExtractedPage]:
    """Render every PDF page and save its text beside the rendered image."""
    pdf_path = pdf_path.resolve()
    if not pdf_path.is_file():
        raise FileNotFoundError(f"找不到 PDF：{pdf_path}")
    output_dir.mkdir(parents=True, exist_ok=True)
    scale = dpi / 72
    pages: list[ExtractedPage] = []
    with pymupdf.open(pdf_path) as document:
        for index, page in enumerate(document, 1):
            stem = f"page-{index:03d}"
            text = page.get_text("text").strip()
            text_path = output_dir / f"{stem}.txt"
            image_path = output_dir / f"{stem}.png"
            text_path.write_text(text + ("\n" if text else ""), encoding="utf-8")
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            pixmap.save(image_path)
            pages.append(
                ExtractedPage(
                    number=index,
                    text_path=str(text_path),
                    image_path=str(image_path),
                    characters=len(text),
                )
            )
    return pages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--dpi", type=int, default=72)
    args = parser.parse_args()
    result = extract_pdf_pages(args.pdf, args.out, dpi=args.dpi)
    print(json.dumps([asdict(page) for page in result], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
