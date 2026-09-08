"""對位偏移與取料補償；所有幾何量均使用節點輸入影像的全圖座標。"""

from __future__ import annotations

import math

import numpy as np

from apps.vision import calib
from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError, flow_out
from apps.vision.tools.builtin.locate import _current_pose


def _rotation(angle: float) -> np.ndarray:
    """影像角度以畫面順時針為正。"""
    radians = math.radians(angle)
    cosine, sine = math.cos(radians), math.sin(radians)
    return np.array([[cosine, -sine], [sine, cosine]])


def _points(value: object) -> np.ndarray:
    """檢查成對點集合，保留全部點供最小平方解算。"""
    points = np.asarray(value, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 2 or not 2 <= len(points) <= 8:
        raise ValueError("Point sets must contain 2 to 8 [x, y] points")
    if not np.isfinite(points).all():
        raise ValueError("No current point set: coordinates must be finite")
    return points


class AlignOffsetTool(Tool):
    """計算由教導姿態到目前姿態的剛體變換。

    point 採先旋轉再平移（rotate-then-translate）：
    q = R(dtheta) @ (p - pivot) + pivot + [dx, dy]。
    dx/dy 是參考點的位移，不是繞影像原點旋轉時的平移項。
    point_set 使用全部 2 至 8 對點做 Kabsch/SVD，僅解旋轉與平移；
    pivot 為教導點集重心，current 為目前重心與 ref_angle + dtheta。
    grab 將相同變換套到教導取料點；其角度沿用工件角度。
    line 以有向線段中點與第一端點到第二端點的方向作為目前姿態。
    非 grab 模式的 abs_* 是目前參考姿態；world_* 是 abs_* 的標定結果。
    """

    key = "align_offset"
    label = "Alignment offset"
    description = (
        "Compare a taught pose with the current pose. Rotate about the taught point, then translate; "
        "output a following transform and absolute positions for a robot. Angles are in degrees."
    )
    category = "locate"
    icon = "Move"
    params = [
        Param("mode", "Mode", kind="select", default="point", options=[
            {"value": "point", "label": "Point and angle"},
            {"value": "point_set", "label": "Corresponding point sets"},
            {"value": "grab", "label": "Grab point compensation"},
            {"value": "line", "label": "Line midpoint and direction"},
        ], help_text="Point/grab use matches first, then a/b/c. Line uses the directed segment midpoint and angle."),
        Param("ref_x", "Reference X", kind="number", default=0, teach=True, unit="px",
              help_text="Taught position, or taught line midpoint. Point sets use their own centroid."),
        Param("ref_y", "Reference Y", kind="number", default=0, teach=True, unit="px"),
        Param("ref_angle", "Reference angle", kind="number", default=0, teach=True, unit="°",
              help_text="Taught workpiece angle; positive angles turn clockwise in the image."),
        Param("ref_points", "Reference points", kind="json", default=[], teach=True,
              visible_when={"param": "mode", "in": ["point_set"]},
              help_text="2 to 8 [x, y] points in the same order as the current points. Fits rotation and translation without scale."),
        Param("grab_x", "Taught grab X", kind="number", default=0, teach=True, unit="px",
              visible_when={"param": "mode", "in": ["grab"]}),
        Param("grab_y", "Taught grab Y", kind="number", default=0, teach=True, unit="px",
              visible_when={"param": "mode", "in": ["grab"]}),
        Param("calibration", "Calibration", kind="asset", accept="calibration",
              help_text="Optional. Converts the absolute output pose to world coordinates, preferring robot mapping over world mapping."),
    ]
    inputs = [
        Port("image", "Image", "image", required=False),
        Port("matches", "Matches", "matches", required=False),
        Port("a", "Current X", "number", required=False),
        Port("b", "Current Y", "number", required=False),
        Port("c", "Current angle", "number", required=False),
        Port("points", "Current points", "points", required=False),
        Port("line", "Current line", "any", required=False),
    ]
    outputs = [
        Port("dx", "X offset", "number"), Port("dy", "Y offset", "number"),
        Port("dtheta", "Angle offset", "number"), Port("transform", "Transform", "any"),
        Port("abs_x", "Absolute X (pixels)", "number"), Port("abs_y", "Absolute Y (pixels)", "number"),
        Port("abs_angle", "Absolute angle (image)", "number"),
        Port("world_x", "Absolute world X", "number"), Port("world_y", "Absolute world Y", "number"),
        Port("world_angle", "Absolute world angle", "number"),
        Port("mapped_x", "Mapped X", "number"), Port("mapped_y", "Mapped Y", "number"),
        Port("mapped_angle", "Mapped angle", "number"),
        flow_out("found", "Found", "ok"), flow_out("not_found", "Not found", "critical"),
    ]

    def _not_found(self, ctx: ToolContext, message: str) -> Result:
        """失敗時清空輸出，避免下游使用無效補正。"""
        outputs = {p.key: None for p in self.outputs if p.type != "flow"
                   and (ctx.param("calibration") or not p.key.startswith("world_"))}
        return Result(outputs=outputs, status="ng", branch="not_found", message=message)

    def execute(self, ctx: ToolContext) -> Result:
        mode = ctx.param("mode", "point")
        pose_ports = {"points"} if mode == "point_set" else {"line"} if mode == "line" else {"matches", "a", "b", "c"}
        if not pose_ports.intersection(ctx.inputs):
            raise ToolError("No current position: wire matches or a/b/c, points for point sets, or a line for line mode")
        try:
            rx, ry, ra = (float(ctx.param(key, 0)) for key in ("ref_x", "ref_y", "ref_angle"))
            if not np.isfinite([rx, ry, ra]).all():
                raise ValueError("Reference coordinates and angle must be finite")
            if mode == "point_set":
                reference = _points(ctx.params.get("ref_points"))
                current = _points(ctx.inputs.get("points"))
                if reference.shape != current.shape:
                    raise ValueError("Reference and current point sets must have the same number of points")
                pivot, centre = reference.mean(axis=0), current.mean(axis=0)
                source, target = reference - pivot, current - centre
                if np.linalg.norm(source) <= 1e-12 or np.linalg.norm(target) <= 1e-12:
                    raise ValueError("Point sets must contain distinct points")
                u, singular, vt = np.linalg.svd(source.T @ target)
                # 強制正旋轉，避免 SVD 把鏡射當作可接受的剛體變換。
                sign = 1.0 if np.linalg.det(vt.T @ u.T) >= 0 else -1.0
                rotation = vt.T @ np.diag([1.0, sign]) @ u.T
                if singular[0] + sign * singular[1] <= 1e-12:
                    raise ValueError("The corresponding points do not determine a unique rotation")
                dtheta = math.degrees(math.atan2(rotation[1, 0], rotation[0, 0]))
                rx, ry = map(float, pivot)
                x, y = map(float, centre)
                angle = (ra + dtheta + 180) % 360 - 180
            elif mode in ("point", "grab", "line"):
                if mode == "line":
                    line = ctx.inputs.get("line")
                    if not isinstance(line, dict):
                        raise ValueError("No current line: wire a segment with x1, y1, x2 and y2")
                    x1, y1, x2, y2 = (float(line[key]) for key in ("x1", "y1", "x2", "y2"))
                    if not np.isfinite([x1, y1, x2, y2]).all() or math.hypot(x2 - x1, y2 - y1) <= 1e-12:
                        raise ValueError("No current line: endpoints must be finite and distinct")
                    x, y = (x1 + x2) / 2, (y1 + y2) / 2
                    angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
                else:
                    # 共用既有優先序、第一筆比對與缺角度預設，不複製姿態解析規則。
                    x, y, angle = _current_pose(ctx)
                if not np.isfinite([x, y, angle]).all():
                    raise ValueError("No current position: the locate step found nothing")
                dtheta = angle - ra
            else:
                # TODO：有需求時再加入縮放與仿射模式；目前只提供剛體對位。
                raise ValueError("Mode must be point, point_set, grab or line")

            dtheta = (dtheta + 180) % 360 - 180
            dx, dy = x - rx, y - ry
            ax, ay = x, y
            if mode == "grab":
                grab = np.array([float(ctx.param("grab_x", 0)), float(ctx.param("grab_y", 0))])
                ax, ay = map(float, _rotation(dtheta) @ (grab - [rx, ry]) + [x, y])
            if not np.isfinite([dx, dy, dtheta, ax, ay]).all():
                raise ValueError("The alignment result must be finite")
            transform = {"dx": dx, "dy": dy, "dtheta": dtheta, "pivot": [rx, ry], "current": [x, y, angle]}
            outputs = {"dx": dx, "dy": dy, "dtheta": dtheta, "transform": transform,
                       "abs_x": ax, "abs_y": ay, "abs_angle": angle}
            if ctx.param("calibration"):
                # from_asset 經由 calib.load 讀檔；座標與角度共用既有標定換算。
                payload = calib.from_asset(ctx.param("calibration"), ctx.asset_path)
                mapping = payload.get("robot") or payload.get("world")
                if not mapping:
                    if not payload.get("mapping"):
                        raise ValueError("The calibration needs a robot, world, or camera mapping")
                else:
                    matrix = mapping["matrix"]
                    wx, wy = map(float, calib.apply(matrix, [[ax, ay]])[0])
                    wa = calib.angle_to_world(matrix, angle, (ax, ay))
                    if not np.isfinite([wx, wy, wa]).all():
                        raise ValueError("The calibrated position and angle must be finite")
                    outputs.update(world_x=wx, world_y=wy, world_angle=wa)
                camera_mapping = payload.get("mapping")
                if camera_mapping:
                    mx, my = map(float, calib.apply(camera_mapping["matrix"], [[ax, ay]])[0])
                    ma = calib.angle_to_world(camera_mapping["matrix"], angle, (ax, ay))
                    if not np.isfinite([mx, my, ma]).all():
                        raise ValueError("The mapped position and angle must be finite")
                    outputs.update(mapped_x=mx, mapped_y=my, mapped_angle=ma)
        except (ToolError, ValueError, TypeError, KeyError, OverflowError, np.linalg.LinAlgError) as exc:
            return self._not_found(ctx, f"Alignment unavailable: {exc}")

        label = f"dx={dx:.2f} dy={dy:.2f} dtheta={dtheta:.2f} deg"
        overlays = [
            {"kind": "point", "x": rx, "y": ry, "color": "#38bdf8", "label": "Reference"},
            {"kind": "point", "x": x, "y": y, "color": "#22c55e", "label": "Current"},
            {"kind": "line", "x1": rx, "y1": ry, "x2": x, "y2": y, "color": "#f59e0b", "width": 2},
            {"kind": "text", "x": x, "y": y, "text": label, "color": "#22c55e"},
        ]
        return Result(outputs=outputs, overlays=overlays, branch="found", message=label)


TOOLS = [AlignOffsetTool()]
