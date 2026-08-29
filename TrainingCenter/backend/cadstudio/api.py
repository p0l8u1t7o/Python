from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional
from uuid import UUID

from django.conf import settings
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from catalog.models import Component, Equipment

from . import ai, runner
from .models import CadJob

router = Router(tags=["cad-studio"])
MAX_REPAIR = 2  # AI 模式自動修復次數


class JobIn(Schema):
    mode: str = "ai"          # ai | code
    prompt: str = ""
    code: str = ""
    name: str = ""
    parent_id: Optional[UUID] = None


class JobOut(Schema):
    id: UUID
    created_at: str
    mode: str
    prompt: str
    name: str
    parent_id: Optional[UUID] = None
    code: str
    status: str
    log: str
    error: str
    ai_notes: str
    glb: Optional[str] = None
    step: Optional[str] = None
    stl: Optional[str] = None
    three_mf: Optional[str] = None
    snapshot: Optional[str] = None
    facts: dict

    @staticmethod
    def resolve_created_at(obj: CadJob):
        return obj.created_at.isoformat()

    @staticmethod
    def resolve_parent_id(obj: CadJob):
        return obj.parent_id

    @staticmethod
    def _url(rel: str):
        return settings.MEDIA_URL + rel if rel else None

    @staticmethod
    def resolve_glb(obj: CadJob):
        return JobOut._url(obj.glb)

    @staticmethod
    def resolve_step(obj: CadJob):
        return JobOut._url(obj.step)

    @staticmethod
    def resolve_stl(obj: CadJob):
        return JobOut._url(obj.stl)

    @staticmethod
    def resolve_three_mf(obj: CadJob):
        return JobOut._url(obj.three_mf)

    @staticmethod
    def resolve_snapshot(obj: CadJob):
        return JobOut._url(obj.snapshot)


class LibraryItem(Schema):
    name: str
    signature: str
    doc: str


def _job_dir(job: CadJob) -> Path:
    return Path(settings.MEDIA_ROOT) / job.job_dir_rel


def _work(job_id):
    """背景執行：AI 產碼（可選）→ 建置。"""
    job = CadJob.objects.get(id=job_id)
    try:
        if job.mode == CadJob.Mode.AI:
            job.status = CadJob.Status.GENERATING
            job.save(update_fields=["status"])
            prev_code, prev_err = "", ""
            if job.parent_id:
                parent = CadJob.objects.filter(id=job.parent_id).first()
                if parent:
                    prev_code, prev_err = parent.code, parent.error
            code, notes = ai.generate_code(job.prompt, prev_code, prev_err)
            job.code, job.ai_notes = code, notes
            job.save(update_fields=["code", "ai_notes"])
        job.status = CadJob.Status.BUILDING
        job.save(update_fields=["status"])
        result = runner.build(_job_dir(job), job.code)
        # AI 模式：建置失敗就把錯誤回饋給 AI 重寫（自動修復迴圈，最多 MAX_REPAIR 次）
        attempt = 0
        while not result["ok"] and job.mode == CadJob.Mode.AI and attempt < MAX_REPAIR:
            attempt += 1
            err = "\n".join(result["log"])[-4000:]
            job.status = CadJob.Status.GENERATING
            job.log = f"[自動修復 {attempt}/{MAX_REPAIR}] 上一版建置失敗，請 AI 修正…\n" + err
            job.save(update_fields=["status", "log"])
            code, notes = ai.generate_code(job.prompt, job.code, err)
            job.code = code
            job.ai_notes = (job.ai_notes + f"\n\n--- 自動修復第 {attempt} 次 ---\n" + notes).strip()
            job.status = CadJob.Status.BUILDING
            job.save(update_fields=["code", "ai_notes", "status"])
            result = runner.build(_job_dir(job), job.code)
        job.log = ("\n".join(result["log"]) + (f"\n[自動修復 {attempt} 次]" if attempt else ""))[-20000:]
        if result["ok"]:
            out = result["outputs"]
            rel = job.job_dir_rel
            job.glb = f"{rel}/{out['glb']}" if "glb" in out else ""
            job.step = f"{rel}/{out['step']}" if "step" in out else ""
            job.snapshot = f"{rel}/{out['png']}" if "png" in out else ""
            job.facts = result["facts"]
            job.status = CadJob.Status.DONE
            job.error = ""
        else:
            job.status = CadJob.Status.FAILED
            job.error = job.log[-6000:]
        job.save()
    except Exception as e:  # noqa: BLE001
        job.status = CadJob.Status.FAILED
        job.error = f"{type(e).__name__}: {e}"
        job.save(update_fields=["status", "error"])


@router.get("/env")
def env_status(request):
    """前端啟動時檢查：cadgen 環境、AI 憑證。"""
    info = ai.provider_info()
    return {"cad_ok": runner.check_env() is None, "cad_error": runner.check_env(), "ai_ok": info["ok"],
            "provider": info["provider"], "model": info["model"], "ai_hint": info["hint"]}


@router.get("/library", response=list[LibraryItem])
def library(request):
    items = []
    for line in ai.parts_api_summary().splitlines():
        sig, _, doc = line[2:].partition("  # ")
        name = sig.split("(", 1)[0].replace("parts.", "")
        items.append({"name": name, "signature": sig, "doc": doc})
    return items


@router.get("/jobs", response=list[JobOut])
def list_jobs(request, limit: int = 30):
    return list(CadJob.objects.all()[:limit])


@router.post("/jobs", response=JobOut)
def create_job(request, data: JobIn):
    if data.mode not in ("ai", "code"):
        data.mode = "ai"
    if data.mode == "code" and "def gen_step" not in data.code:
        from ninja.errors import HttpError

        raise HttpError(400, "程式必須定義 gen_step()")
    job = CadJob.objects.create(
        mode=data.mode, prompt=data.prompt, code=data.code, name=data.name[:120],
        parent_id=data.parent_id,
    )
    runner.run_in_thread(_work, job.id)
    return job


@router.get("/jobs/{job_id}", response=JobOut)
def get_job(request, job_id: UUID):
    return get_object_or_404(CadJob, id=job_id)


class ExportIn(Schema):
    format: str  # stl | 3mf


@router.post("/jobs/{job_id}/export", response=JobOut)
def export_job(request, job_id: UUID, data: ExportIn):
    job = get_object_or_404(CadJob, id=job_id)
    if data.format not in ("stl", "3mf"):
        from ninja.errors import HttpError

        raise HttpError(400, "format 必須是 stl 或 3mf")
    res = runner.export_extra(_job_dir(job), data.format)
    if res["ok"]:
        if data.format == "stl":
            job.stl = f"{job.job_dir_rel}/{res['file']}"
        else:
            job.three_mf = f"{job.job_dir_rel}/{res['file']}"
        job.save()
    else:
        job.log += "\n" + "\n".join(res["log"])
        job.save(update_fields=["log"])
    return job


class AttachIn(Schema):
    kind: str      # component | equipment
    target: str    # <設備slug>/<元件slug> 或 <設備slug>


@router.post("/jobs/{job_id}/attach")
def attach_job(request, job_id: UUID, data: AttachIn):
    job = get_object_or_404(CadJob, id=job_id)
    if not job.glb:
        return {"ok": False, "error": "此工作沒有 glb"}
    src = Path(settings.MEDIA_ROOT) / job.glb
    if data.kind == "equipment":
        obj = get_object_or_404(Equipment, slug=data.target)
        rel = f"models/{obj.slug}.glb"
    else:
        eq_slug, _, c_slug = data.target.partition("/")
        obj = get_object_or_404(Component, module__equipment__slug=eq_slug, slug=c_slug)
        rel = f"models/components/{eq_slug}/{c_slug}.glb"
    dest = Path(settings.MEDIA_ROOT) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    obj.model_file = rel
    fields = ["model_file"]
    if hasattr(obj, "model_prompt") and job.prompt:
        obj.model_prompt = job.prompt[:300]
        fields.append("model_prompt")
    obj.save(update_fields=fields)
    return {"ok": True, "attached": rel, "name": str(obj)}


@router.delete("/jobs/{job_id}")
def delete_job(request, job_id: UUID):
    job = get_object_or_404(CadJob, id=job_id)
    shutil.rmtree(_job_dir(job), ignore_errors=True)
    job.delete()
    return {"ok": True}
