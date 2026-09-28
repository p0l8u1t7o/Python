"""兩個凸體恰好面貼面時，帶號距離不得卡死（DEV-006：FCL 的 GJK＋EPA 會在原生程式碼內無限迴圈）。

卡死時程序持有 GIL，pytest 無法自行逾時，因此量測一律放在有期限的子程序中執行。
「captured」是 DEV-006 真實驗收案卡死當下擷取的一組幾何與位姿：治具頂板與翻面後的
workpiece.cover_hdd，旋轉帶 1e-11 級誤差、以約 2e-8 mm 的深度貼合。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PLATE = {
    "vertices": [
        [-170.0, -125.0, 660.0],
        [-170.0, -125.0, 670.0],
        [-170.0, 125.0, 660.0],
        [170.0, -125.0, 660.0],
        [170.0, -125.0, 670.0],
        [-170.0, 125.0, 670.0],
        [170.0, 125.0, 670.0],
        [170.0, 125.0, 660.0],
    ],
    "faces": [
        [0, 2, 7], [7, 3, 0], [0, 3, 4], [4, 1, 0], [3, 7, 4], [4, 7, 6],
        [5, 2, 0], [0, 1, 5], [5, 7, 2], [6, 7, 5], [1, 4, 5], [5, 4, 6],
    ],
    "rotation": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
    "translation": [-1000.0, 0.0, 0.0],
}  # fmt: skip
COVER = {
    "vertices": [
        [0.0, -40.0, -2.0],
        [0.0, -40.0, 0.0],
        [0.0, 40.0, -2.0],
        [0.0, 40.0, 0.0],
        [100.0, -40.0, -2.0],
        [100.0, -40.0, 0.0],
        [100.0, 40.0, -2.0],
        [100.0, 40.0, 0.0],
    ],
    "faces": [
        [0, 2, 6], [6, 4, 0], [0, 4, 5], [5, 1, 0], [4, 6, 5], [5, 6, 7],
        [3, 2, 0], [0, 1, 3], [3, 6, 2], [7, 6, 3], [1, 5, 3], [3, 5, 7],
    ],
    "rotation": [
        [1.0, -9.432234434416643e-11, -6.428790700064886e-11],
        [-9.432234434416645e-11, -1.0, -6.598021371764931e-18],
        [-6.428790700064885e-11, 6.604085157866206e-18, -1.0],
    ],
    "translation": [-1009.9999999789376, 64.99999997995519, 669.9999999804639],
}  # fmt: skip

PROBE = """
import json, sys
import numpy as np
import fcl
from cellforge.checks.collision import _convex, _set_transform, _signed_distance

def place(entry, lift=0.0):
    vertices = np.asarray(entry["vertices"], dtype=float)
    obj = fcl.CollisionObject(_convex(vertices, np.asarray(entry["faces"])))
    matrix = np.eye(4)
    matrix[:3, :3] = entry["rotation"]
    matrix[:3, 3] = np.asarray(entry["translation"]) + (0.0, 0.0, lift)
    _set_transform(obj, matrix)
    world = vertices @ matrix[:3, :3].T + matrix[:3, 3]
    return obj, np.asarray([world.min(axis=0), world.max(axis=0)])

plate, cover, lifts = json.loads(sys.argv[1])
fixed, fixed_box = place(plate)
results = {}
for label, lift in lifts.items():
    moving, moving_box = place(cover, lift)
    results[label] = _signed_distance(fixed, moving, fixed_box, moving_box)[0]
print(json.dumps(results))
"""


def test_face_touching_convexes_do_not_hang_and_signs_follow_geometry():
    # 以擷取位姿為基準再上下平移：平移量即為期望的帶號間隙（由幾何構造推得）。
    lifts = {"captured": 0.0, "gap": 5.0, "penetrating": -1.5}
    completed = subprocess.run(
        [sys.executable, "-c", PROBE, json.dumps([PLATE, COVER, lifts])],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    distances = json.loads(completed.stdout.strip().splitlines()[-1])
    assert abs(distances["captured"]) < 1e-3
    assert abs(distances["gap"] - lifts["gap"]) < 1e-3
    assert abs(distances["penetrating"] - lifts["penetrating"]) < 1e-3
