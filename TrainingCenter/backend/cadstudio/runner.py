"""在 cad/.venv 裡用 text-to-cad skill 的工具建置使用者／AI 的 build123d 程式。

環境：
  CAD_PYTHON   cadgen 所在的 Python（預設 <repo>/cad/.venv/Scripts/python.exe）
  CAD_SKILL    text-to-cad 的 skills/cad 目錄（預設 <repo>/cad/text-to-cad/skills/cad）
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path

from django.conf import settings

ROOT = Path(settings.BASE_DIR).parent
CAD_DIR = ROOT / "cad"
CAD_PYTHON = Path(os.environ.get("CAD_PYTHON") or (CAD_DIR / ".venv" / "Scripts" / "python.exe"))
CAD_SKILL = Path(os.environ.get("CAD_SKILL") or (CAD_DIR / "text-to-cad" / "skills" / "cad"))
TIMEOUT = 900

HEADER = '''# --- CAD Studio 自動加入：讓程式可以直接 import 零件庫（parts / layout / robot） ---
import sys as _sys
_sys.path.insert(0, r"{lib}")
# 相容包裝：AI 常把定位寫成 asm.add(shape, "name", loc=Location(...)) / location= / position=(x, y, z)
try:
    from build123d import Location as _Loc
    from cadgen import assembly as _cga
    if not getattr(_cga.AssemblyHelper, "_studio_patched", False):
        _orig_add = _cga.AssemblyHelper.add

        def _add(self, shape, name, *details, loc=None, location=None, position=None, rotation=None, **kw):
            move = loc if loc is not None else location
            if move is None and (position is not None or rotation is not None):
                move = _Loc(tuple(position or (0, 0, 0)), tuple(rotation or (0, 0, 0)))
            if move is not None:
                if not isinstance(move, _Loc):
                    move = _Loc(tuple(move))
                shape = shape.moved(move)
            return _orig_add(self, shape, name, *details, **kw)

        _cga.AssemblyHelper.add = _add
        _cga.AssemblyHelper.root = property(lambda self: self.compound())  # asm.root → asm.compound()
        _cga.AssemblyHelper._studio_patched = True
except Exception:  # noqa: BLE001
    pass
# ---------------------------------------------------------------------------
'''


def check_env() -> str | None:
    if not CAD_PYTHON.exists():
        return f"找不到 cadgen 的 Python：{CAD_PYTHON}。請先建立 cad/.venv 並安裝 cadgen（見 README「Text-to-CAD」），或設定環境變數 CAD_PYTHON。"
    if not (CAD_SKILL / "scripts" / "export").exists():
        return f"找不到 text-to-cad skill：{CAD_SKILL}。請執行 .\\setup-cad.ps1（會 clone tag 0.4.28；0.5.0 起上游改成 cadgen CLI，抓 main 會缺 scripts/），或設定 CAD_SKILL。"
    return None


def _run(cmd: list[str], cwd: Path, log: list[str]) -> int:
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    log.append("$ " + " ".join(str(c) for c in cmd))
    try:
        p = subprocess.run([str(c) for c in cmd], cwd=str(cwd), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        log.append(f"[timeout] 超過 {TIMEOUT} 秒")
        return 124
    if p.stdout.strip():
        log.append(p.stdout.strip())
    if p.stderr.strip():
        log.append(p.stderr.strip())
    return p.returncode


def build(job_dir: Path, code: str, want: tuple[str, ...] = ("glb", "step")) -> dict:
    """寫入 model.step.py 並建置。回傳 {ok, log, outputs: {glb, step, stl, 3mf, png}, facts}。"""
    job_dir.mkdir(parents=True, exist_ok=True)
    src = job_dir / "model.step.py"
    src.write_text(HEADER.format(lib=str(CAD_DIR / "lib")) + code.strip() + "\n", encoding="utf-8")
    log: list[str] = []
    outputs: dict[str, str] = {}
    env_err = check_env()
    if env_err:
        return {"ok": False, "log": [env_err], "outputs": outputs, "facts": {}}

    scripts = CAD_SKILL / "scripts"
    rc = _run([CAD_PYTHON, scripts / "gen", src.name, "--write"], job_dir, log)
    if rc != 0:
        return {"ok": False, "log": log, "outputs": outputs, "facts": {}}
    if (job_dir / "model.step").exists():
        outputs["step"] = "model.step"
    fmt_flags = []
    for f in want:
        if f == "glb":
            fmt_flags += ["--glb", "model.glb"]
        elif f == "stl":
            fmt_flags += ["--stl", "model.stl"]
        elif f == "3mf":
            fmt_flags += ["--3mf", "model.3mf"]
    if fmt_flags:
        rc = _run([CAD_PYTHON, scripts / "export", src.name, *fmt_flags, "--mesh-tolerance", "0.1", "--mesh-angular-tolerance", "0.2"], job_dir, log)
        if rc != 0:
            return {"ok": False, "log": log, "outputs": outputs, "facts": {}}
        for f in want:
            name = {"glb": "model.glb", "stl": "model.stl", "3mf": "model.3mf"}.get(f)
            if name and (job_dir / name).exists():
                outputs[f] = name
    # 幾何摘要
    facts: dict = {}
    flog: list[str] = []
    if _run([CAD_PYTHON, scripts / "inspect", "refs", "model.step", "--facts"], job_dir, flog) == 0:
        try:
            data = json.loads(flog[-1].splitlines()[-1])
            summ = (data.get("tokens") or [{}])[0].get("summary", {})
            facts = {k: summ.get(k) for k in ("kind", "occurrenceCount", "faceCount", "edgeCount", "bounds") if k in summ}
        except Exception:  # noqa: BLE001
            pass
    # 快照（失敗不影響結果）
    slog: list[str] = []
    if _run([CAD_PYTHON, scripts / "snapshot", "--input", "model.step", "--output", "snapshot.png", "--camera", "35:25", "--theme", "workbench-light", "--width", "800", "--height", "600"], job_dir, slog) == 0:
        pngs = sorted(job_dir.glob("snapshot*.png"))
        if pngs:
            outputs["png"] = pngs[-1].name
    return {"ok": True, "log": log, "outputs": outputs, "facts": facts}


def export_extra(job_dir: Path, fmt: str) -> dict:
    """對已建置的 job 另外匯出 stl / 3mf。"""
    log: list[str] = []
    flag = {"stl": "--stl", "3mf": "--3mf"}[fmt]
    name = f"model.{fmt}"
    rc = _run([CAD_PYTHON, CAD_SKILL / "scripts" / "export", "model.step.py", flag, name], job_dir, log)
    return {"ok": rc == 0 and (job_dir / name).exists(), "log": log, "file": name}


_lock = threading.Lock()


def run_in_thread(fn, *args):
    t = threading.Thread(target=fn, args=args, daemon=True)
    t.start()
    return t
