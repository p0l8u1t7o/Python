"""CellForge local web application entry point."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from cellforge.trash import default_trash_root
from server.jobs import JobRunner
from server.routes.api import router


def create_app(
    projects_root: Path | None = None,
    *,
    settings: dict[str, object] | None = None,
) -> FastAPI:
    source_root = Path(__file__).resolve().parents[1]
    overrides = dict(settings or {})
    catalog_root = Path(overrides.pop("catalog_root", source_root)).resolve()
    module_cache_root = Path(
        overrides.pop(
            "module_cache_root",
            source_root / ".cellforge-runtime" / "module-cache",
        )
    ).resolve()
    root = projects_root or Path(
        os.environ.get("CELLFORGE_PROJECTS_ROOT", Path.home() / "CellForge" / "projects")
    )
    root.mkdir(parents=True, exist_ok=True)
    trash_root = overrides.pop("trash_root", None) or os.environ.get("CELLFORGE_TRASH_ROOT")
    app = FastAPI(title="CellForge", version="0.1.0")
    app.state.projects_root = root.resolve()
    # 刪除的案子移到這裡，可由網頁還原；預設為專案根目錄旁的 trash/。
    app.state.trash_root = (
        Path(trash_root).resolve() if trash_root else default_trash_root(app.state.projects_root)
    )
    app.state.catalog_root = catalog_root
    app.state.module_cache_root = module_cache_root
    app.state.jobs = JobRunner(app.state.projects_root)
    app.state.settings = {
        "engineering_agent_mode": os.environ.get("CELLFORGE_ENGINEERING_AGENT_MODE", "claude"),
        "engineering_agent_command": os.environ.get("CELLFORGE_CLAUDE_COMMAND", "claude"),
        "engineering_agent_model": os.environ.get("CELLFORGE_CLAUDE_MODEL", "sonnet"),
        "engineering_agent_effort": os.environ.get("CELLFORGE_CLAUDE_EFFORT", "low"),
        "engineering_agent_timeout_s": 1800,
        "astra_agent_mode": os.environ.get("CELLFORGE_ASTRA_AGENT_MODE", "local"),
        "astra_agent_command": os.environ.get("CELLFORGE_ASTRA_COMMAND", "codex"),
        "astra_agent_model": os.environ.get("CELLFORGE_ASTRA_MODEL", "gpt-6-astra"),
        "astra_agent_timeout_s": 900,
        **overrides,
    }
    app.include_router(router)

    @app.exception_handler(Exception)
    async def unhandled(_request, error: Exception):
        return JSONResponse(status_code=500, content={"detail": f"伺服器錯誤：{error}"})

    web_dist = source_root / "web" / "dist"
    if not web_dist.is_dir():
        web_dist = source_root / "cellforge" / "_viewer"
    if web_dist.is_dir():
        app.mount("/", StaticFiles(directory=web_dist, html=True), name="web")
    return app


app = create_app()
