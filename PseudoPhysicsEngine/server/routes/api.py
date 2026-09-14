"""Step-1 REST and SSE routes."""

from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import os
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from cellforge.agents import AstraAgent, EngineeringAgent, refresh_theme_local
from cellforge.diffing import diff_versions
from cellforge.exports import export_project
from cellforge.intake import prepare_intake
from cellforge.intake.local import run_local_intake
from cellforge.project import (
    create_project,
    resolve_inside,
    resolve_project,
    unique_project_dir,
)
from cellforge.questions import update_questions
from cellforge.schema import Questions
from cellforge.versioning import commit_changes
from cellforge.yamlio import dump_yaml, load_yaml


def _local_build(project: Path) -> dict[str, Any]:
    """Isolate OCP from the ASGI worker thread on Windows."""

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "cellforge.cli",
            "build",
            "--project",
            str(project),
            "--level",
            "L1",
            "--json",
        ],
        cwd=Path(__file__).resolve().parents[2],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    output = completed.stdout.strip()
    if completed.returncode != 0:
        detail = output or completed.stderr.strip() or f"exit {completed.returncode}"
        raise ValueError(f"本機建置失敗：{detail}")
    try:
        return json.loads(output.splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as error:
        raise ValueError("本機建置未回傳有效 JSON") from error


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


def _root(request: Request) -> Path:
    return request.app.state.projects_root


def _jobs(request: Request):
    return request.app.state.jobs


def _agent(request: Request) -> EngineeringAgent:
    settings = request.app.state.settings
    return EngineeringAgent(
        str(settings.get("engineering_agent_command", "claude")),
        model=settings.get("engineering_agent_model") or None,
        effort=settings.get("engineering_agent_effort") or None,
        timeout_s=float(settings.get("engineering_agent_timeout_s", 1800)),
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


def _versions(project: Path) -> list[dict[str, Any]]:
    root = project / ".cellforge"
    if not root.is_dir():
        return []
    versions = []
    directories = [path for path in root.glob("v*") if path.name[1:].isdigit()]
    for directory in sorted(directories, key=lambda path: int(path.name[1:])):
        report_path = directory / "step_validation.json"
        report = json.loads(report_path.read_text("utf-8")) if report_path.is_file() else None
        checks_path = directory / "checks.json"
        checks = (
            json.loads(checks_path.read_text("utf-8")).get("summary", {})
            if checks_path.is_file()
            else {"red": 0, "yellow": 0, "green": 0}
        )
        versions.append(
            {
                "id": directory.name,
                "number": int(directory.name[1:]),
                "generated": datetime.fromtimestamp(directory.stat().st_mtime)
                .astimezone()
                .isoformat(),
                "step": report,
                "checks": checks,
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
    data.update({"id": project_id, "versions": _versions(project)})
    return data


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

    async def worker(emit):
        emit("progress", {"progress": 0.05, "message": "開始逐頁擷取 PDF 與 Check List"})
        extraction = await asyncio.to_thread(
            prepare_intake,
            project,
            lambda message: emit("progress", {"progress": 0.2, "message": message}),
        )
        emit("progress", {"progress": 0.35, "message": "工程代理開始判讀全部資料"})
        if _local_agent(request):
            result = await asyncio.to_thread(run_local_intake, project, extraction)
        else:
            result = await _agent(request).run("intake", project, emit)
        validation = _validate_intake_outputs(project)
        emit("progress", {"progress": 1.0, "message": "解析、問題與對照表驗證完成"})
        commit_changes(
            project,
            "engineering intake",
            ["analysis", "workpiece.yaml", "cell.yaml", "process.yaml"],
        )
        return {**result, **validation, "files": extraction["file_count"]}

    job = _jobs(request).submit(project_id, "intake", worker)
    return job.public()


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
            )
        commit_changes(project, f"apply {change_id}", ["analysis", "changes", ".cellforge"])
        return result

    job = _jobs(request).submit(project_id, "assumption_override", worker)
    return {**job.public(), "change_id": change_id}


@router.post("/projects/{project_id}/build", status_code=202)
async def start_build(project_id: str, request: Request) -> dict[str, Any]:
    project = _project(request, project_id)

    questions = Questions.model_validate(load_yaml(project / "analysis" / "questions.yaml"))
    open_ids = [question.id for question in questions.questions if question.status == "open"]
    if open_ids:
        raise HTTPException(409, f"尚有未回答或未跳過的問題：{', '.join(open_ids)}")

    async def worker(emit):
        emit("progress", {"progress": 0.05, "message": "工程代理開始建立初版"})
        if _local_agent(request):
            result = await asyncio.to_thread(_local_build, project)
            result.update({"status": "ok", "mode": "local"})
        else:
            result = await _agent(request).run("first_build", project, emit)
        versions = _versions(project)
        if not versions:
            raise ValueError("first_build 完成但未產生 .cellforge/vN 版本")
        emit("progress", {"progress": 0.82, "message": "Astra 正在刷新主題與 1080p 影片"})
        instruction = "依 render_brief 自動美化並輸出 1080p 工程審查影片"
        if _local_astra(request):
            astra = await asyncio.to_thread(refresh_theme_local, project, instruction)
        else:
            astra = await _astra(request).run(project, instruction, emit)
        result["astra"] = astra
        commit_changes(project, "Astra presentation refresh", ["presentation"])
        emit("progress", {"progress": 1.0, "message": "建置、檢查與 Astra 交付完成"})
        return result

    job = _jobs(request).submit(project_id, "first_build", worker)
    return job.public()


@router.get("/projects/{project_id}/versions")
def get_versions(project_id: str, request: Request) -> list[dict[str, Any]]:
    return _versions(_project(request, project_id))


@router.get("/projects/{project_id}/versions/{version}/{asset}")
def get_version_asset(project_id: str, version: str, asset: str, request: Request) -> FileResponse:
    if asset not in {
        "scene.glb",
        "timeline.json",
        "checks.json",
        "render_brief.md",
        "step_validation.json",
    }:
        raise HTTPException(404, "不支援的版本檔案")
    project = _project(request, project_id)
    target = project / ".cellforge" / version / asset
    if not target.is_file():
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
            )
        commit_changes(
            project,
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
    task_id = f"T-{len(list((project / 'tasks').glob('T-*.yaml'))) + 1:03d}"
    task = {
        "id": task_id,
        "owner": body.owner,
        "created": datetime.now().astimezone().isoformat(),
        "created_by": "user",
        "status": "open",
        "depends_on": body.depends,
        "instruction": body.text,
        "inputs": [],
        "outputs": [],
        "log": f"tasks/logs/{task_id}.jsonl",
        "result": None,
    }
    dump_yaml(project / "tasks" / f"{task_id}.yaml", task)
    commit_changes(project, f"create {task_id}", ["tasks"])
    return task


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
                )
            task_data["status"] = "done"
            task_data["result"] = result
            return result
        except Exception:
            task_data["status"] = "failed"
            raise
        finally:
            dump_yaml(task_path, task_data)
            commit_changes(
                project,
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
def export(project_id: str, body: ExportCreate, request: Request) -> dict[str, Any]:
    project = _project(request, project_id)

    async def worker(emit):
        emit("progress", {"progress": 0.1, "message": "正在建立客戶交付包"})
        result = await asyncio.to_thread(export_project, project, body.kinds or None)
        emit("progress", {"progress": 1.0, "message": "交付包完成"})
        commit_changes(project, "export delivery pack", ["export"])
        return result

    job = _jobs(request).submit(project_id, "export", worker, owner="engineering")
    return job.public()


@router.get("/projects/{project_id}/export/{filename}")
def get_export(project_id: str, filename: str, request: Request) -> FileResponse:
    project = _project(request, project_id)
    matches = list((project / "export").glob(f"v*/{Path(filename).name}"))
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
