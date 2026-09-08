from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from apps.vision.dl import anomaly, retrieval
from apps.vision.tools.base import (
    Param,
    Result,
    Tool,
    ToolContext,
    ToolError,
    flow_out,
    Port,
)


def _crop(image: np.ndarray, roi: dict[str, Any] | None) -> np.ndarray:
    if not roi:
        return image.copy()
    h, w = image.shape[:2]
    x = max(0, min(w, int(roi.get("x", 0))))
    y = max(0, min(h, int(roi.get("y", 0))))
    rw = max(1, int(roi.get("w", w)))
    rh = max(1, int(roi.get("h", h)))
    x2 = max(x + 1, min(w, x + rw))
    y2 = max(y + 1, min(h, y + rh))
    return image[y:y2, x:x2].copy()


class DlRetrievalTool(Tool):
    key = "dl_retrieval"
    label = "Reference library match"
    description = "Compares the image with a saved reference library and returns the closest label."
    category = "dl"
    icon = "LibraryBig"
    params = (
        Param("model", "Reference library", kind="asset", required=True, help_text="Saved library used for matching."),
        Param("roi", "ROI", kind="roi", help_text="Area to compare. Leave empty to use the full image."),
        Param(
            "topk",
            "Vote count",
            kind="number",
            default=3,
            minimum=1,
            maximum=25,
            step=1,
            help_text="Number of closest references used for the final label.",
        ),
        Param(
            "min_similarity",
            "Minimum similarity",
            kind="number",
            default=0.0,
            minimum=-1.0,
            maximum=1.0,
            step=0.01,
            help_text="Results below this value go to not_matched.",
        ),
        Param("expected", "Expected label", kind="text", default="", help_text="Optional label required for ok."),
        Param(
            "device",
            "Device",
            kind="select",
            default="auto",
            options=[
                {"label": "Auto", "value": "auto"},
                {"label": "CPU", "value": "cpu"},
                {"label": "CUDA", "value": "cuda"},
                {"label": "DirectML", "value": "directml"},
            ],
            group="Advanced",
            help_text="Runtime device for matching.",
        ),
        Param(
            "backbone_path",
            "Reference matcher file",
            kind="text",
            default="",
            group="Advanced",
            help_text="Internal file override for tests.",
            visible_when={"param": "device", "in": []},
        ),
    )
    outputs = (
        Port("label", "Label", "string"),
        Port("similarity", "Similarity", "number"),
        Port("confidence", "Confidence", "number"),
        Port("topk", "Top matches", "list"),
        Port("ok", "OK", "bool"),
    )
    flow_outputs = (
        flow_out("ok", "OK", "ok"),
        flow_out("ng", "NG", "critical"),
        flow_out("not_matched", "Not matched", "warn"),
    )

    def execute(self, ctx: ToolContext) -> Result:
        asset = ctx.param("model")
        if not asset:
            raise ToolError("No reference library is set")
        try:
            path = ctx.asset_path(str(asset))
        except Exception as exc:  # pragma: no cover - ToolContext owns the exact error type
            raise ToolError(f"Reference library could not be found: {asset}") from exc
        # 查不到的資產是回 None 不是丟例外（比照 anomaly_tool）；少了這一行，
        # 模型被刪掉時現場看到的是 Path(None) 的 TypeError 而不是能照做的訊息。
        if not path:
            raise ToolError(f"Reference library could not be found: {asset}")
        try:
            model = retrieval.load(Path(path))
            override = str(ctx.param("backbone_path") or "").strip() or None
            sess = retrieval.backbone_session(model, path, str(ctx.param("device", "auto") or "auto"), override)
            result = retrieval.query(model, sess, _crop(ctx.require_image(), ctx.roi("roi")), ctx.number("topk", 3))
        except (retrieval.RetrievalError, anomaly.AnomalyError) as exc:
            raise ToolError(str(exc)) from exc
        min_similarity = float(ctx.number("min_similarity", 0.0))
        matched = float(result["similarity"]) >= min_similarity
        expected = str(ctx.param("expected") or "").strip()
        accepted = bool(matched and (not expected or result["label"] == expected))
        branch = "not_matched" if not matched else ("ok" if accepted else "ng")
        status = "ok" if accepted else "ng"
        label = str(result["label"]) if matched else ""
        message = "Not matched" if not matched else f"{label} {float(result['similarity']):.3f}"
        return Result(
            status=status,
            branch=branch,
            message=message,
            outputs={
                "label": label,
                "similarity": float(result["similarity"]),
                "confidence": float(result["confidence"]),
                "topk": result["topk"],
                "ok": accepted,
            },
        )


TOOLS = (DlRetrievalTool(),)
