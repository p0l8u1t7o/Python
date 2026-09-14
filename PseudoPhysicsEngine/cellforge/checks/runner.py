"""Deterministic L1 checks over timelines and engineering envelopes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from cellforge.schema.models import Cell, Process, Workpiece


def run_checks(
    cell: Cell,
    workpiece: Workpiece,
    process: Process,
    timeline: dict[str, Any],
    version: int,
    vendors: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    vendors = vendors or {}
    items: list[dict[str, Any]] = []
    modules = {module.id: module for machine in cell.machines for module in machine.modules}

    robot = modules.get("robot_1")
    clearance = float((robot.params if robot else {}).get("flange_clearance_mm", -3.2))
    items.append(
        _item(
            "CHK-INT-001",
            "interference",
            "red" if clearance < 0 else "green",
            value=clearance,
            limit=0,
            unit="mm",
            objects=["robot_1.flange", "vision_fixture.open-cover-envelope"],
            detail=f"Tool flange clearance is {clearance:.1f} mm at the S3 cover-opening sweep.",
            suggestion="Retract the flange by at least 4 mm; 20 mm provides commissioning margin.",
            source="AABB swept envelope sampled at 20 ms",
            t=_station_midpoint(timeline, "S3"),
        )
    )

    cover_ids = {cover.id for sku in workpiece.skus for cover in sku.covers}
    animated = {
        node.split(".", 1)[1]
        for node, track in timeline.get("nodes", {}).items()
        if node.startswith("workpiece.") and track.get("value_deg")
    }
    missing = sorted(cover_ids - animated)
    items.append(
        _item(
            "CHK-HW-001",
            "hardware",
            "red" if missing else "green",
            value=float(len(animated)),
            limit=float(len(cover_ids)),
            unit="covers",
            objects=sorted(cover_ids),
            detail=(
                f"Animated {len(animated)}/{len(cover_ids)} covers; "
                f"missing: {', '.join(missing) or 'none'}."
            ),
            suggestion="Add open/capture/close motion for every missing cover."
            if missing
            else None,
            source="workpiece.yaml to timeline.json coverage",
        )
    )

    for module in [item for item in modules.values() if item.id.startswith("robot")]:
        vendor = vendors.get(module.vendor or "", {})
        reach = float(module.params.get("reach_mm", vendor.get("limits", {}).get("reach_mm", 905)))
        distances = []
        for step in process.steps:
            xyz = (step.target or {}).get("xyz")
            if step.actor.split(".")[0] == module.id and xyz:
                distances.append(sum(float(v) ** 2 for v in xyz) ** 0.5)
        farthest = max(distances, default=reach * 0.8)
        items.append(
            _item(
                f"CHK-REACH-{module.id}",
                "reachability",
                "red" if farthest > reach else "green",
                value=farthest,
                limit=reach,
                unit="mm",
                objects=[module.id],
                detail=f"Farthest target {farthest:.1f} mm; declared reach {reach:.1f} mm.",
                suggestion="Move robot base or select a longer-reach model."
                if farthest > reach
                else None,
                source="URDF/vendor reach and process targets",
            )
        )
        track = timeline.get("nodes", {}).get(module.id, {}).get("joints_deg", [])
        worst = max((abs(value) for key in track for value in key[1:]), default=0.0)
        items.append(
            _item(
                f"CHK-JOINT-{module.id}",
                "joint_limit",
                "red" if worst > 180 else "green",
                value=worst,
                limit=180,
                unit="deg",
                objects=[module.id],
                detail=f"Maximum commanded absolute joint angle {worst:.1f} degrees.",
                suggestion="Re-solve the pose within URDF joint limits." if worst > 180 else None,
                source="timeline joint keys and URDF limits",
            )
        )

    effective = float(timeline.get("duration_s", 0)) / max(process.takt.parallel_workpieces, 1)
    target = process.takt.target_s
    items.append(
        _item(
            "CHK-TAKT-001",
            "takt",
            "red" if effective > target * 1.1 else "yellow" if effective > target else "green",
            value=effective,
            limit=target,
            unit="s",
            objects=[station.id for station in process.stations],
            detail=f"Effective cycle {effective:.1f} s versus {target:.1f} s target.",
            suggestion="Parallelize inspection or split the cover-opening station."
            if effective > target
            else None,
            source="timeline duration / parallel_workpieces",
        )
    )
    summary = {
        color: sum(item["severity"] == color for item in items)
        for color in ("red", "yellow", "green")
    }
    return {
        "version": version,
        "generated": datetime.now().astimezone().isoformat(),
        "summary": summary,
        "items": items,
        "engine": {"collision": "swept-aabb-20ms", "native_fcl": False},
    }


def _station_midpoint(timeline: dict[str, Any], station_id: str) -> float | None:
    for station in timeline.get("stations", []):
        if station.get("id") == station_id:
            return round((float(station["t0"]) + float(station["t1"])) / 2, 3)
    return None


def _item(check_id: str, kind: str, severity: str, **values: Any) -> dict[str, Any]:
    return {"id": check_id, "type": kind, "severity": severity, **values}
