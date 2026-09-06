"""manage.py precision：精度驗證與 GR&R 報告（WP-13）。

    manage.py precision <flow> [--mode repeatability|reproducibility|grr] [--source ID] [--repeat 30]
                        [--parts-dir DIR | --parts N] [--tolerance name=T ...] [--reference name=X ...]
                        [--output report.json] [--markdown report.md] [--max-sigma [name=]S ...] [--max-grr PCT] [--json]

- repeatability：同一張影像跑 N 次；reproducibility：同一件重新取像 N 次；grr：多件 × 多次。
- GR&R 的零件影像：`--parts-dir` 每個子資料夾一件（檔案＝試驗），或 `--parts N` 用來源現場取像（每件提示放料後 Enter、連拍 --repeat 張；
  `--no-prompt` 不等）。
- `--max-sigma`／`--max-grr` 是 CI 門檻：不合格離開碼 1（JSON 也照樣輸出）。
"""

from __future__ import annotations

import json
import os
import sys

import cv2
import numpy as np
from django.core.management.base import BaseCommand, CommandError

from apps.vision import precision, serialize


def _kv(pairs: list[str], what: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for item in pairs or []:
        if "=" not in item:
            raise CommandError(f"--{what} expects name=value, got {item!r}")
        k, v = item.split("=", 1)
        try:
            out[k.strip()] = float(v)
        except ValueError:
            raise CommandError(f"--{what} {item!r}: value is not a number") from None
    return out


def _sigma_limits(pairs: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for item in pairs or []:
        if "=" in item:
            k, v = item.split("=", 1)
        else:
            k, v = "*", item
        try:
            out[k.strip()] = float(v)
        except ValueError:
            raise CommandError(f"--max-sigma {item!r}: value is not a number") from None
    return out


def _read_parts_dir(folder: str) -> dict[str, list[np.ndarray]]:
    parts: dict[str, list[np.ndarray]] = {}
    for name in sorted(os.listdir(folder)):
        sub = os.path.join(folder, name)
        if not os.path.isdir(sub):
            continue
        imgs = []
        for f in sorted(os.listdir(sub)):
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")):
                img = cv2.imdecode(np.fromfile(os.path.join(sub, f), dtype=np.uint8), cv2.IMREAD_COLOR)
                if img is not None:
                    imgs.append(img)
        if imgs:
            parts[name] = imgs
    if not parts:
        raise CommandError(f"{folder}: no part folders with pictures (each sub-folder is one part, each file one trial)")
    return parts


class Command(BaseCommand):
    help = "精度驗證：重複性、再現性、GR&R（AIAG MSA 4th ed.），輸出 JSON 與 markdown 報告"

    def add_arguments(self, parser):
        parser.add_argument("flow", help="流程 id 或名稱")
        parser.add_argument("--mode", choices=precision.MODES, default="repeatability")
        parser.add_argument("--source", type=int, default=None, help="影像來源 id（不給就用流程自己的來源）")
        parser.add_argument("--repeat", type=int, default=30, help="重複次數（grr 模式＝每件連拍張數）")
        parser.add_argument("--parts-dir", dest="parts_dir", default="", help="GR&R：每個子資料夾一件、每個檔案一次試驗")
        parser.add_argument("--parts", type=int, default=0, help="GR&R：現場取像的件數（每件提示放料後 Enter）")
        parser.add_argument("--no-prompt", action="store_true", dest="no_prompt", help="GR&R 現場取像不等 Enter")
        parser.add_argument("--tolerance", action="append", default=[], help="name=T，該輸出的公差帶寬（可多個）")
        parser.add_argument("--reference", action="append", default=[], help="name=X，該輸出的標準件真值（Cgk 用）")
        parser.add_argument("--output", default="", help="JSON 報告路徑")
        parser.add_argument("--markdown", default="", help="markdown 報告路徑")
        parser.add_argument("--max-sigma", action="append", default=[], dest="max_sigma", help="CI 門檻：[name=]σ 上限（沒有 name 就是全部）")
        parser.add_argument("--max-grr", type=float, default=None, dest="max_grr", help="CI 門檻：%%GR&R 上限")
        parser.add_argument("--json", action="store_true", dest="as_json", help="stdout 印 JSON 而不是摘要")

    def handle(self, *args, **opts):
        flow = serialize.find_flow(opts["flow"])
        if flow is None:
            raise CommandError(f"Flow {opts['flow']!r} not found")
        tolerance = _kv(opts["tolerance"], "tolerance")
        reference = _kv(opts["reference"], "reference")
        parts = None
        if opts["mode"] == "grr":
            if opts["parts_dir"]:
                parts = _read_parts_dir(opts["parts_dir"])
            elif opts["parts"] >= 2:
                parts = self._grab_parts(opts["parts"], opts["repeat"], opts["source"], flow, opts["no_prompt"])
            else:
                raise CommandError("GR&R needs --parts-dir <dir> or --parts N (with a live source)")

        def progress(done: int, total: int) -> None:
            if not opts["as_json"] and sys.stderr.isatty():
                self.stderr.write(f"\r  {done}/{total}", ending="")

        try:
            result = precision.study(flow, opts["mode"], repeat=opts["repeat"], source_id=opts["source"], parts=parts, tolerance=tolerance, reference=reference, on_progress=progress)
        except precision.PrecisionError as exc:
            raise CommandError(str(exc)) from None
        md = precision.markdown_report(result)
        failures = precision.check_limits(result, _sigma_limits(opts["max_sigma"]), opts["max_grr"])
        result["limits"] = {"failures": failures, "passed": not failures}
        if opts["output"]:
            with open(opts["output"], "w", encoding="utf-8") as fh:
                json.dump(result, fh, ensure_ascii=False, indent=2, default=str)
        if opts["markdown"]:
            with open(opts["markdown"], "w", encoding="utf-8") as fh:
                fh.write(md)
        if opts["as_json"]:
            self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        else:
            self.stdout.write(md)
            if failures:
                self.stdout.write(self.style.ERROR("FAIL: " + "; ".join(failures)))
            elif opts["max_sigma"] or opts["max_grr"] is not None:
                self.stdout.write(self.style.SUCCESS("PASS (limits met)"))
        if failures:
            raise CommandError("precision limits not met: " + "; ".join(failures))

    def _grab_parts(self, n_parts: int, repeat: int, source_id: int | None, flow, no_prompt: bool) -> dict[str, list[np.ndarray]]:
        from apps.vision.runner import runner
        from apps.vision.sources import grab_by_id

        sid = source_id if source_id is not None else precision._flow_source_id(runner.compiled_for(flow))
        if sid is None:
            raise CommandError("No image source: pass --source")
        parts: dict[str, list[np.ndarray]] = {}
        for k in range(1, n_parts + 1):
            if not no_prompt:
                input(f"Place part {k} of {n_parts} and press Enter... ")
            imgs = []
            for _ in range(max(2, repeat)):
                img = grab_by_id(sid)
                if img is None:
                    raise CommandError(f"Source {sid} did not return a picture")
                imgs.append(img)
            parts[f"part_{k:02d}"] = imgs
            self.stderr.write(f"  part {k}: {len(imgs)} pictures")
        return parts
