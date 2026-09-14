"""Customer delivery-pack exporters."""

from __future__ import annotations

import base64
import csv
import html as html_lib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import ezdxf
from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from cellforge.project import source_root
from cellforge.versioning import latest_version_dir
from cellforge.yamlio import load_yaml

ALL_KINDS = ("step", "dxf", "bom", "report", "deck", "html", "video")


def export_project(
    project: Path, kinds: list[str] | None = None, version: str | None = None
) -> dict[str, Any]:
    kinds = [item.lower() for item in (kinds or list(ALL_KINDS))]
    unknown = sorted(set(kinds) - set(ALL_KINDS))
    if unknown:
        raise ValueError(f"Unknown export kinds: {', '.join(unknown)}")
    version_dir = project / ".cellforge" / version if version else latest_version_dir(project)
    if version_dir is None or not version_dir.is_dir():
        raise FileNotFoundError("No immutable build version is available")
    target = project / "export" / version_dir.name
    target.mkdir(parents=True, exist_ok=True)
    project_data = load_yaml(project / "project.yaml")
    slug = _safe_name(project_data["name"])
    outputs: list[Path] = []
    dispatch = {
        "step": lambda: _copy(
            version_dir / "scene.step", target / f"{slug}_{version_dir.name}.step"
        ),
        "dxf": lambda: _dxf(project, target / f"{slug}_{version_dir.name}_layout.dxf"),
        "bom": lambda: _bom(project, target / f"{slug}_{version_dir.name}_bom.csv"),
        "report": lambda: _report(
            project, version_dir, target / f"{slug}_{version_dir.name}_report.docx"
        ),
        "deck": lambda: _deck(
            project, version_dir, target / f"{slug}_{version_dir.name}_review_final3.pptx"
        ),
        "html": lambda: _html(
            project, version_dir, target / f"{slug}_{version_dir.name}_review.html"
        ),
        "video": lambda: _copy(
            project / "presentation" / "cell_review_1080p.mp4",
            target / f"{slug}_{version_dir.name}_1080p.mp4",
        ),
    }
    for kind in kinds:
        outputs.append(dispatch[kind]())
    manifest = {
        "version": version_dir.name,
        "files": [path.name for path in outputs],
        "kinds": kinds,
        "template": {
            "requested": "zq-work-deck",
            "used": "CellForge Midnight",
            "deviation": "zq-work-deck not supplied in workspace",
        },
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "status": "ok",
        "version": version_dir.name,
        "directory": str(target),
        "files": manifest["files"],
    }


def _copy(source: Path, target: Path) -> Path:
    if not source.is_file():
        raise FileNotFoundError(source)
    shutil.copy2(source, target)
    return target


def _dxf(project: Path, target: Path) -> Path:
    document = ezdxf.new("R2018", setup=True)
    document.units = ezdxf.units.MM
    model = document.modelspace()
    cell = load_yaml(project / "cell.yaml")
    model.add_text("CellForge plan — dimensions in mm", dxfattribs={"height": 80}).set_placement(
        (-3800, 1800)
    )
    for machine in cell["machines"]:
        for module in machine["modules"]:
            x, y, _ = module.get("pose", {}).get("xyz", [0, 0, 0])
            params = module.get("params", {})
            length = float(params.get("length_mm", params.get("size", [500, 500])[0]))
            width = float(params.get("width_mm", params.get("size", [500, 500])[1]))
            points = [
                (x - length / 2, y - width / 2),
                (x + length / 2, y - width / 2),
                (x + length / 2, y + width / 2),
                (x - length / 2, y + width / 2),
            ]
            model.add_lwpolyline(points, close=True, dxfattribs={"layer": "EQUIPMENT"})
            model.add_text(module["id"], dxfattribs={"height": 55}).set_placement(
                (x - length / 2, y + width / 2 + 30)
            )
    document.saveas(target)
    return target


def _bom(project: Path, target: Path) -> Path:
    cell = load_yaml(project / "cell.yaml")
    vendor = load_yaml(project / "vendor" / "manifest.yaml") or {"vendors": []}
    vendor_map = {item["id"]: item for item in vendor.get("vendors", [])}
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["item", "module_id", "source", "vendor", "part_no", "trust", "quantity"],
        )
        writer.writeheader()
        for index, module in enumerate(
            (m for machine in cell["machines"] for m in machine["modules"]), 1
        ):
            item = vendor_map.get(module.get("vendor", ""), {})
            writer.writerow(
                {
                    "item": index,
                    "module_id": module["id"],
                    "source": module.get("part") or module.get("vendor"),
                    "vendor": module.get("vendor", ""),
                    "part_no": item.get("part_no", "TBD"),
                    "trust": module.get("trust") or module.get("pose", {}).get("trust", "inferred"),
                    "quantity": 1,
                }
            )
    return target


def _report(project: Path, version_dir: Path, target: Path) -> Path:
    data = load_yaml(project / "project.yaml")
    assumptions = (load_yaml(project / "analysis" / "assumptions.yaml") or {}).get(
        "assumptions", []
    )
    checks = json.loads((version_dir / "checks.json").read_text("utf-8"))
    timeline = json.loads((version_dir / "timeline.json").read_text("utf-8"))
    step = json.loads((version_dir / "step_validation.json").read_text("utf-8"))
    document = Document()
    section = document.sections[0]
    section.top_margin = Inches(0.65)
    section.bottom_margin = Inches(0.65)
    styles = document.styles
    styles["Normal"].font.name = "Microsoft JhengHei"
    styles["Normal"]._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft JhengHei")
    styles["Normal"].font.size = Pt(9.5)
    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run(data["name"])
    run.bold = True
    run.font.size = Pt(28)
    run.font.color.rgb = RGBColor(31, 78, 121)
    subtitle = document.add_paragraph(f"Automated QC cell engineering report • {version_dir.name}")
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    document.add_heading("Assumptions requiring confirmation", level=1)
    for item in assumptions:
        document.add_paragraph(
            f"{item['id']} — {item['text']} ({item['status']})", style="List Bullet"
        )
    document.add_page_break()
    document.add_heading("Executive engineering summary", level=1)
    document.add_paragraph(data.get("description", ""))
    table = document.add_table(rows=1, cols=4)
    table.style = "Light Shading Accent 1"
    for cell, value in zip(table.rows[0].cells, ("Metric", "Red", "Yellow", "Green"), strict=True):
        cell.text = value
    cells = table.add_row().cells
    for cell, value in zip(
        cells,
        (
            "L1 checks",
            checks["summary"]["red"],
            checks["summary"]["yellow"],
            checks["summary"]["green"],
        ),
        strict=True,
    ):
        cell.text = str(value)
    document.add_paragraph(f"Timeline: {timeline['duration_s']:.1f} s at {timeline['fps']} fps")
    document.add_paragraph(
        f"STEP: {step['top_level_part_count']} top-level components / "
        f"{step['leaf_part_count']} leaves; names preserved = "
        f"{step['all_names_preserved']}"
    )
    images = _review_snapshots(project, version_dir, checks)
    if images:
        image_table = document.add_table(rows=1, cols=len(images))
        for cell, image in zip(image_table.rows[0].cells, images, strict=True):
            cell.paragraphs[0].add_run().add_picture(str(image), width=Inches(3.25))
            cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
    document.add_section(WD_SECTION.NEW_PAGE)
    document.add_heading("Check results", level=1)
    for item in checks["items"]:
        document.add_heading(f"{item['id']} • {item['severity'].upper()} • {item['type']}", level=2)
        document.add_paragraph(item.get("detail", ""))
        if item.get("suggestion"):
            document.add_paragraph(f"Action: {item['suggestion']}")
        document.add_paragraph(f"Evidence: {item.get('source', 'n/a')}")
    document.add_heading("Checklist mapping", level=1)
    checklist = project / "analysis" / "checklist_map.md"
    document.add_paragraph(
        checklist.read_text("utf-8") if checklist.is_file() else "No checklist map supplied."
    )
    footer = section.footer.paragraphs[0]
    footer.text = (
        "CellForge • engineering evidence pack • inferred values require commissioning confirmation"
    )
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    document.save(target)
    return target


def _deck(project: Path, version_dir: Path, target: Path) -> Path:
    data = load_yaml(project / "project.yaml")
    assumptions = (load_yaml(project / "analysis" / "assumptions.yaml") or {}).get(
        "assumptions", []
    )
    process = load_yaml(project / "process.yaml")
    workpiece = load_yaml(project / "workpiece.yaml")
    checks = json.loads((version_dir / "checks.json").read_text("utf-8"))
    timeline = json.loads((version_dir / "timeline.json").read_text("utf-8"))
    step = json.loads((version_dir / "step_validation.json").read_text("utf-8"))
    payload = {
        "name": data["name"],
        "customer": data.get("customer", ""),
        "product": data.get("product", ""),
        "version": version_dir.name,
        "assumptions": [
            f"{item['id']}: {item['text'][:45].rstrip()}{'...' if len(item['text']) > 45 else ''}"
            for item in assumptions
        ],
        "stations": [f"{item['id']} — {item['name']}" for item in process["stations"]],
        "checks": checks["summary"],
        "checkItems": [
            f"[{item['severity'].upper()}] {item['id']}: "
            f"{item.get('value', 'n/a')} {item.get('unit', '')} / limit {item.get('limit', 'n/a')}"
            for item in checks["items"]
        ],
        "duration": timeline["duration_s"],
        "takt": process["takt"]["target_s"],
        "coverage": (
            f"{len([n for n in timeline['nodes'] if n.startswith('workpiece.')])}/"
            f"{len(workpiece['skus'][0].get('covers', []))}"
        ),
        "step": step,
        "snapshot": str(
            next(
                iter(_review_snapshots(project, version_dir, checks)),
                project / "build" / "snapshot_station_s3.png",
            ).resolve()
        ),
    }
    data_path = target.with_suffix(".deck-data.json")
    data_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    script = source_root() / "tools" / "build_deck.ps1"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-DataPath",
                str(data_path),
                "-OutputPath",
                str(target.resolve()),
            ],
            check=True,
            timeout=90,
            capture_output=True,
            creationflags=flags,
        )
    finally:
        data_path.unlink(missing_ok=True)
    return target


def _html(project: Path, version_dir: Path, target: Path) -> Path:
    scene = base64.b64encode((version_dir / "scene.glb").read_bytes()).decode("ascii")
    timeline = json.loads((version_dir / "timeline.json").read_text("utf-8"))
    checks = json.loads((version_dir / "checks.json").read_text("utf-8"))
    title = str(load_yaml(project / "project.yaml")["name"])
    bundle_candidates = (
        source_root() / "web" / "dist" / "offline.js",
        Path(__file__).resolve().parent / "_viewer" / "offline.js",
        Path(__file__).resolve().parent / "_offline_viewer.js",
    )
    bundle_path = next((path for path in bundle_candidates if path.is_file()), None)
    if bundle_path is None:
        raise FileNotFoundError("缺少離線 3D viewer bundle；請先在 web 執行 npm run build")
    bundle = bundle_path.read_text("utf-8").replace("</script", "<\\/script")
    payload = json.dumps(
        {"scene": scene, "timeline": timeline, "checks": checks, "title": title},
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("</script", "<\\/script")
    shell = (Path(__file__).resolve().parent / "_offline_viewer.html").read_text("utf-8")
    document = (
        shell.replace("__TITLE__", html_lib.escape(title))
        .replace("__VERSION__", version_dir.name)
        .replace("__PAYLOAD__", payload)
        .replace("__BUNDLE__", bundle)
    )
    target.write_text(document, encoding="utf-8")
    return target


def _review_snapshots(project: Path, version_dir: Path, checks: dict[str, Any]) -> list[Path]:
    candidates: dict[Path, float] = {}
    for directory in (version_dir, project / "build"):
        if not directory.is_dir():
            continue
        for path in directory.glob("snapshot_t*.png"):
            match = re.match(r"snapshot_t(-?\d+(?:\.\d+)?)_", path.name)
            if match:
                candidates[path] = float(match.group(1))
    desired = []
    for severity in ("red", "yellow"):
        timed = [
            item
            for item in checks.get("items", [])
            if item.get("severity") == severity and isinstance(item.get("t"), int | float)
        ]
        if timed:
            desired.append(float(max(timed, key=_check_badness)["t"]))
    selected: list[Path] = []
    for check_time in desired:
        available = [path for path in candidates if path not in selected]
        if available:
            selected.append(min(available, key=lambda path: abs(candidates[path] - check_time)))
    if selected:
        return selected
    return [
        path
        for path in (
            project / "build" / "snapshot_t0_iso.png",
            project / "build" / "snapshot_station_s3.png",
        )
        if path.is_file()
    ]


def _check_badness(item: dict[str, Any]) -> float:
    distance = item.get("min_dist_mm")
    if isinstance(distance, int | float):
        return -float(distance)
    value, limit = item.get("value"), item.get("limit")
    if isinstance(value, int | float) and isinstance(limit, int | float):
        return abs(float(value) - float(limit)) / max(abs(float(limit)), 1e-9)
    return 0.0


def _safe_name(value: str) -> str:
    return (
        "".join(char if char.isalnum() or char in "-_" else "_" for char in value).strip("_")
        or "cellforge"
    )
