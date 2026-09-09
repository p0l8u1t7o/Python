"""目標追蹤工具：以流程變數保存純資料狀態，維持跨 run 的穩定 ID。"""

from __future__ import annotations

import math
from typing import Any

from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError, flow_out

LINE_MODE_OPTIONS = [
    {"value": "none", "label": "None"},
    {"value": "points", "label": "Two points"},
]
ALGORITHM_OPTIONS = [{"value": "platform", "label": "Platform"}, {"value": "bytetrack", "label": "Tracker reference"}]
MOTION_OPTIONS = [{"value": "free", "label": "Free"}, {"value": "linear", "label": "Linear"}]


def _detections(ctx: ToolContext) -> list[dict[str, Any]]:
    raw = ctx.inputs.get("matches")
    if raw is None:
        raw = ctx.inputs.get("boxes")
    if raw is None:
        raise ToolError("Connect matches or boxes")
    if not isinstance(raw, list):
        raise ToolError("Matches or boxes must be a list")
    out: list[dict[str, Any]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ToolError(f"Detection {i} is not an object")
        box = dict(item)
        try:
            if "cx" in box and "cy" in box:
                cx, cy = float(box["cx"]), float(box["cy"])
                w = float(box.get("w", 0) or 0)
                h = float(box.get("h", 0) or 0)
                x = float(box.get("x", cx - w / 2 if w else cx))
                y = float(box.get("y", cy - h / 2 if h else cy))
            elif "x" in box and "y" in box and "w" in box and "h" in box:
                x, y, w, h = float(box["x"]), float(box["y"]), float(box["w"]), float(box["h"])
                cx, cy = x + w / 2, y + h / 2
            elif isinstance(box.get("bbox"), list) and len(box["bbox"]) >= 4:
                x, y, w, h = (float(v) for v in box["bbox"][:4])
                cx, cy = x + w / 2, y + h / 2
            else:
                raise TypeError
        except (TypeError, ValueError):
            raise ToolError(f"Detection {i} must have cx/cy, x/y/w/h, or bbox") from None
        det = dict(box)
        centroid = box.get("centroid")
        if isinstance(centroid, (list, tuple)) and len(centroid) >= 2:
            try:
                cx, cy = float(centroid[0]), float(centroid[1])
            except (TypeError, ValueError):
                pass
        det.update({"cx": cx, "cy": cy, "x": x, "y": y, "w": w, "h": h, "source_index": i})
        det["centroid"] = [round(float(cx), 3), round(float(cy), 3)]
        out.append(det)
    return out


def _state(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"next_id": 1, "tracks": [], "count_in": 0, "count_out": 0}
    tracks = raw.get("tracks")
    next_id = int(raw.get("next_id", 1) or 1)
    return {
        "next_id": max(1, next_id),
        "tracks": tracks if isinstance(tracks, list) else [],
        "count_in": int(raw.get("count_in", 0) or 0),
        "count_out": int(raw.get("count_out", 0) or 0),
    }


def _clean_track(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    try:
        tid = int(raw["id"])
        cx, cy = float(raw["cx"]), float(raw["cy"])
        vx, vy = float(raw.get("vx", 0) or 0), float(raw.get("vy", 0) or 0)
        age, missing = int(raw.get("age", 1) or 1), int(raw.get("missing", 0) or 0)
    except (KeyError, TypeError, ValueError):
        return None
    centroid = raw.get("centroid")
    if not (isinstance(centroid, list) and len(centroid) >= 2):
        centroid = [cx, cy]
    match = raw.get("match")
    if not isinstance(match, dict):
        match = {}
    return {
        "id": tid, "cx": cx, "cy": cy, "vx": vx, "vy": vy, "age": age, "missing": missing,
        "last_cx": float(raw.get("last_cx", cx) or cx), "last_cy": float(raw.get("last_cy", cy) or cy),
        "line_side": raw.get("line_side"),
        "hits": int(raw.get("hits", age if missing == 0 else max(0, age - missing)) or 0),
        "confirmed": bool(raw.get("confirmed", False)),
        "sent": bool(raw.get("sent", False)),
        "centroid": [float(centroid[0]), float(centroid[1])],
        "match": match,
        "track_id": raw.get("track_id"),
    }


def _line(ctx: ToolContext) -> tuple[float, float, float, float] | None:
    raw = ctx.inputs.get("count_line")
    if raw is None:
        raw = ctx.param("count_line")
    if raw in (None, "") or str(ctx.param("line_mode", "none")) == "none":
        return None
    try:
        if isinstance(raw, dict):
            return float(raw["x1"]), float(raw["y1"]), float(raw["x2"]), float(raw["y2"])
        if isinstance(raw, list) and len(raw) >= 2:
            return float(raw[0][0]), float(raw[0][1]), float(raw[1][0]), float(raw[1][1])
    except (KeyError, TypeError, ValueError, IndexError):
        pass
    raise ToolError("Count line must be two points")


def _side(line: tuple[float, float, float, float], cx: float, cy: float) -> float:
    x1, y1, x2, y2 = line
    return (x2 - x1) * (cy - y1) - (y2 - y1) * (cx - x1)


def _round_track(track: dict[str, Any]) -> dict[str, Any]:
    out = {
        "id": int(track["id"]),
        "cx": round(float(track["cx"]), 3),
        "cy": round(float(track["cy"]), 3),
        "vx": round(float(track["vx"]), 3),
        "vy": round(float(track["vy"]), 3),
        "age": int(track["age"]),
        "missing": int(track["missing"]),
        "confirmed": bool(track.get("confirmed", False)),
        "sent": bool(track.get("sent", False)),
        "centroid": [round(float(track.get("centroid", [track["cx"], track["cy"]])[0]), 3), round(float(track.get("centroid", [track["cx"], track["cy"]])[1]), 3)],
    }
    if track.get("track_id") is not None:
        out["track_id"] = track.get("track_id")
    return out


def _track_item(track: dict[str, Any]) -> dict[str, Any]:
    """輸出給下游的物件資料：保留最新 match 欄位並覆上平台追蹤欄位。"""
    item = dict(track.get("match") or {})
    item.update(_round_track(track))
    item["id"] = int(track["id"])
    return item


def _velocity(track: dict[str, Any], det: dict[str, Any], *, motion: str) -> tuple[float, float]:
    steps = max(1, int(track["missing"]) + 1)
    vx = (float(det["cx"]) - float(track["last_cx"])) / steps
    vy = (float(det["cy"]) - float(track["last_cy"])) / steps
    if motion != "linear":
        return vx, vy
    old_vx, old_vy = float(track.get("vx", 0) or 0), float(track.get("vy", 0) or 0)
    vx = old_vx * 0.7 + vx * 0.3
    vy = old_vy * 0.7 + vy * 0.3
    if old_vx or old_vy:
        dot = vx * old_vx + vy * old_vy
        if dot < 0:
            vx, vy = old_vx, old_vy
    return vx, vy


class TrackObjectsTool(Tool):
    key = "track_objects"
    label = "Track objects"
    description = (
        "Assigns stable IDs to a stream of match boxes using predicted position plus nearest-neighbour matching. "
        "This is meaningful only in continuous runs; previews and sandbox runs keep their state in the variable overlay."
    )
    category = "logic"
    icon = "Route"
    params = [
        Param("state_name", "State variable", kind="output_key", default="track_objects",
              help_text="Flow variable used for tracker state. Use a different name for each independent tracker."),
        Param("algorithm", "Algorithm", kind="select", default="platform", options=ALGORITHM_OPTIONS),
        Param("max_distance", "Max distance", kind="number", default=25, minimum=0, step=1, teach=True,
              help_text="A detection farther than this from the predicted position starts a new track."),
        Param("max_missing", "Max missing", kind="number", default=2, minimum=0, step=1,
              help_text="A track is kept for this many consecutive missed frames, then removed."),
        Param("confirm_frames", "Confirm frames", kind="number", default=2, minimum=1, step=1, teach=True,
              help_text="A track must be seen this many consecutive frames before it is emitted."),
        Param("motion", "Motion model", kind="select", default="free", options=MOTION_OPTIONS),
        Param("reset", "Reset", kind="boolean", default=False, help_text="Clear the saved tracking state before this frame."),
        Param("line_mode", "Count line", kind="select", default="none", options=LINE_MODE_OPTIONS, group="Counting"),
        Param("count_line", "Line points", kind="json", default=None, group="Counting",
              visible_when={"param": "line_mode", "in": ["points"]}, help_text='Two points: [[x1,y1],[x2,y2]]. Negative-to-positive crossing is count_in.'),
    ]
    inputs = [
        Port("matches", "Matches", "matches", required=False),
        Port("boxes", "Boxes", "matches", required=False),
        Port("count_line", "Count line", "any", required=False),
        Port("reset", "Reset", "bool", required=False),
        Port("image", "Image (for display)", "image", required=False),
    ]
    outputs = [
        flow_out("ok", "Tracking", "ok"), flow_out("not_found", "No tracks", "critical"),
        Port("tracks", "Tracks", "list"), Port("count", "Count", "number"),
        Port("new_confirmed", "Newly confirmed", "matches"), Port("confirmed", "Confirmed", "matches"),
        Port("new_count", "New count", "number"), Port("lost_count", "Lost count", "number"),
        Port("count_in", "Count in", "number"), Port("count_out", "Count out", "number"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        reset = ctx.flag("reset") or bool(ctx.inputs.get("reset"))
        name = str(ctx.param("state_name", "track_objects") or "track_objects")
        detections = [] if reset and not ("matches" in ctx.inputs or "boxes" in ctx.inputs) else _detections(ctx)
        max_distance = max(0.0, ctx.number("max_distance", 25))
        max_missing = max(0, ctx.integer("max_missing", 2))
        confirm_frames = max(1, ctx.integer("confirm_frames", 2))
        algorithm = str(ctx.param("algorithm", "platform") or "platform")
        motion = str(ctx.param("motion", "free") or "free")
        existing = _state(ctx.variable(name, {}))
        state = {"next_id": existing["next_id"], "tracks": [] if reset else existing["tracks"], "count_in": 0 if reset else existing["count_in"], "count_out": 0 if reset else existing["count_out"]}
        next_id = int(state["next_id"])
        tracks = [t for t in (_clean_track(t) for t in state["tracks"]) if t is not None]
        line = _line(ctx)

        pairs: list[tuple[float, int, int]] = []
        if algorithm == "bytetrack":
            by_ref: dict[int, int] = {}
            for ti, track in enumerate(tracks):
                try:
                    if track.get("track_id") is not None:
                        by_ref[int(track["track_id"])] = ti
                except (TypeError, ValueError):
                    pass
            for di, det in enumerate(detections):
                try:
                    ref = int(det.get("track_id"))
                except (TypeError, ValueError):
                    continue
                ti = by_ref.get(ref)
                if ti is not None:
                    pairs.append((0.0, ti, di))
        else:
            for ti, track in enumerate(tracks):
                px = float(track["cx"]) + float(track["vx"])
                py = float(track["cy"]) + float(track["vy"])
                for di, det in enumerate(detections):
                    dist = math.hypot(float(det["cx"]) - px, float(det["cy"]) - py)
                    if dist <= max_distance:
                        pairs.append((dist, ti, di))
        matched_tracks: set[int] = set()
        matched_dets: set[int] = set()
        updated: list[dict[str, Any]] = []
        count_in = int(state["count_in"])
        count_out = int(state["count_out"])

        for _, ti, di in sorted(pairs):
            if ti in matched_tracks or di in matched_dets:
                continue
            track = tracks[ti]
            det = detections[di]
            vx, vy = _velocity(track, det, motion=motion)
            if line is not None:
                prev_side = track.get("line_side")
                now_side = _side(line, float(det["cx"]), float(det["cy"]))
                if isinstance(prev_side, (int, float)) and prev_side != 0 and now_side != 0 and (prev_side < 0) != (now_side < 0):
                    if prev_side < 0 < now_side:
                        count_in += 1
                    else:
                        count_out += 1
                track["line_side"] = now_side
            track.update({
                "cx": float(det["cx"]), "cy": float(det["cy"]), "vx": vx, "vy": vy,
                "age": int(track["age"]) + 1, "missing": 0,
                "last_cx": float(det["cx"]), "last_cy": float(det["cy"]),
                "hits": int(track.get("hits", 0)) + 1,
                "centroid": list(det.get("centroid") or [float(det["cx"]), float(det["cy"])]),
                "match": dict(det),
                "track_id": det.get("track_id", track.get("track_id")),
            })
            updated.append(track)
            matched_tracks.add(ti)
            matched_dets.add(di)

        lost_count = 0
        for ti, track in enumerate(tracks):
            if ti in matched_tracks:
                continue
            track = dict(track)
            track["cx"] = float(track["cx"]) + float(track["vx"])
            track["cy"] = float(track["cy"]) + float(track["vy"])
            track["age"] = int(track["age"]) + 1
            track["missing"] = int(track["missing"]) + 1
            track["hits"] = 0
            track["centroid"] = [float(track["cx"]), float(track["cy"])]
            if int(track["missing"]) > max_missing:
                lost_count += 1
                continue
            updated.append(track)

        new_count = 0
        for di, det in enumerate(detections):
            if di in matched_dets:
                continue
            track = {
                "id": next_id, "cx": float(det["cx"]), "cy": float(det["cy"]), "vx": 0.0, "vy": 0.0,
                "age": 1, "missing": 0, "last_cx": float(det["cx"]), "last_cy": float(det["cy"]),
                "line_side": _side(line, float(det["cx"]), float(det["cy"])) if line is not None else None,
                "hits": 1, "confirmed": False, "sent": False, "centroid": list(det.get("centroid") or [float(det["cx"]), float(det["cy"])]),
                "match": dict(det), "track_id": det.get("track_id"),
            }
            next_id += 1
            new_count += 1
            updated.append(track)

        new_confirmed: list[dict[str, Any]] = []
        confirmed: list[dict[str, Any]] = []
        for track in updated:
            first_confirm = not bool(track.get("confirmed")) and int(track.get("hits", 0)) >= confirm_frames and int(track.get("missing", 0)) == 0
            if first_confirm:
                track["confirmed"] = True
                track["sent"] = True
                new_confirmed.append(_track_item(track))
            if bool(track.get("confirmed")) and int(track.get("missing", 0)) == 0:
                confirmed.append(_track_item(track))

        updated.sort(key=lambda t: int(t["id"]))
        stored = {"next_id": next_id, "tracks": updated, "count_in": count_in, "count_out": count_out}
        ctx.set_variable(name, stored)

        tracks_out = [_round_track(t) for t in updated]
        overlays = []
        if line is not None:
            x1, y1, x2, y2 = line
            overlays.append({"kind": "line", "x1": x1, "y1": y1, "x2": x2, "y2": y2, "color": "#38bdf8", "width": 2, "label": "count"})
        for t in updated:
            colour = "#f97316" if int(t["missing"]) else "#22c55e"
            overlays.append({"kind": "point", "x": float(t["cx"]), "y": float(t["cy"]), "color": colour, "label": f"#{int(t['id'])}"})

        return Result(
            outputs={
                "tracks": tracks_out, "count": len(tracks_out), "new_count": new_count, "lost_count": lost_count,
                "new_confirmed": new_confirmed, "confirmed": confirmed,
                "count_in": count_in, "count_out": count_out,
            },
            overlays=overlays, branch="ok" if tracks_out else "not_found", status="ok" if tracks_out else "ng",
            message=f"{len(tracks_out)} tracks, {new_count} new, {lost_count} lost",
        )


TOOLS = [TrackObjectsTool()]
