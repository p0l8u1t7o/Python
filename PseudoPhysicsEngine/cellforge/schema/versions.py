"""版本快照 manifest：記錄一個 vN 的來源、模組、執行環境與產物雜湊。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from .base import ForgeModel

Sha256 = str


class ManifestFile(ForgeModel):
    path: str
    sha256: Sha256
    size: int
    # object：內容定址存放在 .cellforge/objects/，版本目錄內為硬連結或複本。
    stored: Literal["copy", "object"] = "copy"


class SourcePolicy(ForgeModel):
    include: list[str]
    exclude: list[str] = Field(default_factory=list)
    object_threshold_bytes: int


class ManifestModule(ForgeModel):
    id: str
    source: str
    module_file: str
    module_sha256: Sha256
    params: dict[str, Any] = Field(default_factory=dict)
    expanded_params: dict[str, Any] = Field(default_factory=dict)
    # library／project-part／vendor-urdf:<id>／vendor-static:<id>／approximated-stub:<id>
    model_source: str | None = None
    approximated: bool = False


class ManifestPart(ForgeModel):
    """產品零件實例；SKU 方塊零件沒有 module_file。"""

    id: str
    sku: str | None = None
    module_file: str | None = None
    module_sha256: Sha256 | None = None
    mass_kg: float | None = None


class ManifestEngine(ForgeModel):
    package_version: str | None = None
    git_commit: str | None = None
    git_dirty: bool | None = None
    python: str
    platform: str
    packages: dict[str, str | None] = Field(default_factory=dict)


class ManifestBuild(ForgeModel):
    level: Literal["L0", "L1"]
    status: Literal["succeeded"]
    started: datetime
    finished: datetime
    warnings: list[str] = Field(default_factory=list)
    # 觸發入口（cli、mcp、direct、manual、agent:first_build…）與所屬 job；
    # job 成功判定只承認 job_id 等於自己的版本。
    origin: str | None = None
    job_id: str | None = None


class ManifestEngineering(ForgeModel):
    """工程檢查結論，與建置是否成功分開；L0 版本一律為 not_evaluated。"""

    status: Literal["pass", "warning", "fail", "not_evaluated"]
    summary: dict[str, int] | None = None


class VersionManifest(ForgeModel):
    manifest_version: Literal[1] = 1
    version: str
    number: int
    created: datetime
    project_name: str
    build: ManifestBuild
    engineering: ManifestEngineering
    engine: ManifestEngine
    schema_fingerprint: Sha256
    source_policy: SourcePolicy
    sources: list[ManifestFile] = Field(default_factory=list)
    library: list[ManifestFile] = Field(default_factory=list)
    modules: list[ManifestModule] = Field(default_factory=list)
    # 舊版本沒有此欄位，視為單一工件 workpiece。
    parts: list[ManifestPart] = Field(default_factory=list)
    artifacts: list[ManifestFile] = Field(default_factory=list)
