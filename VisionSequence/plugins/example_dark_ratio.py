"""範例外掛（一）：自訂「工具」— 暗區比例檢測。

放在 plugins/ 資料夾即自動偵測掛載（重啟後端生效），不用改 .env。
下面三個變數可直接修改，改顯示名稱／說明／要不要掛載：
"""

from __future__ import annotations

DISPLAY_NAME = "暗區比例（範例外掛）"
DESCRIPTION = "ROI 內灰階低於門檻的像素比例，超過允許比例走「不良」分支。"
ENABLED = True  # False = 這個檔案整個不掛載

import cv2  # noqa: E402

from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError, flow_out  # noqa: E402
from apps.vision.tools.roi import crop, region_overlay  # noqa: E402


class DarkRatioTool(Tool):
    key = "dark_ratio"          # 全域唯一；圖 JSON 記這個
    label = DISPLAY_NAME
    description = DESCRIPTION
    enabled = ENABLED           # 也可只停用單一類別（其他類別照常掛載）
    category = "detect"         # source|preprocess|locate|measure|detect|dl|logic|output
    icon = "Moon"               # lucide-react 圖示名
    params = [
        Param("roi", "區域", kind="roi", shapes=["rect", "rotated_rect", "circle", "polygon"]),
        Param("threshold", "門檻", kind="number", default=80, minimum=0, maximum=255, teach=True),
        Param("max_ratio", "允許比例", kind="number", default=0.1, minimum=0, maximum=1, step=0.01, teach=True),
    ]
    inputs = [Port("image", "影像", "image"), Port("roi", "區域（動態）", "region", required=False)]
    outputs = [Port("ratio", "比例", "number"), flow_out("pass", "通過", "ok"), flow_out("fail", "不良", "critical")]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        if image.ndim == 3:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        region = ctx.roi()
        c = crop(image, region, upright=True)
        if c.image.size == 0:
            raise ToolError("ROI 在影像外")
        pixels = c.image[c.mask > 0] if c.mask is not None else c.image
        ratio = float((pixels < ctx.number("threshold", 80)).mean()) if pixels.size else 0.0
        ok = ratio <= ctx.number("max_ratio", 0.1)
        overlays = [region_overlay(region, label=f"dark {ratio * 100:.1f}%")] if region else []
        return Result(outputs={"ratio": ratio}, branch="pass" if ok else "fail", status="ok" if ok else "ng", overlays=overlays, message=f"暗區 {ratio * 100:.1f}%")
