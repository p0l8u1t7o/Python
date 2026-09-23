"""
深度學習模型管理 (規劃書 PLAN-002 第 5.2 節)

- 匯入：驗證原廠簽章、格式與雜湊後，存到 <資料目錄>/models/<模型代碼>/<版本>/ (model.onnx、model.json)
- 模型代碼＋版本不可重複；停用後不能用於新發布的配方 (已發布配方仍可執行，以免既有產線中斷)
- 配方以 "模型代碼@版本" 參照；發布時檢查模型存在、啟用中且適用於該檢測模組
"""
import json
import os
import shutil

from ..core import modelpkg
from ..store.db import now
from .updates import PUBLIC_KEY

ModelError = modelpkg.ModelPackageError


def _row(r):
    r = dict(r)
    r["meta"] = json.loads(r.pop("meta_json"))
    r["ref"] = modelpkg.ref(r["model_id"], r["version"])
    return r


def list_models(db, module_id=None, include_retired=True):
    rows = db.all("SELECT * FROM models ORDER BY model_id, id")
    out = [_row(r) for r in rows]
    if module_id:
        out = [m for m in out if m["module_id"] == module_id]
    if not include_retired:
        out = [m for m in out if m["status"] == "active"]
    return out


def get_by_ref(db, ref):
    mid, ver = modelpkg.split_ref(ref)
    r = db.one("SELECT * FROM models WHERE model_id = ? AND version = ?", (mid, ver))
    return _row(r) if r else None


def import_model(settings, db, path, actor, public_key_path=PUBLIC_KEY):
    meta, data = modelpkg.verify(path, public_key_path)
    from ..core import plugin
    if meta.get("module_id") not in plugin.available():
        raise ModelError("unknown_module", meta.get("module_id"))
    if db.one("SELECT id FROM models WHERE model_id = ? AND version = ?", (meta["model_id"], meta["version"])):
        raise ModelError("model_exists", modelpkg.ref(meta["model_id"], meta["version"]))
    d = os.path.join(settings.models_dir, meta["model_id"], meta["version"])
    tmp = d + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    with open(os.path.join(tmp, "model.onnx"), "wb") as f:
        f.write(data)
    with open(os.path.join(tmp, "model.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    shutil.rmtree(d, ignore_errors=True)
    os.replace(tmp, d)
    pk = db.insert("models", model_id=meta["model_id"], version=meta["version"], module_id=meta["module_id"],
                   task=meta.get("task", ""), sha256=meta["files"]["model.onnx"],
                   meta_json=json.dumps(meta, ensure_ascii=False), file_path=os.path.join(d, "model.onnx"),
                   status="active", imported_by=actor, imported_at=now())
    db.audit(actor, "model.import", "model", pk, ref=modelpkg.ref(meta["model_id"], meta["version"]),
             module_id=meta["module_id"], sha256=meta["files"]["model.onnx"])
    return _row(db.one("SELECT * FROM models WHERE id = ?", (pk,)))


def set_status(db, pk, status, actor):
    r = db.one("SELECT * FROM models WHERE id = ?", (pk,))
    if r is None:
        raise ModelError("model_not_found", pk)
    if status not in ("active", "retired"):
        raise ModelError("invalid_model_status", status)
    db.execute("UPDATE models SET status = ? WHERE id = ?", (status, pk))
    db.audit(actor, "model.retire" if status == "retired" else "model.activate", "model", pk,
             ref=modelpkg.ref(r["model_id"], r["version"]))
    return _row(db.one("SELECT * FROM models WHERE id = ?", (pk,)))


def model_refs(recipe_body):
    """配方中所有模型參照 [(模組代碼, 參照)]"""
    from ..core import plugin
    out = []
    mods = plugin.available()
    for m in recipe_body.get("modules", []):
        cls = mods.get(m["module_id"])
        if not cls:
            continue
        for p in cls.params:
            if p.type == "model":
                v = (m.get("params") or {}).get(p.key, p.default)
                if v:
                    out.append((m["module_id"], v))
    return out


def check_recipe(db, recipe_body):
    """發布時檢查：模型存在、啟用中、適用於該模組"""
    for module_id, r in model_refs(recipe_body):
        m = get_by_ref(db, r)
        if m is None:
            raise ModelError("model_not_found", r)
        if m["status"] != "active":
            raise ModelError("model_retired", r)
        if m["module_id"] != module_id:
            raise ModelError("model_module_mismatch", r)


def resolve(db, recipe_body):
    """分析子行程用：{參照: dict(path, meta)}；找不到的參照不列入 (模組回報無法使用模型)"""
    out = {}
    for _, r in model_refs(recipe_body):
        m = get_by_ref(db, r)
        if m and os.path.isfile(m["file_path"]):
            out[r] = dict(path=m["file_path"], meta=m["meta"])
    return out
