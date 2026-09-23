"""
檢測模組驗證 (規劃書 PLAN-002 第 7 節；PLAN-001 第 5.6 節)

  python -m xrayvision validate-module <module_id> --dataset <驗證資料集 .zip 或資料夾> --recipe <配方.json>
        --out <輸出資料夾> [--model 模型代碼@版本=<.xrvmodel>] [--locale zh-TW]

驗證資料集 (格式 xrv-validation-set/1)：
  annotations.json   {"format", "module_id", "images": [{"file": "images/…", "balls": [[x, y, r], …],
                                                        "voids": [[[x, y], …], …], …}]}
  images/…           原始影像
  來源：平台「匯出訓練資料」勾選「包含原始影像」，或原廠端合成資料集產生器。

流程：以配方分析每張影像 → 由模組的 validation_metrics() 與標註比對 → 依模組的 validation_criteria 判定
各項是否達標 → 輸出 report.json 與 report.html。成像條件不變性與重拍重複性另以 validate 指令驗證。
"""
import html
import json
import os
import shutil
import tempfile
import time
import zipfile

from .. import __version__
from . import modelpkg, plugin
from .pipeline import Recipe, analyze_image, module_series

FORMAT = "xrv-validation-set/1"


class ValidationSetError(ValueError):
    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def load_dataset(path):
    """回傳 (資料夾, annotations dict, 暫存資料夾或 None)"""
    tmp = None
    if os.path.isfile(path):
        tmp = tempfile.mkdtemp(prefix="xrv_valset_")
        try:
            with zipfile.ZipFile(path) as z:
                for n in z.namelist():
                    dst = os.path.abspath(os.path.join(tmp, n))
                    if not dst.startswith(os.path.abspath(tmp) + os.sep):
                        raise ValidationSetError("dataset_invalid", n)
                z.extractall(tmp)
        except zipfile.BadZipFile:
            raise ValidationSetError("dataset_invalid", path)
        root = tmp
    else:
        root = path
    try:
        with open(os.path.join(root, "annotations.json"), encoding="utf-8") as f:
            ann = json.load(f)
    except (OSError, ValueError):
        raise ValidationSetError("dataset_invalid", "annotations.json")
    if ann.get("format") != FORMAT:
        raise ValidationSetError("dataset_invalid", ann.get("format"))
    return root, ann, tmp


def load_models(specs, public_key_path):
    """--model 參照=檔案 → {參照: dict(path, meta)}；模型檔解開到暫存資料夾"""
    out = {}
    for s in specs or []:
        ref, path = s.split("=", 1)
        meta, data = modelpkg.verify(path, public_key_path)
        if modelpkg.ref(meta["model_id"], meta["version"]) != ref:
            raise ValidationSetError("model_ref_mismatch", ref)
        p = os.path.join(tempfile.mkdtemp(prefix="xrv_model_"), "model.onnx")
        with open(p, "wb") as f:
            f.write(data)
        out[ref] = dict(path=p, meta=meta)
    return out


def run(module_id, dataset, recipe_path, out_dir, models=None, locale="zh-TW", progress=None):
    cls = plugin.get(module_id)
    if not hasattr(cls, "validation_metrics"):
        raise ValidationSetError("validation_not_supported", module_id)
    recipe = Recipe.load(recipe_path)
    spec_mod = next((m for m in recipe.modules if m.module_id == module_id), None)
    if spec_mod is None:
        raise ValidationSetError("module_not_in_recipe", module_id)
    spec = cls.resolve_judgment(spec_mod.judgment)
    root, ann, tmp = load_dataset(dataset)
    t0 = time.time()
    try:
        pairs = []
        for i, item in enumerate(ann["images"], 1):
            res, _ = analyze_image(os.path.join(root, item["file"]), recipe, models=models or {})
            mr = next(m for m in res.modules if m.module_id == module_id)
            pairs.append((item, mr, res))
            if progress:
                progress(i, len(ann["images"]), item["file"])
        metrics = cls.validation_metrics(pairs, spec)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    checks = []
    for key, (op, limit) in cls.validation_criteria.items():
        v = metrics.get(key)
        ok = v is not None and (v >= limit if op == ">=" else v <= limit)
        checks.append(dict(metric=key, op=op, limit=limit, value=v, passed=bool(ok)))
    metrics = json.loads(json.dumps(metrics, default=_plain))
    checks = json.loads(json.dumps(checks, default=_plain))
    report = dict(format="xrv-validation-report/1", module_id=module_id, module_version=cls.version,
                  series=module_series(cls.version), software_version=__version__, recipe=recipe.to_dict(),
                  dataset=os.path.basename(os.path.abspath(dataset)), images=len(ann["images"]),
                  models=sorted((models or {}).keys()), created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                  elapsed_s=round(time.time() - t0, 1), metrics=metrics, checks=checks,
                  passed=all(c["passed"] for c in checks))
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1, default=_plain)
    with open(os.path.join(out_dir, "report.html"), "w", encoding="utf-8") as f:
        f.write(render_html(report, locale))
    return report


def _plain(o):
    """numpy 數值轉成一般數值 (JSON)"""
    return o.item() if hasattr(o, "item") else str(o)


def render_html(r, locale):
    from ..i18n import catalog
    cat = catalog(locale)

    def t(key, _locale=None, default=None):
        return cat.get(key, key if default is None else default)

    e = html.escape

    def fmt(v):
        return "–" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))

    rows = "".join(f"<tr><td>{e(t(f'validation.metric.{c['metric']}', locale, c['metric']))}</td><td>{fmt(c['value'])}</td>"
                   f"<td>{e(c['op'])} {fmt(c['limit'])}</td><td class={'ok' if c['passed'] else 'ng'}>"
                   f"{e(t('validation.passed' if c['passed'] else 'validation.failed', locale))}</td></tr>" for c in r["checks"])
    other = "".join(f"<tr><td>{e(t(f'validation.metric.{k}', locale, k))}</td><td>{fmt(v)}</td></tr>"
                    for k, v in r["metrics"].items() if not isinstance(v, (dict, list)))
    classes = r["metrics"].get("detection_by_size") or {}
    cls_rows = "".join(f"<tr><td>{e(k)}</td><td>{v['detected']} / {v['total']}</td><td>{fmt(v['rate'])}</td></tr>"
                       for k, v in classes.items())
    verdict = t("validation.passed" if r["passed"] else "validation.failed", locale)
    return f"""<!doctype html><html lang="{e(locale)}"><head><meta charset="utf-8">
<title>{e(t('validation.module_report', locale))} {e(r['module_id'])} {e(r['module_version'])}</title>
<style>body{{font-family:"Segoe UI","Microsoft JhengHei",sans-serif;margin:24px;color:#222}}table{{border-collapse:collapse;margin:8px 0 18px}}
td,th{{border:1px solid #ccc;padding:4px 10px;text-align:left}}.ok{{color:#15803d;font-weight:600}}.ng{{color:#b91c1c;font-weight:600}}</style>
</head><body>
<h1>{e(t('validation.module_report', locale))}</h1>
<table>
<tr><th>{e(t('validation.module', locale))}</th><td>{e(r['module_id'])} {e(r['module_version'])}</td></tr>
<tr><th>{e(t('validation.dataset', locale))}</th><td>{e(r['dataset'])}（{r['images']}）</td></tr>
<tr><th>{e(t('validation.models', locale))}</th><td>{e(', '.join(r['models']) or '–')}</td></tr>
<tr><th>{e(t('validation.result', locale))}</th><td class="{'ok' if r['passed'] else 'ng'}">{e(verdict)}</td></tr>
<tr><th>{e(t('validation.created', locale))}</th><td>{e(r['created_at'])}，{e(r['software_version'])}</td></tr>
</table>
<h2>{e(t('validation.criteria', locale))}</h2>
<table><tr><th>{e(t('validation.metric', locale))}</th><th>{e(t('validation.value', locale))}</th><th>{e(t('validation.limit', locale))}</th><th></th></tr>{rows}</table>
<h2>{e(t('validation.by_size', locale))}</h2>
<table><tr><th>{e(t('validation.size_class', locale))}</th><th>{e(t('validation.detected', locale))}</th><th>{e(t('validation.rate', locale))}</th></tr>{cls_rows}</table>
<h2>{e(t('validation.all_metrics', locale))}</h2>
<table>{other}</table>
<p>{e(t('validation.note_invariance', locale))}</p>
</body></html>"""
