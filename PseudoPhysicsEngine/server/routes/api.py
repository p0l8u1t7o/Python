"""Step-1 REST and SSE routes."""

from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import os
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from cellforge import derived
from cellforge.agents import AstraAgent, EngineeringAgent, refresh_theme_local
from cellforge.diffing import diff_versions
from cellforge.exports import export_project
from cellforge.intake import prepare_intake
from cellforge.intake.local import run_local_intake

# D-011：PyMuPDF 必須先於下列會載入 CadQuery/OCP 的模組載入。
from cellforge.module_cache import cached_check, cached_preview, cached_render
from cellforge.module_service import (
    module_detail,
    module_summary,
    project_modules,
    promote_part,
    promotion_check,
    resolve_project_module,
)
from cellforge.procutil import ProcessTimeoutError, run_streaming
from cellforge.project import (
    create_project,
    resolve_inside,
    resolve_project,
    unique_project_dir,
)
from cellforge.questions import update_questions
from cellforge.schema import Questions
from cellforge.trash import (
    TrashError,
    list_trash,
    move_to_trash,
    purge_trash,
    restore_from_trash,
)
from cellforge.version_store import BUILD_JOB_ENV, BUILD_ORIGIN_ENV
from cellforge.versioning import (
    MANIFEST_NAME,
    VersionContext,
    VersionError,
    VersionNotFoundError,
    commit_changes,
    try_commit_changes,
    version_dirs,
)
from cellforge.workflow import (
    WorkflowPreconditionError,
    inputs_fingerprint,
    intake_state,
    record_intake,
    require_first_build_ready,
    versions_for_job,
    written_since,
)
from cellforge.yamlio import dump_yaml, load_yaml
from server.jobs import current_job_id

PLATFORM_ROOT = Path(__file__).resolve().parents[2]
# intake 必須在本次工作中重新產生的輸出；舊檔案不能冒充這次的結果。
INTAKE_OUTPUTS = ["analysis/intake.md", "analysis/checklist_map.md", "analysis/questions.yaml"]


async def _cell_json(
    project: Path,
    args: list[str],
    *,
    purpose: str,
    timeout_s: float,
    origin: str | None = None,
) -> tuple[int, dict[str, Any] | None, str]:
    """Run ``cell ... --json`` in a subprocess so native OCP crashes cannot take down the API.

    取消 job 時整棵子程序樹一併結束，被中斷的建置只會留下之後自動回收的 staging。
    """

    environment = os.environ.copy()
    if job_id := current_job_id():
        environment[BUILD_JOB_ENV] = job_id
    if origin:
        environment[BUILD_ORIGIN_ENV] = origin
    stdout: list[str] = []
    stderr: list[str] = []
    try:
        code = await run_streaming(
            [sys.executable, "-m", "cellforge.cli", *args, "--project", str(project), "--json"],
            cwd=PLATFORM_ROOT,
            env=environment,
            timeout_s=timeout_s,
            on_stdout=stdout.append,
            on_stderr=stderr.append,
        )
    except ProcessTimeoutError as error:
        raise ValueError(f"{purpose}超過 {timeout_s:.0f} 秒，已停止") from error
    payload = None
    for line in reversed(stdout):
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            payload = candidate
            break
    detail = (payload or {}).get("message") or "\n".join(stderr[-20:]) or f"退出碼 {code}"
    return code, payload, str(detail)


def _commit_or_warn(project: Path, emit, message: str, paths: list[str]) -> str | None:
    """工作已完成後的 git 提交；失敗只記警告，不把完成的工作改判失敗。"""
    warning = try_commit_changes(project, message, paths)
    if warning:
        emit("warning", {"message": warning})
    return warning


async def _local_build(project: Path, request: Request, origin: str) -> dict[str, Any]:
    code, payload, detail = await _cell_json(
        project,
        ["build", "--level", "L1"],
        purpose="本機建置",
        timeout_s=float(request.app.state.settings.get("build_timeout_s", 900)),
        origin=origin,
    )
    if code != 0 or payload is None or payload.get("status") != "ok":
        raise ValueError(f"本機建置失敗：{detail}")
    return payload


async def _verify_job_version(
    project: Path, request: Request, *, require_level: str | None = "L1"
) -> dict[str, Any]:
    """Success means: this job published a version and it reads back completely."""

    job_id = current_job_id()
    produced = versions_for_job(project, job_id) if job_id else []
    if not produced:
        raise ValueError("本次工作沒有發布任何版本（案子既有的版本不算數）；請檢查建置紀錄後重試")
    latest = produced[-1]
    code, payload, detail = await _cell_json(
        project,
        ["version", "verify", latest.name],
        purpose="版本回讀驗證",
        timeout_s=float(request.app.state.settings.get("verify_timeout_s", 300)),
    )
    if code != 0 or payload is None or payload.get("status") != "ok":
        raise ValueError(f"本次工作發布的 {latest.name} 回讀驗證失敗：{detail}")
    if require_level and payload.get("level") != require_level:
        raise ValueError(
            f"本次工作發布的 {latest.name} 為 {payload.get('level')}，first_build 必須產生 "
            f"{require_level} 版本"
        )
    return {
        "version": int(latest.name[1:]),
        "version_id": latest.name,
        "job_versions": [path.name for path in produced],
        "verification": payload,
    }


router = APIRouter(prefix="/api")


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "CellForge",
        "pid": os.getpid(),
        "projects_root": str(_root(request)),
    }


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1)
    customer: str = ""
    product: str = ""
    description: str = ""
    constraints: dict[str, Any] = Field(default_factory=dict)
    seed_example: str | None = None


class QuestionUpdate(BaseModel):
    answer: str | None = None
    skip: bool = False
    skip_all: bool = False


class AssumptionUpdate(BaseModel):
    text: str


class ChangeCreate(BaseModel):
    text: str
    object: str | None = None
    t: float | None = None


class TaskCreate(BaseModel):
    owner: Literal["engineering", "astra"]
    text: str
    depends: list[str] = Field(default_factory=list)


class ExportCreate(BaseModel):
    kinds: list[str]
    version: str | None = None


def _root(request: Request) -> Path:
    return request.app.state.projects_root


def _catalog_root(request: Request) -> Path:
    return request.app.state.catalog_root


def _module_cache_root(request: Request) -> Path:
    return request.app.state.module_cache_root


def _jobs(request: Request):
    return request.app.state.jobs


def _agent(request: Request) -> EngineeringAgent:
    settings = request.app.state.settings
    return EngineeringAgent(
        str(settings.get("engineering_agent_command", "claude")),
        model=settings.get("engineering_agent_model") or None,
        effort=settings.get("engineering_agent_effort") or None,
        timeout_s=float(settings.get("engineering_agent_timeout_s", 1800)),
        max_attempts=int(settings.get("engineering_agent_max_attempts", 3)),
    )


def _local_agent(request: Request) -> bool:
    return request.app.state.settings.get("engineering_agent_mode") == "local"


def _local_astra(request: Request) -> bool:
    return request.app.state.settings.get("astra_agent_mode", "local") == "local"


def _astra(request: Request) -> AstraAgent:
    settings = request.app.state.settings
    return AstraAgent(
        str(settings.get("astra_agent_command", "codex")),
        model=str(settings.get("astra_agent_model", "gpt-6-astra")),
        timeout_s=float(settings.get("astra_agent_timeout_s", 900)),
    )


def _project(request: Request, project_id: str) -> Path:
    try:
        return resolve_project(_root(request), project_id)
    except FileNotFoundError as error:
        raise HTTPException(404, f"找不到案子：{project_id}") from error


def _module_resource(request: Request, project: Path, module_id: str):
    try:
        return resolve_project_module(project, module_id, _catalog_root(request))
    except KeyError as error:
        raise HTTPException(404, str(error)) from error
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        raise HTTPException(422, str(error)) from error


def _check_response(cached) -> dict[str, Any]:
    return {
        **cached.result.as_dict(),
        "params": cached.params,
        "cache": {
            "key": cached.key,
            "hit": cached.hit,
        },
    }


def _refresh_module_artifacts(resource, cache_root: Path) -> dict[str, Any]:
    checked = cached_check(
        resource.source,
        resource.params,
        cache_root=cache_root,
        force=True,
    )
    rendered = cached_render(
        resource.source,
        resource.params,
        cache_root=cache_root,
        force=True,
    )
    previewed = cached_preview(
        resource.source,
        resource.params,
        cache_root=cache_root,
        force=True,
    )
    return {
        "status": "ok",
        "module_id": resource.id,
        "check": _check_response(checked),
        "render": str(rendered.path),
        "preview": str(previewed.path),
        "cache_key": checked.key,
    }


def _versions(project: Path) -> list[dict[str, Any]]:
    versions = []
    for directory in version_dirs(project):
        report_path = directory / "step_validation.json"
        report = json.loads(report_path.read_text("utf-8")) if report_path.is_file() else None
        checks_path = directory / "checks.json"
        checks = (
            json.loads(checks_path.read_text("utf-8")).get("summary", {})
            if checks_path.is_file()
            else {"red": 0, "yellow": 0, "green": 0}
        )
        manifest_path = directory / MANIFEST_NAME
        manifest = json.loads(manifest_path.read_text("utf-8")) if manifest_path.is_file() else None
        generated = (
            manifest["created"]
            if manifest
            else datetime.fromtimestamp(directory.stat().st_mtime).astimezone().isoformat()
        )
        versions.append(
            {
                "id": directory.name,
                "number": int(directory.name[1:]),
                "generated": generated,
                "step": report,
                "checks": checks,
                # 建置完成、工程結論與匯出狀態分開呈現；舊快照沒有 manifest，標為資料不完整。
                "complete": manifest is not None,
                "level": manifest["build"]["level"] if manifest else None,
                "engineering_status": manifest["engineering"]["status"] if manifest else None,
            }
        )
    return versions


@router.get("/projects")
def list_projects(request: Request) -> list[dict[str, Any]]:
    root = _root(request)
    root.mkdir(parents=True, exist_ok=True)
    result = []
    for project in sorted(root.iterdir()):
        config = project / "project.yaml"
        if not project.is_dir() or not config.is_file():
            continue
        data = load_yaml(config)
        versions = _versions(project)
        result.append(
            {
                "id": project.name,
                "name": data.get("name", project.name),
                "customer": data.get("customer", ""),
                "product": data.get("product", ""),
                "latest_version": versions[-1]["id"] if versions else None,
                "checks": versions[-1]["checks"]
                if versions
                else {"red": 0, "yellow": 0, "green": 0},
                "modified": datetime.fromtimestamp(config.stat().st_mtime).astimezone().isoformat(),
            }
        )
    return result


@router.post("/projects", status_code=201)
def post_project(body: ProjectCreate, request: Request) -> dict[str, Any]:
    root = _root(request)
    root.mkdir(parents=True, exist_ok=True)
    directory = unique_project_dir(root, body.name)
    constraints = {
        "robot_brand": None,
        "takt_target_s": None,
        "footprint_mm": None,
        "stations_max": None,
        "safety_notes": "",
        "free_text": "",
        **body.constraints,
    }
    create_project(
        directory,
        {
            "name": body.name,
            "customer": body.customer,
            "product": body.product,
            "description": body.description,
            "constraints": constraints,
            "created": date.today().isoformat(),
        },
        seed_example=body.seed_example,
    )
    return {"id": directory.name, "name": body.name}


@router.get("/projects/{project_id}")
def get_project(project_id: str, request: Request) -> dict[str, Any]:
    project = _project(request, project_id)
    data = dict(load_yaml(project / "project.yaml"))
    summary_path = project / "analysis" / "first_build_summary.txt"
    data.update({"id": project_id, "versions": _versions(project)})
    data["first_build_summary"] = (
        summary_path.read_text(encoding="utf-8") if summary_path.is_file() else None
    )
    return data


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, request: Request) -> dict[str, Any]:
    """移到回收區（可還原）；有排隊或執行中的工作時拒絕，避免工作寫入已搬走的目錄。"""
    _project(request, project_id)
    active = request.app.state.jobs.active(project_id)
    if active:
        kinds = "、".join(sorted({job.kind for job in active}))
        raise HTTPException(409, f"案子仍有執行中的工作（{kinds}），請等待完成或取消後再刪除")
    try:
        return move_to_trash(_root(request), request.app.state.trash_root, project_id)
    except TrashError as error:
        raise HTTPException(409, str(error)) from error


@router.get("/trash")
def get_trash(request: Request) -> list[dict[str, Any]]:
    return list_trash(request.app.state.trash_root)


@router.post("/trash/{trash_id}/restore")
def restore_trash(trash_id: str, request: Request) -> dict[str, Any]:
    try:
        return restore_from_trash(_root(request), request.app.state.trash_root, trash_id)
    except TrashError as error:
        raise HTTPException(404 if "沒有這個項目" in str(error) else 409, str(error)) from error


@router.delete("/trash/{trash_id}")
def purge_trash_item(trash_id: str, request: Request) -> dict[str, Any]:
    try:
        purge_trash(request.app.state.trash_root, trash_id)
    except TrashError as error:
        raise HTTPException(404 if "沒有這個項目" in str(error) else 409, str(error)) from error
    return {"trash_id": trash_id, "purged": True}


@router.get("/library/modules")
def get_library_modules(request: Request) -> dict[str, Any]:
    manifest = _catalog_root(request) / "library" / "manifest.yaml"
    if not manifest.is_file():
        raise HTTPException(404, "找不到模組庫 manifest")
    payload = load_yaml(manifest)
    if not isinstance(payload, dict):
        raise HTTPException(500, "模組庫 manifest 格式錯誤")
    return dict(payload)


@router.get("/projects/{project_id}/modules")
def get_project_modules(project_id: str, request: Request) -> dict[str, Any]:
    project = _project(request, project_id)
    try:
        resources = project_modules(project, _catalog_root(request))
        modules = [module_summary(resource, _module_cache_root(request)) for resource in resources]
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        raise HTTPException(422, str(error)) from error
    return {"modules": modules}


@router.get("/projects/{project_id}/modules/{module_id}")
def get_project_module_detail(project_id: str, module_id: str, request: Request) -> dict[str, Any]:
    project = _project(request, project_id)
    resource = _module_resource(request, project, module_id)
    try:
        return module_detail(resource)
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        raise HTTPException(422, str(error)) from error


@router.get("/projects/{project_id}/modules/{module_id}/check")
def get_project_module_check(project_id: str, module_id: str, request: Request) -> JSONResponse:
    project = _project(request, project_id)
    resource = _module_resource(request, project, module_id)
    try:
        checked = cached_check(
            resource.source,
            resource.params,
            cache_root=_module_cache_root(request),
        )
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        raise HTTPException(422, str(error)) from error
    return JSONResponse(
        _check_response(checked),
        headers={"X-CellForge-Cache": "hit" if checked.hit else "miss"},
    )


@router.get("/projects/{project_id}/modules/{module_id}/render.png")
def get_project_module_render(project_id: str, module_id: str, request: Request) -> FileResponse:
    project = _project(request, project_id)
    resource = _module_resource(request, project, module_id)
    try:
        rendered = cached_render(
            resource.source,
            resource.params,
            cache_root=_module_cache_root(request),
        )
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        raise HTTPException(422, str(error)) from error
    return FileResponse(
        rendered.path,
        media_type="image/png",
        headers={"X-CellForge-Cache": "hit" if rendered.hit else "miss"},
    )


@router.get("/projects/{project_id}/modules/{module_id}/preview.glb")
def get_project_module_preview(project_id: str, module_id: str, request: Request) -> FileResponse:
    project = _project(request, project_id)
    resource = _module_resource(request, project, module_id)
    try:
        previewed = cached_preview(
            resource.source,
            resource.params,
            cache_root=_module_cache_root(request),
        )
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        raise HTTPException(422, str(error)) from error
    return FileResponse(
        previewed.path,
        media_type="model/gltf-binary",
        headers={"X-CellForge-Cache": "hit" if previewed.hit else "miss"},
    )


@router.post("/projects/{project_id}/modules/{module_id}/recheck", status_code=202)
async def recheck_project_module(
    project_id: str, module_id: str, request: Request
) -> dict[str, Any]:
    project = _project(request, project_id)
    resource = _module_resource(request, project, module_id)
    cache_root = _module_cache_root(request)

    async def worker(emit):
        emit("progress", {"progress": 0.05, "message": "正在重新檢查模組"})
        result = await asyncio.to_thread(_refresh_module_artifacts, resource, cache_root)
        emit("progress", {"progress": 1.0, "message": "模組檢查與預覽已更新"})
        return result

    job = _jobs(request).submit(project_id, "module_recheck", worker)
    return job.public()


@router.post("/projects/{project_id}/modules/{module_id}/fix", status_code=202)
async def fix_project_module(project_id: str, module_id: str, request: Request) -> dict[str, Any]:
    project = _project(request, project_id)
    resource = _module_resource(request, project, module_id)
    try:
        checked = cached_check(
            resource.source,
            resource.params,
            cache_root=_module_cache_root(request),
        )
    except (ImportError, OSError, ValueError) as error:
        raise HTTPException(422, str(error)) from error
    findings = [item for item in checked.result.items if item.severity in {"fail", "warn"}]
    if not findings:
        raise HTTPException(409, f"模組 {module_id} 沒有需要代理修正的失敗或警告")
    lines = "\n".join(
        f"- [{item.severity}] {item.index} {item.code}：{item.message}" for item in findings
    )
    change_text = (
        f"請修正案內模組 {module_id} 的品質檢查結果：\n{lines}\n"
        f"完成後執行 cell part check {module_id} --project {project} --json。"
    )
    change_id = _write_change(
        project,
        change_text,
        source=f"模組品質檢查 / {module_id}",
    )
    task = _write_task(
        project,
        owner="engineering",
        text=change_text,
        created_by=f"module_fix:{module_id}",
        status="queued",
    )
    task_path = project / "tasks" / f"{task['id']}.yaml"

    async def worker(emit):
        task["status"] = "running"
        dump_yaml(task_path, task)
        try:
            if _local_agent(request):
                result = {
                    "status": "ok",
                    "mode": "local",
                    "change_id": change_id,
                    "module_id": module_id,
                    "task_id": task["id"],
                }
            else:
                result = await _agent(request).run(
                    "apply_cr",
                    project,
                    emit,
                    context=f"CR: {change_id}\nModule: {module_id}\n{change_text}",
                    job_id=current_job_id(),
                )
            task["status"] = "done"
            task["result"] = result
            return result
        except Exception:
            task["status"] = "failed"
            raise
        finally:
            dump_yaml(task_path, task)
            _commit_or_warn(
                project,
                emit,
                f"apply {change_id}",
                ["parts", "changes", "tasks", ".cellforge"],
            )

    job = _jobs(request).submit(project_id, "module_fix", worker)
    return {**job.public(), "change_id": change_id, "task_id": task["id"]}


@router.post("/projects/{project_id}/modules/{module_id}/promote", status_code=202)
async def promote_project_module(
    project_id: str, module_id: str, request: Request
) -> dict[str, Any]:
    project = _project(request, project_id)
    cache_root = _module_cache_root(request)
    try:
        promotion_check(project, module_id, cache_root=cache_root)
    except (ImportError, OSError, ValueError) as error:
        raise HTTPException(409, str(error)) from error
    catalog_root = _catalog_root(request)

    async def worker(emit):
        emit("progress", {"progress": 0.1, "message": "正在把案內模組收進模組庫"})
        entry = await asyncio.to_thread(
            promote_part,
            project,
            module_id,
            catalog_root=catalog_root,
            cache_root=cache_root,
        )
        _commit_or_warn(project, emit, f"promote module {module_id}", ["cell.yaml", "parts"])
        emit("progress", {"progress": 1.0, "message": "模組已收進共用模組庫"})
        return {"status": "ok", "module": entry}

    job = _jobs(request).submit(project_id, "module_promote", worker)
    return job.public()


@router.post("/projects/{project_id}/files", status_code=201)
async def upload_file(
    project_id: str,
    request: Request,
    file: Annotated[UploadFile, File()],
    kind: Annotated[str, Form()] = "other",
    note: Annotated[str, Form()] = "",
) -> dict[str, Any]:
    project = _project(request, project_id)
    filename = Path(file.filename or "upload.bin").name
    target = project / "inputs" / filename
    stem, suffix = target.stem, target.suffix
    sequence = 2
    while target.exists():
        target = target.with_name(f"{stem}_{sequence}{suffix}")
        sequence += 1
    digest = hashlib.sha256()
    with target.open("wb") as handle:
        while chunk := await file.read(1024 * 1024):
            digest.update(chunk)
            handle.write(chunk)
    manifest_path = project / "inputs" / "manifest.yaml"
    manifest = load_yaml(manifest_path) or {"files": []}
    entry = {
        "path": target.relative_to(project).as_posix(),
        "kind": kind,
        "note": note,
        "sha256": digest.hexdigest(),
        "added": datetime.now().astimezone().isoformat(),
    }
    manifest.setdefault("files", []).append(entry)
    dump_yaml(manifest_path, manifest)
    commit_changes(project, f"upload {target.name}", ["inputs"])
    return entry


@router.get("/projects/{project_id}/files")
def get_files(project_id: str, request: Request) -> dict[str, Any]:
    project = _project(request, project_id)
    return dict(load_yaml(project / "inputs" / "manifest.yaml") or {"files": []})


@router.get("/projects/{project_id}/files/content")
def get_file_content(project_id: str, path: str, request: Request) -> FileResponse:
    project = _project(request, project_id)
    try:
        target = resolve_inside(project, path)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    if not target.is_file() or target.parent != project / "inputs":
        raise HTTPException(404, "找不到檔案")
    return FileResponse(target, media_type=mimetypes.guess_type(target.name)[0])


@router.post("/projects/{project_id}/intake", status_code=202)
async def start_intake(project_id: str, request: Request) -> dict[str, Any]:
    project = _project(request, project_id)
    mode = "local" if _local_agent(request) else "claude"

    async def worker(emit):
        job_id = current_job_id()
        started = datetime.now().astimezone().isoformat()
        started_epoch = time.time()
        fingerprint = inputs_fingerprint(project)
        state = {
            "job_id": job_id,
            "mode": mode,
            "started": started,
            "fingerprint": fingerprint,
        }
        record_intake(project, status="running", **state)
        try:
            emit("progress", {"progress": 0.05, "message": "開始逐頁擷取 PDF 與 Check List"})
            extraction = await asyncio.to_thread(
                prepare_intake,
                project,
                lambda message: emit("progress", {"progress": 0.2, "message": message}),
            )
            emit("progress", {"progress": 0.35, "message": "工程代理開始判讀全部資料"})
            if mode == "local":
                result = await asyncio.to_thread(run_local_intake, project, extraction)
            else:
                result = await _agent(request).run("intake", project, emit, job_id=job_id)
            stale = written_since(project, INTAKE_OUTPUTS, started_epoch)
            if stale:
                raise ValueError(
                    "intake 結束，但下列輸出不是本次工作產生的，不能沿用舊結果：" + "、".join(stale)
                )
            validation = _validate_intake_outputs(project)
            emit("progress", {"progress": 0.9, "message": "驗證工件、設備與流程草案"})
            code, _payload, detail = await _cell_json(
                project, ["validate"], purpose="草案驗證", timeout_s=300
            )
            if code != 0:
                raise ValueError(f"intake 產生的工程草案未通過 cell validate：{detail}")
            if inputs_fingerprint(project) != fingerprint:
                raise ValueError("intake 進行中輸入資料被修改，結果已過期；請重新執行 intake")
        except asyncio.CancelledError:
            record_intake(project, status="cancelled", error="工作已取消", **state)
            try_commit_changes(project, "engineering intake cancelled", ["analysis"])
            raise
        except Exception as error:
            record_intake(project, status="failed", error=str(error), **state)
            try_commit_changes(project, "engineering intake failed", ["analysis"])
            raise
        payload = {**result, **validation, "files": extraction["file_count"], "mode": mode}
        record_intake(project, status="succeeded", result=validation, **state)
        emit("progress", {"progress": 1.0, "message": "解析、問題、對照表與草案驗證完成"})
        if warning := _commit_or_warn(
            project,
            emit,
            "engineering intake",
            ["analysis", "workpiece.yaml", "cell.yaml", "process.yaml"],
        ):
            payload["warnings"] = [warning]
        return payload

    job = _jobs(request).submit(project_id, "intake", worker)
    return job.public()


@router.get("/projects/{project_id}/intake/state")
def get_intake_state(project_id: str, request: Request) -> dict[str, Any]:
    project = _project(request, project_id)
    state = intake_state(project)
    return {
        "state": state,
        "inputs_fingerprint": inputs_fingerprint(project),
        "stale": bool(state) and state.get("inputs_fingerprint") != inputs_fingerprint(project),
    }


def _validate_intake_outputs(project: Path) -> dict[str, Any]:
    questions = Questions.model_validate(load_yaml(project / "analysis" / "questions.yaml"))
    if not 5 <= len(questions.questions) <= 15:
        raise ValueError(f"工程代理問題數必須介於 5～15，目前為 {len(questions.questions)}")
    checklist = (project / "analysis" / "checklist_map.md").read_text("utf-8")
    match = re.search(r"Coverage:\s*(\d+)\s*/\s*(\d+)\s*\(([\d.]+)%\)", checklist)
    if not match:
        raise ValueError("checklist_map.md 缺少 Coverage: M/N (P%) 驗收行")
    mapped, total, percent = int(match.group(1)), int(match.group(2)), float(match.group(3))
    if total and (mapped / total < 0.8 or percent < 80):
        raise ValueError(f"Check List 覆蓋率不足 80%：{mapped}/{total} ({percent:g}%)")
    return {
        "questions": len(questions.questions),
        "checklist_mapped": mapped,
        "checklist_total": total,
        "coverage_percent": percent,
    }


@router.get("/projects/{project_id}/questions")
def get_questions(project_id: str, request: Request) -> dict[str, Any]:
    project = _project(request, project_id)
    return dict(load_yaml(project / "analysis" / "questions.yaml") or {"questions": []})


@router.post("/projects/{project_id}/questions/{question_id}")
def update_question(
    project_id: str, question_id: str, body: QuestionUpdate, request: Request
) -> dict[str, Any]:
    project = _project(request, project_id)
    try:
        changed = update_questions(
            project,
            question_id,
            answer=body.answer,
            skip=body.skip,
            skip_all=body.skip_all,
        )
    except KeyError as error:
        raise HTTPException(404, f"找不到問題：{question_id}") from error
    commit_changes(project, f"update question {question_id}", ["analysis"])
    return {"status": "ok", "questions": changed}


@router.get("/projects/{project_id}/assumptions")
def get_assumptions(project_id: str, request: Request) -> dict[str, Any]:
    project = _project(request, project_id)
    return dict(load_yaml(project / "analysis" / "assumptions.yaml") or {"assumptions": []})


@router.put("/projects/{project_id}/assumptions/{assumption_id}")
async def update_assumption(
    project_id: str, assumption_id: str, body: AssumptionUpdate, request: Request
) -> dict[str, Any]:
    project = _project(request, project_id)
    assumptions = load_yaml(project / "analysis" / "assumptions.yaml") or {"assumptions": []}
    if not any(item["id"] == assumption_id for item in assumptions["assumptions"]):
        raise HTTPException(404, f"找不到假設：{assumption_id}")
    change_id = _write_change(
        project,
        f"覆寫假設 {assumption_id}：{body.text}",
        source=f"使用者 / 假設 {assumption_id}",
    )

    async def worker(emit):
        if _local_agent(request):
            for item in assumptions["assumptions"]:
                if item["id"] == assumption_id:
                    item["status"] = "overridden"
                    item["overridden_by"] = change_id
            dump_yaml(project / "analysis" / "assumptions.yaml", assumptions)
            result = {"status": "ok", "mode": "local", "change_id": change_id}
        else:
            result = await _agent(request).run(
                "assumption_override",
                project,
                emit,
                context=f"Assumption: {assumption_id}\nCR: {change_id}\nNew text: {body.text}",
                job_id=current_job_id(),
            )
        _commit_or_warn(project, emit, f"apply {change_id}", ["analysis", "changes", ".cellforge"])
        return result

    job = _jobs(request).submit(project_id, "assumption_override", worker)
    return {**job.public(), "change_id": change_id}


def _require_first_build_ready(project: Path, request: Request) -> None:
    mode = "local" if _local_agent(request) else "claude"
    try:
        require_first_build_ready(project, mode)
    except WorkflowPreconditionError as error:
        raise HTTPException(409, str(error)) from error
    questions = Questions.model_validate(load_yaml(project / "analysis" / "questions.yaml"))
    open_ids = [question.id for question in questions.questions if question.status == "open"]
    if open_ids:
        raise HTTPException(409, f"尚有未回答或未跳過的問題：{', '.join(open_ids)}")


@router.post("/projects/{project_id}/build", status_code=202)
async def start_build(project_id: str, request: Request) -> dict[str, Any]:
    project = _project(request, project_id)
    _require_first_build_ready(project, request)
    mode = "local" if _local_agent(request) else "claude"

    async def worker(emit):
        # 排隊期間輸入可能被改；開始前再確認一次，失效就不動工。
        try:
            intake = require_first_build_ready(project, mode)
        except WorkflowPreconditionError as error:
            raise ValueError(str(error)) from error
        emit("progress", {"progress": 0.05, "message": "工程代理開始建立初版"})
        if mode == "local":
            result = await _local_build(project, request, origin="local:first_build")
            result.update({"status": "ok", "mode": "local"})
        else:
            result = await _agent(request).run(
                "first_build", project, emit, job_id=current_job_id()
            )
            result["mode"] = "claude"
        claimed = result.get("version")
        emit("progress", {"progress": 0.7, "message": "確認本次工作發布的版本並回讀驗證"})
        verified = await _verify_job_version(project, request, require_level="L1")
        warnings: list[str] = []
        if isinstance(claimed, int) and claimed != verified["version"]:
            warnings.append(
                f"代理回報 v{claimed}，但本次工作實際發布的最新版本是 {verified['version_id']}；"
                "以 manifest 為準"
            )
        result.update(verified)
        result["intake_job"] = intake.get("job_id")
        # 只有正式代理跑完 intake 與 first_build 才可作為代理驗收證據。
        result["agent_acceptance"] = mode == "claude" and intake.get("mode") == "claude"
        # 建置成功與工程通過分開：工程結論取自版本 manifest，未通過時以警告明示。
        engineering = verified["verification"].get("engineering_status")
        result["engineering_status"] = engineering
        if engineering != "pass":
            summary_counts = verified["verification"].get("engineering_summary") or {}
            warnings.append(
                f"{verified['version_id']} 已建置並通過回讀驗證，但工程檢查未通過"
                f"（{engineering}；red {summary_counts.get('red', '?')}、"
                f"yellow {summary_counts.get('yellow', '?')}），僅可作為草案，不是工程驗收。"
            )
        summary = result.get("summary")
        if isinstance(summary, str):
            summary_path = project / "analysis" / "first_build_summary.txt"
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(summary, encoding="utf-8")
        emit("progress", {"progress": 0.82, "message": "Astra 正在刷新主題與 1080p 影片"})
        instruction = "依 render_brief 自動美化並輸出 1080p 工程審查影片"
        if _local_astra(request):
            astra = await asyncio.to_thread(refresh_theme_local, project, instruction)
        else:
            astra = await _astra(request).run(project, instruction, emit)
        result["astra"] = astra
        if warning := _commit_or_warn(
            project,
            emit,
            "Astra presentation refresh",
            ["presentation", "analysis/first_build_summary.txt", ".cellforge/derived"],
        ):
            warnings.append(warning)
        result["warnings"] = [*result.get("warnings", []), *warnings]
        emit("progress", {"progress": 1.0, "message": "建置、檢查與 Astra 交付完成"})
        return result

    job = _jobs(request).submit(project_id, "first_build", worker)
    return job.public()


@router.post("/projects/{project_id}/builds/manual", status_code=202)
async def start_manual_build(project_id: str, request: Request) -> dict[str, Any]:
    """以目前工作區 YAML 直接建置 L1；不經工程代理，結果明確標示不是代理驗收。"""

    project = _project(request, project_id)

    async def worker(emit):
        emit(
            "progress",
            {"progress": 0.05, "message": "手寫資料建置（非代理驗收）：以目前 YAML 建置 L1"},
        )
        result = await _local_build(project, request, origin="manual")
        emit("progress", {"progress": 0.8, "message": "確認本次工作發布的版本並回讀驗證"})
        result.update(await _verify_job_version(project, request, require_level="L1"))
        result.update({"status": "ok", "mode": "manual", "agent_acceptance": False})
        result["engineering_status"] = result["verification"].get("engineering_status")
        if result["engineering_status"] != "pass":
            result["warnings"] = [
                f"{result['version_id']} 已建置，但工程檢查未通過"
                f"（{result['engineering_status']}），僅可作為草案。"
            ]
        return result

    job = _jobs(request).submit(project_id, "manual_build", worker)
    return job.public()


@router.get("/projects/{project_id}/versions")
def get_versions(project_id: str, request: Request) -> list[dict[str, Any]]:
    return _versions(_project(request, project_id))


@router.get("/projects/{project_id}/versions/{version}/costing")
def get_version_costing(project_id: str, version: str, request: Request) -> dict[str, Any]:
    """該版本的成本計算結果（總額、缺價、來源）；只讀版本快照，不重新計算。"""
    project = _project(request, project_id)
    try:
        context = VersionContext.open(project, version)
    except VersionNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    path = context.optional_artifact("costing.json")
    if path is None:
        raise HTTPException(404, f"{context.name} 沒有成本資料（案子缺少 costing.yaml）")
    return json.loads(path.read_text("utf-8"))


@router.get("/projects/{project_id}/versions/{version}/manifest")
def get_version_manifest(project_id: str, version: str, request: Request) -> dict[str, Any]:
    project = _project(request, project_id)
    try:
        context = VersionContext.open(project, version)
    except VersionNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    return {
        "version": context.name,
        "complete": not context.legacy,
        "manifest": context.manifest,
        "warnings": context.warnings,
        "derived": [
            {
                "id": item.entry.get("id"),
                "kind": item.kind,
                "path": item.entry.get("path"),
                "created": item.entry.get("created"),
                "available": item.available,
                "reason": item.reason,
                "settings": item.entry.get("settings", {}),
            }
            for item in derived.artifacts(project, context.name)
        ],
    }


@router.get("/projects/{project_id}/versions/{version}/{asset}")
def get_version_asset(project_id: str, version: str, asset: str, request: Request) -> FileResponse:
    if asset not in {
        "scene.glb",
        "timeline.json",
        "checks.json",
        "render_brief.md",
        "step_validation.json",
        MANIFEST_NAME,
    }:
        raise HTTPException(404, "不支援的版本檔案")
    project = _project(request, project_id)
    try:
        context = VersionContext.open(project, version)
        target = (
            context.directory / MANIFEST_NAME
            if asset == MANIFEST_NAME
            else context.optional_artifact(asset)
        )
    except VersionError as error:
        raise HTTPException(404, str(error)) from error
    if target is None or not target.is_file():
        raise HTTPException(404, "找不到版本檔案")
    return FileResponse(target)


@router.get("/projects/{project_id}/versions/{version}/diff/{other}")
def version_diff(project_id: str, version: str, other: str, request: Request) -> dict[str, Any]:
    project = _project(request, project_id)
    try:
        return diff_versions(project, version, other)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error)) from error


@router.post("/projects/{project_id}/changes", status_code=201)
async def create_change(project_id: str, body: ChangeCreate, request: Request) -> dict[str, Any]:
    project = _project(request, project_id)
    change_id = _write_change(project, body.text, object_name=body.object, t=body.t)

    async def worker(emit):
        if _local_agent(request):
            from cellforge.changes import apply_local_change

            result = await asyncio.to_thread(
                apply_local_change, project, change_id, body.text, body.object, body.t
            )
        else:
            result = await _agent(request).run(
                "apply_cr",
                project,
                emit,
                context=(
                    f"CR: {change_id}\nObject: {body.object or ''}\n"
                    f"Time: {body.t if body.t is not None else ''}"
                ),
                job_id=current_job_id(),
            )
        _commit_or_warn(
            project,
            emit,
            f"apply {change_id}",
            ["cell.yaml", "process.yaml", "changes", ".cellforge"],
        )
        return result

    job = _jobs(request).submit(project_id, "apply_cr", worker)
    return {**job.public(), "change_id": change_id}


def _write_change(
    project: Path,
    text: str,
    source: str = "使用者",
    object_name: str | None = None,
    t: float | None = None,
) -> str:
    number = len(list((project / "changes").glob("CR-*.md"))) + 1
    change_id = f"CR-{number:03d}"
    location = f" / 3D 右鍵 {object_name}" if object_name else ""
    if object_name and t is not None:
        location += f" @ t={t:g}"
    (project / "changes" / f"{change_id}.md").write_text(
        f"# {change_id}\n- 來源：{source}{location}\n- 原始指令：{text}\n- 狀態：open\n",
        encoding="utf-8",
    )
    commit_changes(project, f"create {change_id}", ["changes"])
    return change_id


def _write_task(
    project: Path,
    *,
    owner: Literal["engineering", "astra"],
    text: str,
    created_by: str,
    status: str = "open",
    depends: list[str] | None = None,
) -> dict[str, Any]:
    task_id = f"T-{len(list((project / 'tasks').glob('T-*.yaml'))) + 1:03d}"
    task = {
        "id": task_id,
        "owner": owner,
        "created": datetime.now().astimezone().isoformat(),
        "created_by": created_by,
        "status": status,
        "depends_on": depends or [],
        "instruction": text,
        "inputs": [],
        "outputs": [],
        "log": f"tasks/logs/{task_id}.jsonl",
        "result": None,
    }
    dump_yaml(project / "tasks" / f"{task_id}.yaml", task)
    commit_changes(project, f"create {task_id}", ["tasks"])
    return task


@router.get("/projects/{project_id}/changes")
def get_changes(project_id: str, request: Request) -> list[dict[str, str]]:
    project = _project(request, project_id)
    return [
        {"id": path.stem, "text": path.read_text("utf-8")}
        for path in sorted((project / "changes").glob("CR-*.md"))
    ]


@router.post("/projects/{project_id}/tasks", status_code=201)
def create_task(project_id: str, body: TaskCreate, request: Request) -> dict[str, Any]:
    project = _project(request, project_id)
    return _write_task(
        project,
        owner=body.owner,
        text=body.text,
        created_by="user",
        depends=body.depends,
    )


@router.get("/projects/{project_id}/tasks")
def get_tasks(project_id: str, request: Request) -> list[dict[str, Any]]:
    project = _project(request, project_id)
    return [dict(load_yaml(path)) for path in sorted((project / "tasks").glob("T-*.yaml"))]


@router.post("/projects/{project_id}/tasks/{task_id}/run", status_code=202)
async def run_task(project_id: str, task_id: str, request: Request) -> dict[str, Any]:
    project = _project(request, project_id)
    task_path = project / "tasks" / f"{task_id}.yaml"
    if not task_path.is_file():
        raise HTTPException(404, f"找不到任務：{task_id}")
    task_data = load_yaml(task_path)
    tasks = {item["id"]: item for item in get_tasks(project_id, request)}
    blocked = [
        dependency
        for dependency in task_data.get("depends_on", [])
        if tasks.get(dependency, {}).get("status") != "done"
    ]
    if blocked:
        raise HTTPException(409, f"任務相依尚未完成：{', '.join(blocked)}")

    async def worker(emit):
        task_data["status"] = "running"
        dump_yaml(task_path, task_data)
        try:
            if task_data["owner"] == "astra":
                if _local_astra(request):
                    result = await asyncio.to_thread(
                        refresh_theme_local, project, task_data["instruction"]
                    )
                else:
                    result = await _astra(request).run(project, task_data["instruction"], emit)
            elif _local_agent(request):
                result = {"status": "ok", "mode": "local", "task": task_id}
            else:
                result = await _agent(request).run(
                    "apply_cr",
                    project,
                    emit,
                    context=f"Task: {task_id}\nInstruction: {task_data['instruction']}",
                    job_id=current_job_id(),
                )
            task_data["status"] = "done"
            task_data["result"] = result
            return result
        except Exception:
            task_data["status"] = "failed"
            raise
        finally:
            dump_yaml(task_path, task_data)
            _commit_or_warn(
                project,
                emit,
                f"run {task_id}",
                ["tasks", "changes", ".cellforge", "presentation"],
            )

    job = _jobs(request).submit(
        project_id, f"{task_data['owner']}_task", worker, owner=task_data["owner"]
    )
    return {**job.public(), "task_id": task_id}


@router.get("/projects/{project_id}/process")
def get_process(project_id: str, request: Request) -> dict[str, Any]:
    project = _project(request, project_id)
    return dict(load_yaml(project / "process.yaml"))


@router.get("/projects/{project_id}/analysis/checklist_map")
def get_checklist_map(project_id: str, request: Request) -> dict[str, str]:
    project = _project(request, project_id)
    path = project / "analysis" / "checklist_map.md"
    return {"markdown": path.read_text("utf-8") if path.is_file() else ""}


@router.get("/projects/{project_id}/analysis/intake")
def get_intake(project_id: str, request: Request) -> dict[str, str]:
    project = _project(request, project_id)
    path = project / "analysis" / "intake.md"
    return {"markdown": path.read_text("utf-8") if path.is_file() else ""}


@router.post("/projects/{project_id}/export", status_code=202)
async def export(project_id: str, body: ExportCreate, request: Request) -> dict[str, Any]:
    project = _project(request, project_id)
    try:
        version = VersionContext.open(project, body.version).name
    except VersionNotFoundError as error:
        raise HTTPException(404, str(error)) from error

    async def worker(emit):
        emit("progress", {"progress": 0.1, "message": f"正在建立 {version} 客戶交付包"})
        result = await asyncio.to_thread(export_project, project, body.kinds or None, version)
        if result["missing"]:
            missing = "；".join(f"{item['kind']}：{item['reason']}" for item in result["missing"])
            emit("progress", {"progress": 1.0, "message": f"{version} 交付包不完整：{missing}"})
        else:
            emit("progress", {"progress": 1.0, "message": f"{version} 交付包完成"})
        _commit_or_warn(project, emit, f"export {version} delivery pack", ["export"])
        return result

    job = _jobs(request).submit(project_id, "export", worker, owner="engineering")
    return job.public()


@router.get("/projects/{project_id}/export/{filename}")
def get_export(project_id: str, filename: str, request: Request) -> FileResponse:
    project = _project(request, project_id)
    matches = [
        path
        for path in (project / "export").glob(f"v*/{Path(filename).name}")
        if path.name != "manifest.json"
    ]
    if len(matches) != 1 or not matches[0].is_file():
        raise HTTPException(404, "找不到匯出檔案")
    target = matches[0]
    return FileResponse(target, filename=target.name)


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request) -> dict[str, Any]:
    try:
        return _jobs(request).get(job_id).public()
    except KeyError as error:
        raise HTTPException(404, str(error)) from error


@router.get("/jobs/{job_id}/events")
def job_events(job_id: str, request: Request) -> EventSourceResponse:
    try:
        job = _jobs(request).get(job_id)
    except KeyError as error:
        raise HTTPException(404, str(error)) from error

    async def stream():
        cursor = 0
        while True:
            while cursor < len(job.events):
                event = job.events[cursor]
                cursor += 1
                yield {"event": event["type"], "data": json.dumps(event, ensure_ascii=False)}
            if job.status in {"done", "failed", "cancelled"}:
                break
            if await request.is_disconnected():
                break
            await asyncio.sleep(0.1)

    return EventSourceResponse(stream())


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, request: Request) -> dict[str, Any]:
    try:
        return _jobs(request).cancel(job_id).public()
    except KeyError as error:
        raise HTTPException(404, str(error)) from error


@router.get("/settings")
def get_settings(request: Request) -> dict[str, Any]:
    return {
        "projects_root": str(_root(request)),
        "engineering_agent": request.app.state.settings.get("engineering_agent_command", "claude"),
        "astra_agent": request.app.state.settings.get("astra_agent_command", "codex"),
        **request.app.state.settings,
    }


@router.put("/settings")
def put_settings(body: dict[str, Any], request: Request) -> dict[str, Any]:
    request.app.state.settings.update(body)
    return {"status": "ok", **request.app.state.settings}
