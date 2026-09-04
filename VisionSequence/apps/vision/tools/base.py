"""工具（節點）框架與 registry。

設計沿用 docs/workflow-design.html 的原則：
- 引擎不認識任何工具；工具以 key 註冊，圖只寫 key。
- 前端的調色盤與參數表單完全從 catalogue() 產生，加工具不用改前端。
- Param.kind 是封閉集合（前端 ParamField 的 switch 分支），不是 JSON Schema。

與控制流程引擎不同的地方：機器視覺是**資料流**。每個工具宣告輸入埠與輸出埠，
邊連接「來源節點.輸出埠 → 目標節點.輸入埠」，影像以 numpy 陣列在記憶體傳遞，
一次 run 在同一執行緒內以拓樸順序跑完，沒有任何資料落地。

條件分支：工具可宣告 kind="flow" 的輸出把手（例如 if 的 true/false）。
帶有 flow 邊連入的節點，只有在至少一條連入的分支被選中時才執行；
被跳過的節點其下游（資料邊）也一併跳過（除非該輸入是選填）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

import numpy as np

from apps.core.errors import ValidationError

# 埠的資料型別。any 可接任何型別；flow 是控制分支。
PORT_TYPES = (
    "image",     # np.ndarray（灰階 HxW 或彩色 HxWx3 BGR，uint8）
    "region",    # ROI dict：{"shape": "rect"|"circle"|"polygon"|"line"|"annulus"|"rotated_rect", ...}
    "number",    # int/float
    "bool",
    "string",
    "points",    # list[[x, y], ...]
    "contours",  # list[np.ndarray(N,1,2)]
    "matches",   # list[dict]（範本比對／偵測結果）
    "list",      # 任意 list
    "any",
    "flow",
)

# Param.kind 封閉集合（前端 ParamField 同步）。
PARAM_KINDS = (
    "text", "multiline", "number", "boolean", "select",
    "range",        # 單一數值，但以滑桿呈現（必須給 minimum/maximum/step）
    "roi",          # 影像上畫的區域；值為 region dict
    "source",       # 影像來源 id
    "asset",        # 上傳的資產（範本影像、ONNX 模型…）；值為 asset id
    "color",        # "#rrggbb"
    "json",         # 任意 JSON
    "expression",   # 公式字串（formula 工具）
    "code",         # 程式碼（accept＝語言，目前 python）；前端等寬編輯器，只有管理員能儲存新內容（apps/vision/scripts.py）
    "output_key",   # 輸出欄位名稱
)


class UnknownToolType(ValidationError):
    def __init__(self, key: str, available: list[str] | None = None) -> None:
        super().__init__(
            f"未知的工具型別 '{key}'",
            code="unknown_tool_type",
            details={"tool_type": key, "available": sorted(available or [])},
        )


@dataclass(frozen=True, slots=True)
class Param:
    key: str
    label: str
    kind: str = "text"
    required: bool = False
    default: Any = None
    help_text: str = ""
    options: list[dict[str, Any]] = field(default_factory=list)
    unit: str = ""
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    #: 依另一個參數的值顯示／隱藏：{"param": "mode", "in": ["a", "b"]}
    visible_when: dict[str, Any] | None = None
    #: roi 參數允許的形狀，例如 ["rect", "rotated_rect", "circle"]
    shapes: list[str] = field(default_factory=list)
    #: asset 參數接受的類型：image | model | file
    accept: str = ""
    #: 前端分組（進階參數摺疊）。
    group: str = ""
    #: 需要現場教導的參數（參數卡頁只列這些）。
    teach: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "kind": self.kind,
            "required": self.required,
            "default": self.default,
            "help_text": self.help_text,
            "options": list(self.options),
            "unit": self.unit,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "step": self.step,
            "visible_when": self.visible_when,
            "shapes": list(self.shapes),
            "accept": self.accept,
            "group": self.group,
            "teach": self.teach,
        }


@dataclass(frozen=True, slots=True)
class Port:
    key: str
    label: str
    type: str = "image"
    #: 輸入埠：未連線是否算錯。選填輸入未連線時工具收到 None。
    required: bool = True
    #: 輸入埠：允許多條邊連入（收到 list）。
    multiple: bool = False
    #: 輸出埠（type="flow"）的顏色語意：neutral | ok | warn | critical
    tone: str = "neutral"

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "type": self.type,
            "required": self.required,
            "multiple": self.multiple,
            "tone": self.tone,
        }


def flow_out(key: str, label: str, tone: str = "neutral") -> Port:
    return Port(key, label, type="flow", required=False, tone=tone)


# ---------------------------------------------------------------------------
# 執行
# ---------------------------------------------------------------------------
@dataclass
class ToolContext:
    """工具被允許看到的一切。"""

    run_id: str
    flow_id: int
    node: dict[str, Any]
    inputs: dict[str, Any]
    #: run 層級共享變數（工具可透過 Result.context 寫入）。
    context: dict[str, Any]
    moment: float
    log: Callable[..., None]
    #: 取得資產檔案路徑（範本影像、模型）。
    asset_path: Callable[[str], str | None]
    #: 取得影像來源並抓一張。
    grab: Callable[[str], np.ndarray | None]
    #: 是否為編輯器內的試跑（可保留更多除錯輸出）。
    preview: bool = False
    #: 本工具宣告可吃的影像位深（Tool.accepts；image() 會把宣告外的位深自動正規化成 u8）。
    depth: tuple[str, ...] = ("u8",)
    _params_cache: dict[str, Any] | None = field(default=None, init=False, repr=False, compare=False)

    @property
    def params(self) -> dict[str, Any]:
        """節點參數的副本（一個 ctx 只複製一次；工具每次 param() 都會用到）。"""
        cached = self._params_cache
        if cached is None:
            cached = self._params_cache = dict(self.node.get("params") or {})
        return cached

    def param(self, key: str, default: Any = None) -> Any:
        value = self.params.get(key)
        return default if value in (None, "") else value

    def number(self, key: str, default: float = 0.0) -> float:
        try:
            return float(self.param(key, default))
        except (TypeError, ValueError):
            return float(default)

    def integer(self, key: str, default: int = 0) -> int:
        return int(round(self.number(key, default)))

    def flag(self, key: str, default: bool = False) -> bool:
        value = self.param(key, default)
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)

    def image(self, key: str = "image") -> np.ndarray | None:
        value = self.inputs.get(key)
        if not isinstance(value, np.ndarray):
            return None
        # 位深中央接縫：工具沒宣告支援的位深（16-bit／浮點）自動正規化成 u8（新陣列，不動輸入）
        from apps.vision.tools import imgfmt

        return imgfmt.coerce(value, self.depth)

    def require_image(self, key: str = "image") -> np.ndarray:
        image = self.image(key)
        if image is None:
            raise ToolError(f"輸入埠 '{key}' 沒有影像")
        return image

    def roi(self, key: str = "roi") -> dict[str, Any] | None:
        """ROI 優先取輸入埠（動態 region），其次取參數（畫布上畫的）。"""
        value = self.inputs.get(key)
        if isinstance(value, dict) and value.get("shape"):
            return value
        value = self.params.get(key)
        if isinstance(value, dict) and value.get("shape"):
            return value
        return None


class ToolError(Exception):
    """工具在「可預期的失敗」時拋出；引擎記為該節點 error，不會讓平台當機。"""


@dataclass
class Result:
    """工具做了什麼。

    outputs：以輸出埠 key 為鍵。影像請放 np.ndarray；引擎會登記到影像快取供前端檢視。
    overlays：畫在**輸入影像座標**上的標記（前端 ImageViewer 繪製）：
        {"kind": "rect", "x", "y", "w", "h", "angle"?, "color"?, "label"?, "width"?}
        {"kind": "circle", "cx", "cy", "r", ...}
        {"kind": "polygon"|"polyline", "points": [[x, y], ...], ...}
        {"kind": "line", "x1", "y1", "x2", "y2", ...}
        {"kind": "point", "x", "y", ...}   /  {"kind": "points", "points": [...]}
        {"kind": "text", "x", "y", "text", ...}
        {"kind": "contours", "contours": [[[x, y], ...], ...], ...}
    branch：kind=flow 的輸出把手名稱；None = 全部資料輸出正常流出。
    status：ok | ng | error。ng 代表「檢測判定不良」，不是程式錯誤。
    """

    outputs: dict[str, Any] = field(default_factory=dict)
    overlays: list[dict[str, Any]] = field(default_factory=list)
    branch: str | None = None
    status: str = "ok"
    message: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] | None = None
    #: 指定 overlays 對應的輸入影像埠（預設第一個 image 輸入）。
    overlay_on: str | None = None


class ToolType(Protocol):
    key: str
    label: str
    description: str
    #: 調色盤分組：source | preprocess | locate | measure | detect | logic | output | dl | decoration
    category: str
    icon: str
    params: list[Param]
    inputs: list[Port]
    outputs: list[Port]

    def execute(self, ctx: ToolContext) -> Result: ...


class Tool:
    """方便繼承的基底：提供預設欄位，子類只需覆寫需要的部分。"""

    key = ""
    label = ""
    description = ""
    category = "preprocess"
    icon = "Box"
    params: list[Param] = []
    inputs: list[Port] = [Port("image", "影像", "image")]
    outputs: list[Port] = [Port("image", "影像", "image")]
    #: 是否可能耗時很久（前端顯示提示）。
    heavy = False
    #: 參數語意變更時 +1：配方匯入會比對版本，提醒使用者確認。
    version = 1
    #: False = 資料夾外掛掃描（apps.core.plugins）時不掛載這個類別。
    enabled = True
    #: 哪些參數填的是「通訊連線名稱」。Runner 的 prefetch 會照這個把連線在呼叫者執行緒
    #: 先開好（執行緒池內的熱路徑不碰資料庫）；沒宣告的話工具在執行時只會拿到 None。
    connection_params: tuple[str, ...] = ()

    #: 可吃的影像位深（imgfmt.DEPTHS 子集合）。預設只吃 u8：其他位深進來會被自動
    #: 正規化（工具永遠不炸）；能原生處理 16-bit／浮點的工具自行宣告放寬。
    accepts: tuple[str, ...] = ("u8",)

    def execute(self, ctx: ToolContext) -> Result:  # pragma: no cover - 抽象
        raise NotImplementedError


_REGISTRY: dict[str, ToolType] = {}


def register(tool: ToolType) -> ToolType:
    if not tool.key:
        raise RuntimeError(f"{tool!r} 沒有 key")
    if tool.key in _REGISTRY:
        raise RuntimeError(f"工具 '{tool.key}' 已註冊")
    for p in tool.params:
        if p.kind not in PARAM_KINDS:
            raise RuntimeError(f"工具 '{tool.key}' 參數 '{p.key}' 的 kind '{p.kind}' 不在封閉集合內")
    for port in list(tool.inputs) + list(tool.outputs):
        if port.type not in PORT_TYPES:
            raise RuntimeError(f"工具 '{tool.key}' 埠 '{port.key}' 的 type '{port.type}' 不合法")
    _REGISTRY[tool.key] = tool
    return tool


def unregister(key: str) -> None:
    _REGISTRY.pop(key, None)


def get(key: str) -> ToolType:
    try:
        return _REGISTRY[key]
    except KeyError:
        raise UnknownToolType(key, list(_REGISTRY)) from None


def has(key: str) -> bool:
    return key in _REGISTRY


def all_types() -> list[ToolType]:
    return sorted(_REGISTRY.values(), key=lambda t: (CATEGORY_ORDER.get(t.category, 99), t.label))


CATEGORY_ORDER = {
    "source": 0,
    "preprocess": 1,
    "locate": 2,
    "measure": 3,
    "detect": 4,
    "dl": 5,
    "logic": 6,
    "output": 7,
    "decoration": 8,
}

CATEGORY_LABELS = {
    "source": "影像來源",
    "preprocess": "影像前處理",
    "locate": "定位",
    "measure": "量測",
    "detect": "檢測 / 識別",
    "dl": "深度學習",
    "logic": "邏輯",
    "output": "輸出",
    "decoration": "註解",
}


#: 每個工具都有的隱含輸出：本節點的標記（overlays），接給 draw_result 疊圖。
IMPLICIT_OVERLAYS_PORT = {"key": "_overlays", "label": "標記", "type": "list", "required": False, "multiple": False, "tone": "neutral", "implicit": True}
#: 影像直通（每個工具預設可把影像傳進、傳出）：輸出＝原影像原樣往下傳（標記只是 metadata 不畫進影像）；
#: 沒有任何 image 輸入的工具（邏輯類）另補直通輸入。引擎在 execute 後負責發值（工具本身不讀不寫）。
IMPLICIT_IMAGE_OUT = {"key": "_image", "label": "影像（直通）", "type": "image", "required": False, "multiple": False, "tone": "neutral", "implicit": True}
IMPLICIT_IMAGE_IN = {"key": "_image", "label": "影像（直通）", "type": "image", "required": False, "multiple": False, "tone": "neutral", "implicit": True}


def catalogue() -> list[dict[str, Any]]:
    return [
        {
            "key": t.key,
            "label": t.label,
            "description": t.description,
            "category": t.category,
            "category_label": CATEGORY_LABELS.get(t.category, t.category),
            "icon": t.icon,
            "heavy": bool(getattr(t, "heavy", False)),
            "version": int(getattr(t, "version", 1)),
            "params": [p.as_dict() for p in t.params],
            "inputs": [p.as_dict() for p in t.inputs] + ([] if any(p.type == "image" for p in t.inputs) else [IMPLICIT_IMAGE_IN]),
            "outputs": [p.as_dict() for p in t.outputs] + [IMPLICIT_IMAGE_OUT, IMPLICIT_OVERLAYS_PORT],
        }
        for t in all_types()
    ]


def now() -> float:
    return time.perf_counter()
