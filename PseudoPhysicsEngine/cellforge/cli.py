"""The `cell` command line interface."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import typer

from cellforge.project import create_project, project_template
from cellforge.questions import update_questions
from cellforge.schema.export import export_json_schemas
from cellforge.validation import ProjectValidationError, validate_project
from cellforge.yamlio import load_yaml

app = typer.Typer(help="CellForge 自動化機台可行性評估工具", no_args_is_help=True)
question_app = typer.Typer(help="回答或跳過工程代理問題", no_args_is_help=True)
agent_app = typer.Typer(help="執行工程代理任務", no_args_is_help=True)
app.add_typer(question_app, name="question")
vendor_app = typer.Typer(help="Manage traceable vendor assets", no_args_is_help=True)
app.add_typer(agent_app, name="agent")
app.add_typer(vendor_app, name="vendor")


def _emit(payload: dict, json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False))
    else:
        typer.echo(payload.get("message", json.dumps(payload, ensure_ascii=False, indent=2)))


@app.command("init")
def init_project(
    directory: Path,
    from_wizard: Path | None = typer.Option(None, "--from-wizard"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """由範本建立案子目錄。"""
    if directory.exists() and any(directory.iterdir()):
        typer.echo(f"目標目錄不是空的：{directory}", err=True)
        raise typer.Exit(2)
    project_data = load_yaml(from_wizard or project_template() / "project.yaml")
    create_project(directory, project_data)
    _emit(
        {"status": "ok", "project": str(directory), "message": f"已建立案子：{directory}"},
        json_output,
    )


@app.command("validate")
def validate(
    project: Path = typer.Option(Path.cwd(), "--project"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """驗證 Schema、id、引用、單位與模組參數。"""
    try:
        validate_project(project.resolve())
    except ProjectValidationError as error:
        _emit({"status": "failed", "message": str(error)}, json_output)
        raise typer.Exit(2) from error
    _emit({"status": "ok", "message": "驗證通過"}, json_output)


@app.command("build")
def build(
    project: Path = typer.Option(Path.cwd(), "--project"),
    level: str = typer.Option("L0", "--level"),
    no_checks: bool = typer.Option(False, "--no-checks"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """建立 STEP、GLB 與 timeline。"""
    from cellforge.build.pipeline import BuildError, build_project

    del no_checks
    try:
        report = build_project(project.resolve(), level.upper())
    except (BuildError, ProjectValidationError, ValueError) as error:
        _emit({"status": "failed", "message": str(error)}, json_output)
        raise typer.Exit(3) from error
    report.update({"status": "ok", "message": "L0 建置完成；STEP 已用 OCP 重讀驗證"})
    _emit(report, json_output)


@app.command("snapshot")
def snapshot(
    time_s: float = typer.Option(..., "--t"),
    camera: str = typer.Option("iso", "--cam"),
    output: Path | None = typer.Option(None, "--out"),
    project: Path = typer.Option(Path.cwd(), "--project"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """以 Playwright 擷取指定時刻畫面。"""
    from cellforge.snapshot import SnapshotError, snapshot_project

    try:
        path = snapshot_project(project.resolve(), time_s, camera, output)
    except SnapshotError as error:
        _emit({"status": "failed", "message": str(error)}, json_output)
        raise typer.Exit(3) from error
    _emit({"status": "ok", "path": str(path), "message": f"已產生截圖：{path}"}, json_output)


@app.command("schema")
def schema(
    output: Path = typer.Option(Path("docs/schema"), "--out"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """輸出前端與代理使用的 JSON Schema。"""
    paths = export_json_schemas(output)
    _emit(
        {
            "status": "ok",
            "files": [str(path) for path in paths],
            "message": f"已輸出 {len(paths)} 份 JSON Schema",
        },
        json_output,
    )


@question_app.command("answer")
def question_answer(
    question_id: str,
    text: str,
    project: Path = typer.Option(Path.cwd(), "--project"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """回答一題，保留使用者原始文字。"""
    try:
        changed = update_questions(project.resolve(), question_id, answer=text)
    except (KeyError, ValueError) as error:
        _emit({"status": "failed", "message": str(error)}, json_output)
        raise typer.Exit(2) from error
    _emit({"status": "ok", "questions": changed, "message": f"已回答 {question_id}"}, json_output)


@question_app.command("skip")
def question_skip(
    question_id: str,
    project: Path = typer.Option(Path.cwd(), "--project"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """跳過一題並把預設值寫入 assumptions.yaml。"""
    try:
        changed = update_questions(project.resolve(), question_id, skip=True)
    except (KeyError, ValueError) as error:
        _emit({"status": "failed", "message": str(error)}, json_output)
        raise typer.Exit(2) from error
    _emit({"status": "ok", "questions": changed, "message": f"已跳過 {question_id}"}, json_output)


@question_app.command("skip-all")
def question_skip_all(
    project: Path = typer.Option(Path.cwd(), "--project"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """跳過所有未處理問題並建立一題一筆的假設。"""
    try:
        changed = update_questions(project.resolve(), None, skip_all=True)
    except (KeyError, ValueError) as error:
        _emit({"status": "failed", "message": str(error)}, json_output)
        raise typer.Exit(2) from error
    _emit(
        {"status": "ok", "questions": changed, "message": f"已跳過 {len(changed)} 題"},
        json_output,
    )


@agent_app.command("run")
def agent_run(
    owner: str = typer.Option(..., "--owner"),
    task: str = typer.Option(..., "--task"),
    project: Path = typer.Option(Path.cwd(), "--project"),
    command: str = typer.Option("claude", "--command"),
    model: str | None = typer.Option(None, "--model"),
    effort: str | None = typer.Option("low", "--effort"),
    timeout_s: float = typer.Option(1800, "--timeout"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """以非互動 Claude Code 執行工程任務。"""
    if owner != "engineering":
        _emit({"status": "failed", "message": "步驟 2 僅支援 engineering owner"}, json_output)
        raise typer.Exit(2)
    task_path = project.resolve() / "tasks" / f"{task}.yaml"
    if not task_path.is_file():
        _emit({"status": "failed", "message": f"找不到任務：{task}"}, json_output)
        raise typer.Exit(2)

    from cellforge.agents import EngineeringAgent, EngineeringAgentError

    task_data = load_yaml(task_path)

    def emit(kind: str, data: dict) -> None:
        if json_output:
            typer.echo(json.dumps({"type": kind, **data}, ensure_ascii=False))
        elif data.get("message"):
            typer.echo(data["message"])

    runner = EngineeringAgent(command, model=model, effort=effort, timeout_s=timeout_s)
    try:
        result = asyncio.run(
            runner.run(
                "apply_cr",
                project.resolve(),
                emit,
                context=f"Task: {task}\nInstruction: {task_data['instruction']}",
            )
        )
    except EngineeringAgentError as error:
        _emit({"status": "failed", "message": str(error)}, json_output)
        raise typer.Exit(3) from error
    _emit({**result, "message": result.get("summary", "工程代理完成")}, json_output)


@vendor_app.command("stub")
def vendor_stub(
    vendor_id: str,
    project: Path = typer.Option(Path.cwd(), "--project"),
    reach_mm: float = typer.Option(905, "--reach-mm"),
    payload_kg: float = typer.Option(7, "--payload-kg"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Create a traceable six-axis robot URDF placeholder."""
    from cellforge.vendor import stub_robot

    entry = stub_robot(project.resolve(), vendor_id, reach_mm=reach_mm, payload_kg=payload_kg)
    _emit(
        {"status": "ok", "vendor": entry, "message": f"Created vendor stub {vendor_id}"},
        json_output,
    )


@vendor_app.command("add")
def vendor_add(
    vendor_id: str,
    source: str,
    kind: str = typer.Option("other", "--kind"),
    project: Path = typer.Option(Path.cwd(), "--project"),
    units: str = typer.Option("mm", "--units"),
    up_axis: str = typer.Option("z", "--up-axis"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Download or copy a vendor asset and record its provenance."""
    from cellforge.vendor import add_vendor_file

    entry = add_vendor_file(
        project.resolve(), vendor_id, kind, source, units=units, up_axis=up_axis
    )
    _emit(
        {"status": "ok", "vendor": entry, "message": f"Added vendor asset {vendor_id}"}, json_output
    )


@app.command("checks")
def checks_command(
    project: Path = typer.Option(Path.cwd(), "--project"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Run an L1 build and all engineering checks."""
    from cellforge.build.pipeline import build_project

    report = build_project(project.resolve(), "L1")
    _emit(
        {"status": "ok", **report, "message": f"L1 checks complete: {report['checks']}"},
        json_output,
    )


@app.command("diff")
def diff_command(
    before: str,
    after: str,
    project: Path = typer.Option(Path.cwd(), "--project"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Compare source, checks, and timeline of two immutable versions."""
    from cellforge.diffing import diff_versions

    report = diff_versions(project.resolve(), before, after)
    _emit({"status": "ok", **report, "message": f"{report['count']} semantic changes"}, json_output)


@app.command("export")
def export_command(
    project: Path = typer.Option(Path.cwd(), "--project"),
    kinds: str = typer.Option("all", "--kinds"),
    version: str | None = typer.Option(None, "--version"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Create the complete customer delivery pack."""
    from cellforge.exports import export_project

    selected = None if kinds.lower() == "all" else [item.strip() for item in kinds.split(",")]
    report = export_project(project.resolve(), selected, version)
    _emit({**report, "message": f"Exported {len(report['files'])} files"}, json_output)


@app.command("serve")
def serve(
    port: int = typer.Option(8765, "--port"),
    projects_root: Path | None = typer.Option(None, "--projects-root"),
) -> None:
    """啟動只綁定本機的 FastAPI 與前端。"""
    import uvicorn

    from server.main import create_app

    uvicorn.run(
        create_app(projects_root),
        host="127.0.0.1",
        port=port,
        log_level="info",
    )


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    try:
        app()
    except SystemExit as error:
        exit_code = int(error.code or 0)
        sys.stdout.flush()
        sys.stderr.flush()
        if os.name == "nt":
            # OCP may fault while Windows unloads its native DLLs after all
            # command output and files are already complete. Exit directly so
            # callers receive the real Typer status instead of 0xC0000005.
            os._exit(exit_code)
        raise


if __name__ == "__main__":
    main()
