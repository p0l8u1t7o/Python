"""intake → first_build 的前置狀態與 job 成功判定。

每次 intake 結束（成功、失敗或取消）都寫入 ``analysis/intake_state.json``，記錄模式與
當時輸入證據的指紋。first_build 只接受「最近一次 intake 成功、輸入未再變更、且模式相符」
的案子；成功與否只看本次 job 自己發布的版本，不因案子已有其他版本或輸出檔就算成功。
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from cellforge.versioning import MANIFEST_NAME, version_dirs
from cellforge.yamlio import load_yaml

INTAKE_STATE = "analysis/intake_state.json"
IntakeStatus = Literal["running", "succeeded", "failed", "cancelled"]
AgentMode = Literal["claude", "local"]


class WorkflowPreconditionError(RuntimeError):
    """前置條件不符；訊息說明原因與下一步，直接顯示給使用者。"""


def inputs_fingerprint(project: Path) -> str:
    """SHA-256 over the registered input evidence (path and content hash), order-independent."""

    manifest = load_yaml(project / "inputs" / "manifest.yaml") or {}
    entries = sorted(
        (str(item.get("path", "")), str(item.get("sha256", "")).lower())
        for item in manifest.get("files", []) or []
    )
    payload = json.dumps(entries, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def record_intake(
    project: Path,
    *,
    job_id: str | None,
    mode: AgentMode,
    status: IntakeStatus,
    started: str,
    fingerprint: str,
    error: str | None = None,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = {
        "job_id": job_id,
        "mode": mode,
        "status": status,
        "started": started,
        "finished": None if status == "running" else datetime.now().astimezone().isoformat(),
        "inputs_fingerprint": fingerprint,
        "error": error,
        "result": result,
    }
    path = project / INTAKE_STATE
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)
    return state


def intake_state(project: Path) -> dict[str, Any] | None:
    path = project / INTAKE_STATE
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text("utf-8"))
    except json.JSONDecodeError:
        return None


def require_first_build_ready(project: Path, mode: AgentMode) -> dict[str, Any]:
    state = intake_state(project)
    manual = "若只要以目前 YAML 建置，請改用「手寫資料建置（非代理驗收）」。"
    if state is None:
        raise WorkflowPreconditionError(f"尚未完成 intake，不能開始 first_build。{manual}")
    if state.get("status") != "succeeded":
        detail = f"：{state['error']}" if state.get("error") else ""
        raise WorkflowPreconditionError(
            f"最近一次 intake 狀態為 {state.get('status')}{detail}；請重新執行 intake。{manual}"
        )
    if state.get("inputs_fingerprint") != inputs_fingerprint(project):
        raise WorkflowPreconditionError(
            "intake 完成後輸入資料已變更（新增、移除或替換檔案），intake 結果已過期；"
            "請重新執行 intake。"
        )
    if mode == "claude" and state.get("mode") != "claude":
        raise WorkflowPreconditionError(
            "目前的 intake 由離線 runner 產生，不是正式工程代理的結果；正式 first_build 必須先以"
            f"正式代理重新執行 intake。{manual}"
        )
    return state


def versions_for_job(project: Path, job_id: str) -> list[Path]:
    """Published versions whose manifest says this job produced them, in version order."""

    found = []
    for directory in version_dirs(project):
        manifest_path = directory / MANIFEST_NAME
        if not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text("utf-8"))
        except json.JSONDecodeError:
            continue
        if manifest.get("build", {}).get("job_id") == job_id:
            found.append(directory)
    return found


def written_since(project: Path, relatives: list[str], since: float) -> list[str]:
    """Relative paths that are missing or were not rewritten after ``since`` (epoch seconds)."""

    stale = []
    for relative in relatives:
        path = project / relative
        # 檔案系統時間解析度有限，保留兩秒容差。
        if not path.is_file() or path.stat().st_mtime < since - 2.0:
            stale.append(relative)
    return stale
