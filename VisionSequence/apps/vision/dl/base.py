"""Trainer 框架與 registry：平台內教導（標記 → 訓練 → 匯出 ONNX 資產）。

設計沿用工具框架的哲學：
- 引擎與 UI 不認識任何 trainer；以 kind 註冊，前端表單從 catalogue() 產生（Param 沿用工具的封閉集合），
  之後導入其他深度學習模型只要新增 Trainer 子類別，UI 共用不用改。
- 資料夾外掛（plugins/）放繼承 Trainer 的類別即自動掛載（apps/core/plugins.py）。
- 訓練產物是 ONNX bytes ＋建議的工具參數（tool_key／tool_params），存成資產後
  對應的 dl_* 工具直接可用。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

import cv2
import numpy as np

from apps.vision.tools.base import Param

log = logging.getLogger(__name__)

#: 標記模式（封閉集合；前端標記介面依此切換）：
#: classes = 整張影像一個類別；shapes = 一張影像多個 polygon/bbox 實例（分割／偵測）。
LABEL_MODES = ("classes", "shapes")


class TrainError(Exception):
    """可預期的訓練失敗（樣本不足、參數不合法…）；訊息會顯示給使用者。"""


class TrainCancelled(Exception):
    """使用者取消訓練。"""


@dataclass
class SampleRef:
    """一筆標記樣本的參照；影像用 load() 才讀（訓練逐張抽特徵，不整批進記憶體）。

    shapes（label_mode=shapes 用）：[{"label": 類別名, "kind": "polygon"|"bbox", "points": [[x,y],…]}]，
    座標一律 0~1 正規化（與 YOLO txt 一致）。"""

    id: str
    label: str  # classes 模式："" = 未標記
    path: str
    shapes: list[dict[str, Any]] = field(default_factory=list)

    def load(self) -> np.ndarray | None:
        try:
            data = np.fromfile(self.path, dtype=np.uint8)
        except OSError:
            return None
        if data.size == 0:
            return None
        return cv2.imdecode(data, cv2.IMREAD_COLOR)


@dataclass
class TrainResult:
    onnx_bytes: bytes
    metrics: dict[str, Any]
    #: 模型給哪個內建工具用（dl_classify / dl_detect / dl_segment）。
    tool_key: str = "dl_classify"
    #: 放進該工具即可用的建議參數（input_size、mean、std、labels…）。
    tool_params: dict[str, Any] = field(default_factory=dict)


@dataclass
class Suggestion:
    """自動標記建議：classes 模式給 label；shapes 模式給 shapes（整張圖的建議形狀）。"""

    sample_id: str
    label: str
    score: float
    shapes: list[dict[str, Any]] | None = None


#: progress(fraction 0~1, stage 說明, metrics 或 None)；實作要定期呼叫，並在拋 TrainCancelled 時停止。
ProgressFn = Callable[[float, str, dict[str, Any] | None], None]


class Trainer:
    """方便繼承的基底：子類宣告欄位並實作 train()／suggest()。"""

    kind = ""
    label = ""
    description = ""
    #: False = 資料夾外掛掃描時不掛載。
    enabled = True
    #: 標記模式（LABEL_MODES）。
    label_mode = "classes"
    #: 訓練產物給哪個工具用。
    tool_key = "dl_classify"
    #: 訓練超參數（沿用工具的 Param；kind 限 PARAM_KINDS，前端 ParamField 直接渲染）。
    params: list[Param] = []
    #: 支援的訓練裝置（cpu／cuda…）；devices.py 會與伺服器實際資源取交集。
    devices: tuple[str, ...] = ("cpu",)
    #: 每類最少樣本數（train 前的預檢）。
    min_per_class = 2

    def train(self, samples: list[SampleRef], classes: list[str], params: dict[str, Any], device: str, progress: ProgressFn) -> TrainResult:
        raise NotImplementedError

    def suggest(self, labeled: list[SampleRef], unlabeled: list[SampleRef], classes: list[str], params: dict[str, Any]) -> list[Suggestion]:
        """自動標記：預設不支援（子類覆寫）。"""
        raise TrainError(f"{self.kind} 不支援自動標記")


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------
_TRAINERS: dict[str, Trainer] = {}
_lock = threading.Lock()


def register_trainer(cls: type[Trainer]) -> bool:
    kind = str(getattr(cls, "kind", "") or "")
    if not kind:
        log.warning("Trainer %s 沒有 kind，略過", cls.__name__)
        return False
    for p in cls.params:
        from apps.vision.tools.base import PARAM_KINDS

        if p.kind not in PARAM_KINDS:
            log.warning("Trainer '%s' 參數 '%s' 的 kind '%s' 不在封閉集合內，略過", kind, p.key, p.kind)
            return False
    if getattr(cls, "label_mode", "classes") not in LABEL_MODES:
        log.warning("Trainer '%s' 的 label_mode 不合法，略過", kind)
        return False
    with _lock:
        if kind in _TRAINERS:
            if type(_TRAINERS[kind]) is not cls:
                log.warning("Trainer kind '%s' 已註冊，略過 %s", kind, cls.__name__)
            return False
        _TRAINERS[kind] = cls()
        return True


def get_trainer(kind: str) -> Trainer:
    from apps.core.errors import ValidationError

    trainer = _TRAINERS.get(kind)
    if trainer is None:
        raise ValidationError(f"未知的模型種類 '{kind}'", code="unknown_trainer", details={"available": sorted(_TRAINERS)})
    return trainer


def catalogue() -> list[dict[str, Any]]:
    return [
        {
            "kind": t.kind,
            "label": t.label or t.kind,
            "description": t.description,
            "label_mode": t.label_mode,
            "tool_key": t.tool_key,
            "devices": list(t.devices),
            "min_per_class": int(t.min_per_class),
            "params": [p.as_dict() for p in t.params],
        }
        for t in sorted(_TRAINERS.values(), key=lambda t: t.kind)
    ]


_registered = False


def register_builtins() -> None:
    global _registered
    if _registered:
        return
    from apps.vision.dl import builtin, yolo

    for cls in builtin.TRAINERS + yolo.TRAINERS:
        register_trainer(cls)
    _registered = True
