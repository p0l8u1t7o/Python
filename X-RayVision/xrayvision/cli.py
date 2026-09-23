"""
命令列入口

  python -m xrayvision analyze <影像或資料夾 ...> --recipe <配方.json> --out <輸出資料夾>
                               [--workers N] [--calibration-root DIR] [--acq "kv=90,power_w=5"] [--no-overlay]
  python -m xrayvision validate <同一視野的多張影像 ...> --recipe <配方.json> --out <輸出資料夾> [--tolerance 0.2]
  python -m xrayvision calib-create --id <代碼> --flat <空拍影像 ...> [--dark <暗場影像 ...>]
                                    [--conditions "tube_voltage_kv=90,tube_mode=high_resolution"] [--root DIR]
  python -m xrayvision modules
  python -m xrayvision recipe-template <module_id>
  python -m xrayvision reset-password <帳號> --data <資料目錄>     本機救援：產生一次性密碼 (需可寫入資料目錄)
  python -m xrayvision validate-module <module_id> --dataset <驗證資料集> --recipe <配方.json> --out <資料夾>
                                       [--model 模型代碼@版本=<.xrvmodel>]   模組驗證報告
"""
import argparse
import csv
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor

import cv2

from . import PRODUCT_NAME, __version__
from .core import acquisition, plugin, runtime, serialize, validation
from .core.calibration import CalibrationError, CalibrationProfile
from .core.io import ImageFormatError, list_images
from .core.pipeline import DEFAULT_CALIBRATION_ROOT, Recipe, RecipeError, analyze_image, load_profile
from .core.render import render
from .i18n import DEFAULT_LOCALE, LOCALES, t


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------
def _analyze_one(job):
    path, recipe_dict, out_dir, overlay, calib_root, acq = job
    recipe = Recipe.from_dict(recipe_dict)
    try:
        result, prep = analyze_image(path, recipe, calibration_root=calib_root, acquisition_manual=acq)
    except (ImageFormatError, CalibrationError) as e:
        return dict(path=path, error=e.code)
    stem = os.path.splitext(os.path.basename(path))[0]
    if out_dir:
        serialize.dump(result, os.path.join(out_dir, f"{stem}.result.json"))
        if overlay:
            cv2.imwrite(os.path.join(out_dir, f"{stem}.overlay.jpg"), render(prep.display, result),
                        [cv2.IMWRITE_JPEG_QUALITY, 90])
    return dict(path=path, result=serialize.to_jsonable(result))


def _init_worker():
    runtime.apply_limits(low_priority=True, cv_threads=1)


def _run_jobs(jobs, workers):
    runtime.apply_limits(low_priority=True, cv_threads=1)
    workers = min(workers or runtime.default_workers(), len(jobs))
    if workers > 1:
        with ProcessPoolExecutor(workers, initializer=_init_worker) as ex:
            return list(ex.map(_analyze_one, jobs))
    return [_analyze_one(j) for j in jobs]


SUMMARY_FIELDS = ["folder", "image", "kind", "reference_only", "quality", "quality_issues", "module", "status",
                  "reasons", "shift_dx_px", "shift_dy_px", "shift_se_px", "shift_dx_um", "shift_dy_um", "rotation_deg",
                  "scale_ppm", "inliers", "grade", "sites_used", "groups", "elapsed_s"]
QUALITY_FIELDS = ["folder", "image", "metric", "value", "level", "warn_below", "warn_above", "fail_below",
                  "fail_above"]


def _loc(outcome):
    return (os.path.basename(os.path.dirname(os.path.abspath(outcome["path"]))), os.path.basename(outcome["path"]))


def _summary_rows(outcome):
    folder, name = _loc(outcome)
    if "error" in outcome:
        return [[folder, name, "", "", "", "", "", "error", outcome["error"]] + [""] * 12]
    r = outcome["result"]
    issues = ";".join(f"{c['metric']}={c['level']}" for c in r["quality"]["checks"] if c["level"] != "pass")
    rows = []
    for m in r["modules"]:
        s = m["summary"] or {}
        e = s.get("die_shift") or {}
        rows.append([folder, name, r["image"]["kind"], int(r["reference_only"]), r["quality"]["level"], issues,
                     m["module_id"], m["status"], ";".join(m["reasons"]), e.get("dx", ""), e.get("dy", ""),
                     e.get("se", ""), e.get("dx_um", ""), e.get("dy_um", ""), e.get("rot_deg", ""),
                     e.get("scale_ppm", ""), e.get("n_in", ""), s.get("grade", ""), s.get("sites_used", ""),
                     len(m["groups"]), round(m["elapsed_s"], 2)])
    return rows


def _quality_rows(outcome):
    if "error" in outcome:
        return []
    folder, name = _loc(outcome)
    out = []
    checked = {c["metric"]: c for c in outcome["result"]["quality"]["checks"]}
    for k, v in sorted(outcome["result"]["quality"]["metrics"].items()):
        c = checked.get(k, {})
        rule = c.get("rule", {})
        out.append([folder, name, k, v, c.get("level", ""), rule.get("warn_below", ""), rule.get("warn_above", ""),
                    rule.get("fail_below", ""), rule.get("fail_above", "")])
    for k, c in checked.items():
        if k.startswith("acquisition."):
            out.append([folder, name, k, c["value"], c["level"], c["rule"].get("warn_below", ""),
                        c["rule"].get("warn_above", ""), "", ""])
    return out


def _load_recipe(path, locale):
    try:
        return Recipe.load(path)
    except (OSError, RecipeError) as e:
        print(f"{t('error.invalid_recipe', locale)}: {e}", file=sys.stderr)
        return None


def cmd_analyze(a):
    recipe = _load_recipe(a.recipe, a.locale)
    if recipe is None:
        return 2
    try:
        load_profile(recipe, a.calibration_root)           # 先檢查校正設定檔，避免每張都失敗
    except CalibrationError as e:
        print(f"{t('error.' + e.code, a.locale)}: {e.detail}", file=sys.stderr)
        return 2
    files = list_images(a.inputs)
    if not files:
        print("no images", file=sys.stderr)
        return 2
    acq = acquisition.parse_manual(a.acq) or None
    jobs = []
    for f in files:
        d = os.path.join(a.out, os.path.basename(os.path.dirname(os.path.abspath(f))))
        os.makedirs(d, exist_ok=True)
        jobs.append((f, recipe.to_dict(), d, not a.no_overlay, a.calibration_root, acq))
    outcomes = _run_jobs(jobs, a.workers)
    os.makedirs(a.out, exist_ok=True)
    for fname, fields, fn in (("summary.csv", SUMMARY_FIELDS, _summary_rows),
                              ("quality.csv", QUALITY_FIELDS, _quality_rows)):
        with open(os.path.join(a.out, fname), "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(fields)
            for o in outcomes:
                w.writerows(fn(o))
    for o in outcomes:
        for row in _summary_rows(o):
            shift = (f"shift=({row[9]:+.2f},{row[10]:+.2f})px se={row[11]:.2f} {row[17]}" if row[9] != "" else row[8])
            print(f"{row[0]}/{row[1]:<16} quality={row[4]:<5} {row[7]:<10} {shift}"
                  + (f"  [{row[5]}]" if row[5] else ""))
    print(f"output: {os.path.abspath(a.out)}")
    return 0


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------
def cmd_validate(a):
    recipe = _load_recipe(a.recipe, a.locale)
    if recipe is None:
        return 2
    files = list_images(a.inputs)
    if len(files) < 2:
        print("at least two images are required", file=sys.stderr)
        return 2
    module_id = a.module or recipe.modules[0].module_id
    if not plugin.get(module_id).summary_vector:
        print(f"module {module_id} does not support invariance validation", file=sys.stderr)
        return 2
    jobs = [(f, recipe.to_dict(), None, False, a.calibration_root, None) for f in files]
    outcomes = _run_jobs(jobs, a.workers)
    errors = [o for o in outcomes if "error" in o]
    if errors:
        for o in errors:
            print(f"{o['path']}: {t('error.' + o['error'], a.locale)}", file=sys.stderr)
        return 2
    results = [o["result"] for o in outcomes]
    v = validation.invariance(results, module_id, a.tolerance)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "validation.md"), "w", encoding="utf-8") as f:
        f.write(validation.to_markdown(v, lambda k: t(k, a.locale)))
    serialize.dump(v, os.path.join(a.out, "validation.json"))
    s = v["spread"]
    print(f"{module_id}: {'PASSED' if v['passed'] else 'FAILED'}  "
          + (f"max pairwise {s['max_pairwise']:.3f} px (tolerance {a.tolerance} px)" if s else "insufficient results"))
    print(f"output: {os.path.abspath(a.out)}")
    return 0 if v["passed"] else 1


# ---------------------------------------------------------------------------
# calib-create / modules / recipe-template
# ---------------------------------------------------------------------------
def cmd_calib_create(a):
    try:
        prof = CalibrationProfile.build(a.id, list_images(a.flat), list_images(a.dark) if a.dark else (),
                                        conditions=acquisition.normalize(acquisition.parse_manual(a.conditions)),
                                        note=a.note or "")
        d = prof.save(a.root)
    except (CalibrationError, ImageFormatError) as e:
        print(f"{t('error.' + e.code, a.locale)}: {getattr(e, 'detail', '') or getattr(e, 'path', '')}",
              file=sys.stderr)
        return 2
    print(f"calibration profile saved: {os.path.abspath(d)}  (flat {prof.flat_frames}, dark {prof.dark_frames})")
    return 0


def cmd_modules(a):
    for mid, cls in sorted(plugin.available().items()):
        print(f"{mid}  v{cls.version}  {cls.names.get(a.locale, mid)}  kinds={','.join(cls.supported_kinds)}")
        for p in cls.params:
            rng = f"[{p.min}, {p.max}]" if p.min is not None else (f"{list(p.choices)}" if p.choices else "")
            print(f"    {p.key:<22} {p.type:<6} default={p.default!r:<8} {rng:<16} {p.unit:<6} "
                  f"{p.label.get(a.locale, p.key)}{'  (advanced)' if p.advanced else ''}")
    return 0


def cmd_recipe_template(a):
    cls = plugin.get(a.module_id)
    d = dict(recipe_id=f"{a.module_id}-default", version=1,
             name={"zh-TW": cls.names.get("zh-TW", a.module_id), "en": cls.names.get("en", a.module_id)},
             pixel_size_um=None, calibration_profile=None, quality_rules=[], acquisition_limits={},
             modules=[dict(module_id=a.module_id, params={p.key: p.default for p in cls.params})])
    print(json.dumps(d, ensure_ascii=False, indent=2))
    return 0


def cmd_serve(a):
    import uvicorn
    from .config import Settings
    from .service.api import create_app
    settings = Settings.load(a.data)
    if a.port:
        settings.port = a.port
    app = create_app(settings, workers=a.workers or None, watch=not a.no_watch)
    print(f"{PRODUCT_NAME} {__version__}  data={settings.data_dir}  http://{settings.host}:{settings.port}")
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="warning")
    return 0


def cmd_recipe_import(a):
    from .config import Settings
    from .service.recipes import RecipeStore, RecipeStoreError
    from .store.db import Database
    settings = Settings.load(a.data)
    settings.ensure_dirs()
    store = RecipeStore(Database(settings.db_path))
    try:
        with open(a.file, encoding="utf-8") as f:
            body = json.load(f)
        row = store.create_draft(body, a.operator, note=f"imported from {os.path.basename(a.file)}")
        if a.release:
            row = store.release(row["id"], a.operator)
    except (OSError, ValueError, RecipeStoreError) as e:
        print(f"{t('error.invalid_recipe', a.locale)}: {e}", file=sys.stderr)
        return 2
    print(f"recipe {row['recipe_id']} v{row['version']} ({row['status']}) id={row['id']}")
    return 0


def cmd_reset_password(a):
    """忘記密碼且沒有其他系統管理員時的本機救援：重設為一次性密碼、解除鎖定並啟用帳號"""
    import secrets
    from .config import Settings
    from .service import auth
    from .store.db import Database
    settings = Settings.load(a.data)
    if not os.path.isfile(settings.db_path):
        print(f"database not found: {settings.db_path}", file=sys.stderr)
        return 2
    db = Database(settings.db_path)
    u = db.one("SELECT * FROM users WHERE username = ?", (a.username,))
    if u is None:
        print(t("error.user_not_found", a.locale), file=sys.stderr)
        return 2
    pw = secrets.token_urlsafe(9)
    auth.reset_password(db, u["id"], pw, actor="local-console")
    if not u["active"]:
        db.execute("UPDATE users SET active = 1 WHERE id = ?", (u["id"],))
        db.audit("local-console", "user.update", "user", u["id"], active=1)
    print(f"{a.username}: {pw}")
    return 0


def cmd_validate_module(a):
    from .core import module_validation as MV
    from .service.updates import PUBLIC_KEY
    try:
        models = MV.load_models(a.model, PUBLIC_KEY)
        rep = MV.run(a.module_id, a.dataset, a.recipe, a.out, models=models, locale=a.locale,
                     progress=lambda i, n, f: print(f"[{i}/{n}] {f}", flush=True))
    except (MV.ValidationSetError, KeyError, ValueError) as e:
        print(f"{t('error.' + getattr(e, 'code', 'invalid_request'), a.locale)}: {e}", file=sys.stderr)
        return 2
    for c in rep["checks"]:
        mark = "OK" if c["passed"] else "NG"
        print(f"  {mark}  {c['metric']:<22} {c['value']!s:<24} {c['op']} {c['limit']}")
    print(("PASSED" if rep["passed"] else "FAILED") + f" → {os.path.join(a.out, 'report.html')}")
    return 0 if rep["passed"] else 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="xrayvision", description=f"{PRODUCT_NAME} {__version__}")
    ap.add_argument("--locale", choices=LOCALES, default=DEFAULT_LOCALE)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("analyze", help="analyze images with a recipe")
    p.add_argument("inputs", nargs="+")
    p.add_argument("--recipe", required=True)
    p.add_argument("--out", default="output")
    p.add_argument("--workers", type=int, default=0, help="parallel processes (default: half of CPU cores)")
    p.add_argument("--calibration-root", default=DEFAULT_CALIBRATION_ROOT)
    p.add_argument("--acq", default="", help='acquisition parameters, e.g. "kv=90,power_w=5,frames=8"')
    p.add_argument("--no-overlay", action="store_true")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("validate", help="measurement invariance validation on images of the same field of view")
    p.add_argument("inputs", nargs="+")
    p.add_argument("--recipe", required=True)
    p.add_argument("--module", default="")
    p.add_argument("--tolerance", type=float, default=0.2, help="allowed variation between images (px)")
    p.add_argument("--out", default="validation")
    p.add_argument("--workers", type=int, default=0)
    p.add_argument("--calibration-root", default=DEFAULT_CALIBRATION_ROOT)
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("calib-create", help="create a dark/flat-field calibration profile")
    p.add_argument("--id", required=True)
    p.add_argument("--flat", nargs="+", required=True)
    p.add_argument("--dark", nargs="*", default=[])
    p.add_argument("--conditions", default="")
    p.add_argument("--note", default="")
    p.add_argument("--root", default=DEFAULT_CALIBRATION_ROOT)
    p.set_defaults(func=cmd_calib_create)

    p = sub.add_parser("serve", help="run the platform service (HTTP API, job queue, folder watcher)")
    p.add_argument("--data", default=None, help="data directory (default: XRAYVISION_DATA or ./data_xrv)")
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--workers", type=int, default=0)
    p.add_argument("--no-watch", action="store_true")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("recipe-import", help="import a recipe JSON into the database as a new version")
    p.add_argument("file")
    p.add_argument("--data", default=None)
    p.add_argument("--release", action="store_true")
    p.add_argument("--operator", default="local")
    p.set_defaults(func=cmd_recipe_import)

    p = sub.add_parser("reset-password", help="local recovery: reset an account to a one-time password")
    p.add_argument("username")
    p.add_argument("--data", default=None)
    p.set_defaults(func=cmd_reset_password)
    p = sub.add_parser("validate-module", help="validate an inspection module against an annotated dataset")
    p.add_argument("module_id")
    p.add_argument("--dataset", required=True)
    p.add_argument("--recipe", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--model", action="append", default=[], help="model_id@version=<file.xrvmodel>")
    p.set_defaults(func=cmd_validate_module)
    p = sub.add_parser("modules", help="list inspection modules and parameters")
    p.set_defaults(func=cmd_modules)
    p = sub.add_parser("recipe-template", help="print a default recipe for a module")
    p.add_argument("module_id")
    p.set_defaults(func=cmd_recipe_template)
    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
