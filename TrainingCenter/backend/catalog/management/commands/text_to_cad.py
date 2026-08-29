"""用 Zoo (KittyCAD) Text-to-CAD API 由文字產生 3D CAD（glb），掛到設備或元件。

前置：
  1. 到 https://zoo.dev 申請 API key，設定環境變數 ZOO_API_KEY
  2. 需要對外網路

用法：
  python manage.py text_to_cad component aoi/camera --prompt "industrial GigE camera, 29x29x42 mm box with C-mount lens thread"
  python manage.py text_to_cad component aoi/camera            # 用 seed 的 model_prompt 或自動由名稱組合
  python manage.py text_to_cad equipment aoi --prompt "..."     # 整台設備（品質有限，建議只用於單一元件）
  python manage.py text_to_cad component --all-missing          # 補所有有 model_prompt 但沒有 model_file 的元件

限制（實務經驗）：
  - Text-to-CAD 適合幾何簡單的單一零件（法蘭、支架、氣缸、感測器外殼），整台機台或多零件組合幾乎不可用。
  - 產生需 30 秒～數分鐘，指令會輪詢直到完成；失敗會回報原因。
  - 產出的 glb 沒有材質與顏色，前端以金屬材質顯示。
"""

import json
import os
import re
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from catalog.models import Component, Equipment

API = "https://api.zoo.dev"


def _req(method: str, path: str, key: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = Request(f"{API}{path}", data=data, method=method, headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": "TrainingCenter/1.0",
    })
    try:
        with urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except HTTPError as e:
        raise CommandError(f"Zoo API {e.code}: {e.read().decode(errors='ignore')[:300]}") from e


def generate_glb(prompt: str, key: str, timeout_s: int = 600, log=print) -> bytes:
    """送出 text-to-cad 任務並輪詢直到完成，回傳 glb bytes。"""
    job = _req("POST", "/ai/text-to-cad/glb?kcl=true", key, {"prompt": prompt})
    job_id = job["id"]
    log(f"  任務 {job_id} 已送出，等待產生…")
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        time.sleep(5)
        st = _req("GET", f"/user/text-to-cad/{job_id}", key)
        status = st.get("status")
        if status == "completed":
            outputs = st.get("outputs") or {}
            # outputs: {"source.glb": "<base64>"}
            import base64
            for name, b64 in outputs.items():
                if name.endswith(".glb"):
                    return base64.b64decode(b64)
            raise CommandError("完成但沒有 glb 輸出")
        if status == "failed":
            raise CommandError(f"產生失敗：{st.get('error')}")
        log(f"  … {status} ({int(time.time() - t0)} s)")
    raise CommandError("逾時")


class Command(BaseCommand):
    help = "用 Zoo Text-to-CAD 由文字產生 glb 並掛到設備或元件"

    def add_arguments(self, parser):
        parser.add_argument("kind", choices=["component", "equipment"])
        parser.add_argument("target", nargs="?", help="component: <設備slug>/<元件slug>；equipment: <設備slug>")
        parser.add_argument("--prompt", help="英文提示詞；省略時用 model_prompt 或由名稱自動組合")
        parser.add_argument("--all-missing", action="store_true", help="component：處理所有有 model_prompt 但無 model_file 的元件")
        parser.add_argument("--dry-run", action="store_true", help="只列出會送出的提示詞")

    def handle(self, *args, **opts):
        key = os.environ.get("ZOO_API_KEY", "")
        if not key and not opts["dry_run"]:
            raise CommandError("請先設定環境變數 ZOO_API_KEY（https://zoo.dev 申請）")
        media = Path(settings.MEDIA_ROOT)

        if opts["kind"] == "equipment":
            eq = Equipment.objects.get(slug=opts["target"])
            prompt = opts["prompt"] or f"industrial automation machine: {eq.summary}"
            self.stdout.write(f"{eq.name}: {prompt}")
            if opts["dry_run"]:
                return
            glb = generate_glb(prompt, key, log=self.stdout.write)
            rel = f"models/{eq.slug}.glb"
            (media / rel).parent.mkdir(parents=True, exist_ok=True)
            (media / rel).write_bytes(glb)
            eq.model_file = rel
            eq.save(update_fields=["model_file"])
            self.stdout.write(self.style.SUCCESS(f"已寫入 {rel}（{len(glb) // 1024} KB）"))
            return

        if opts["all_missing"]:
            comps = list(Component.objects.exclude(model_prompt="").filter(model_file=""))
        else:
            if not opts["target"] or "/" not in opts["target"]:
                raise CommandError("component 需要 <設備slug>/<元件slug>")
            eq_slug, c_slug = opts["target"].split("/", 1)
            comps = [Component.objects.get(module__equipment__slug=eq_slug, slug=c_slug)]

        for c in comps:
            prompt = opts["prompt"] or c.model_prompt or self._auto_prompt(c)
            self.stdout.write(f"{c.name}: {prompt}")
            if opts["dry_run"]:
                continue
            try:
                glb = generate_glb(prompt, key, log=self.stdout.write)
            except CommandError as e:
                self.stderr.write(f"  [ERR] {c.name}: {e}")
                continue
            rel = f"models/components/{c.module.equipment.slug}/{c.slug}.glb"
            (media / rel).parent.mkdir(parents=True, exist_ok=True)
            (media / rel).write_bytes(glb)
            c.model_file = rel
            if not c.model_prompt:
                c.model_prompt = prompt
            c.save(update_fields=["model_file", "model_prompt"])
            self.stdout.write(self.style.SUCCESS(f"  已寫入 {rel}（{len(glb) // 1024} KB）"))

    @staticmethod
    def _auto_prompt(c: Component) -> str:
        # 規格 key 是中文，只取含英數的 value（如 "5 MP", "IP67"）
        specs = ", ".join(str(v) for v in (c.specs or {}).values() if re.search(r"[A-Za-z0-9]", str(v)))
        base = c.photo_query.split("|")[0].replace("cat:", "").split("~")[0].strip() if c.photo_query else c.slug.replace("-", " ")
        return f"{base}, industrial automation part{', ' + specs if specs else ''}"
