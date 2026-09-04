from __future__ import annotations

from typing import Any

from ninja import Schema


class FlowIn(Schema):
    name: str
    description: str = ""
    graph: dict[str, Any] | None = None
    is_enabled: bool = True
    continuous_interval_ms: int = 0


class FlowPatch(Schema):
    name: str | None = None
    description: str | None = None
    graph: dict[str, Any] | None = None
    is_enabled: bool | None = None
    continuous_interval_ms: int | None = None
    commissioned: bool | None = None
    archive_policy: dict | None = None


class RecipeIn(Schema):
    name: str
    description: str = ""
    param_overrides: dict[str, Any] = {}
    is_default: bool = False


class RecipePatch(Schema):
    name: str | None = None
    description: str | None = None
    param_overrides: dict[str, Any] | None = None
    is_default: bool | None = None


class FlowOut(Schema):
    id: int
    name: str
    description: str
    graph: dict[str, Any]
    is_enabled: bool
    version: int
    continuous_interval_ms: int
    node_count: int
    created_at: str
    updated_at: str
    stats: dict[str, Any]
    continuous: bool


class RunRequest(Schema):
    """JSON 觸發（不附影像）。附影像請用 multipart：image 檔 + 可選 context JSON 字串。"""

    context: dict[str, Any] | None = None
    wait: bool = True
    timeout_s: float | None = None
    include_images: bool = False


class PreviewRequest(Schema):
    """編輯器試跑：用尚未存檔的圖，並可指定要抓哪個來源／用最近一張影像。"""

    graph: dict[str, Any]
    context: dict[str, Any] | None = None
    #: 用先前某次 run 的來源影像重跑（ref），方便調參數時畫面不變。
    reuse_image_ref: str | None = None
    #: 只跑到這個節點（含其祖先）：工具專屬頁即時調參用。
    until_node: str | None = None
    #: 回傳該節點的參考統計（輸入／輸出影像直方圖、數值分布）。
    analysis: bool = False
    #: 以某個配方的覆寫試跑（id 或名稱）。
    recipe: str | None = None


class SourceIn(Schema):
    name: str
    kind: str
    config: dict[str, Any] = {}
    is_enabled: bool = True
    group: str = ""


class SourcePatch(Schema):
    name: str | None = None
    kind: str | None = None
    config: dict[str, Any] | None = None
    is_enabled: bool | None = None
    group: str | None = None


class SourceOut(Schema):
    id: int
    name: str
    kind: str
    config: dict[str, Any]
    is_enabled: bool
    status: dict[str, Any]
    created_at: str
    updated_at: str


class AssetOut(Schema):
    id: str
    name: str
    kind: str
    size: int
    meta: dict[str, Any]
    created_at: str


class Page(Schema):
    items: list[Any]
    total: int
    limit: int
    offset: int
