"""manage.py flow export|import|run —— 讓流程能進 git、能在 CI 跑。

  flow export <id|name> -o path
  flow import path [--source <id>] [--owner <username>]
  flow run <id|name|file> [--source <id>] [--images <dir>] [--json]
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import cv2
import numpy as np
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from apps.core.errors import APIError
from apps.vision import serialize
from apps.vision.models import Flow, ImageSource

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp")


def read_image(path: str) -> np.ndarray | None:
    """Windows 中文路徑：np.fromfile + imdecode。"""
    try:
        data = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    image = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if image is None:
        return None
    if image.ndim == 3 and image.shape[2] == 4:
        image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    return image


def list_images(folder: str) -> list[str]:
    if not os.path.isdir(folder):
        raise CommandError(f"資料夾不存在：{folder}")
    return sorted(os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(IMAGE_EXTS))


class Command(BaseCommand):
    help = "流程匯出／匯入／命令列執行"

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="sub", required=True)
        p_exp = sub.add_parser("export", help="匯出成穩定序列化的 .flow.json")
        p_exp.add_argument("flow", help="流程 id 或名稱")
        p_exp.add_argument("-o", "--output", default="", help="輸出檔路徑（省略則印到 stdout）")

        p_imp = sub.add_parser("import", help="依 name upsert 匯入")
        p_imp.add_argument("path")
        p_imp.add_argument("--source", type=int, default=None, help="把 {SOURCE} 換成這個影像來源 id")
        p_imp.add_argument("--owner", default="", help="新建流程的擁有者 username")

        p_run = sub.add_parser("run", help="執行一次或整個資料夾")
        p_run.add_argument("flow", help="流程 id、名稱或 .flow.json 檔案")
        p_run.add_argument("--source", type=int, default=None, help="檔案內 {SOURCE} 要換成的來源 id")
        p_run.add_argument("--images", default="", help="資料夾：每張影像以 input_image 各跑一次")
        p_run.add_argument("--json", action="store_true", dest="as_json")

    def handle(self, *args, **opts):
        sub = opts["sub"]
        try:
            if sub == "export":
                return self._export(opts)
            if sub == "import":
                return self._import(opts)
            if sub == "run":
                return self._run(opts)
        except APIError as exc:
            raise CommandError(f"{exc.code}: {exc.message}") from None
        raise CommandError(f"未知子命令 {sub}")

    # -- export -------------------------------------------------------------
    def _export(self, opts):
        flow = serialize.find_flow(opts["flow"])
        if flow is None:
            raise CommandError(f"流程不存在：{opts['flow']}")
        doc = serialize.export_flow(flow)
        out = opts["output"]
        if out:
            os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
            serialize.write_file(doc, out)
            self.stderr.write(f"已匯出 {flow.name}（v{flow.version}）→ {out}")
        else:
            self.stdout.write(serialize.dumps(doc), ending="")

    # -- import -------------------------------------------------------------
    def _import(self, opts):
        path = opts["path"]
        if not os.path.isfile(path):
            raise CommandError(f"檔案不存在：{path}")
        with open(path, "rb") as f:
            doc = serialize.parse(f.read())
        source_id = opts["source"]
        if source_id is not None and not ImageSource.objects.filter(pk=source_id).exists():
            raise CommandError(f"影像來源 {source_id} 不存在")
        owner = None
        if opts["owner"]:
            owner = User.objects.filter(username=opts["owner"]).first()
            if owner is None:
                raise CommandError(f"使用者不存在：{opts['owner']}")
        flow, created = serialize.import_flow(doc, source_id=source_id, owner=owner)
        self.stdout.write(f"{'建立' if created else '更新'} {flow.name}（id={flow.id}, v{flow.version}）")

    # -- run ----------------------------------------------------------------
    def _run(self, opts):
        from apps.vision.runner import runner

        ref = opts["flow"]
        graph_override = None
        if os.path.isfile(ref):
            with open(ref, "rb") as f:
                doc = serialize.parse(f.read())
            graph_override = serialize.materialize_graph(doc, source_id=opts["source"])
            flow = Flow(id=0, name=doc["name"], graph=graph_override, version=0)
        else:
            flow = serialize.find_flow(ref)
            if flow is None:
                raise CommandError(f"流程不存在：{ref}")
        rows: list[dict[str, Any]] = []
        if opts["images"]:
            paths = list_images(opts["images"])
            if not paths:
                raise CommandError("資料夾內沒有影像")
            for path in paths:
                image = read_image(path)
                name = os.path.basename(path)
                if image is None:
                    rows.append({"name": name, "status": "failed", "outputs": {}, "duration_ms": 0, "error": "無法解碼"})
                    continue
                report = runner.run_sync(flow, trigger="cli", input_image=image, graph_override=graph_override)
                rows.append(self._row(name, report))
        else:
            report = runner.run_sync(flow, trigger="cli", graph_override=graph_override)
            rows.append(self._row(flow.name, report))
        if opts["as_json"]:
            self.stdout.write(json.dumps({"flow": flow.name, "items": rows, "total": len(rows), "ok": sum(r["status"] == "ok" for r in rows), "ng": sum(r["status"] == "ng" for r in rows), "failed": sum(r["status"] not in ("ok", "ng") for r in rows)}, ensure_ascii=False, indent=2))
        else:
            for r in rows:
                line = f"{r['status']:<7} {r['duration_ms']:>8.1f} ms  {r['name']}  {json.dumps(r['outputs'], ensure_ascii=False)}"
                if r.get("error"):
                    line += f"  !! {r['error']}"
                self.stdout.write(line)
        if any(r["status"] not in ("ok", "ng") for r in rows):
            sys.exit(2)

    @staticmethod
    def _row(name: str, report) -> dict[str, Any]:
        return {"name": name, "run_id": report.id, "status": report.status, "outputs": report.outputs, "duration_ms": round(report.duration_ms, 2), "error": report.error}
