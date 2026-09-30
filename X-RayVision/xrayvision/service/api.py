"""
HTTP API (JSON)。前端 (React) 與工程工具透過此介面操作平台。

- 服務只綁定本機 (設定檔 host 預設 127.0.0.1)。
- 登入：產品內建帳號，工作階段存於 HttpOnly Cookie；每個端點依角色權限檢查 (auth.PERMISSIONS)。
- 授權：授權無效時拒絕匯入與重新分析，分析佇列暫停；檢視與匯出不受影響。
- 錯誤回應：{"error": 代碼, "detail": 說明}；前端以語系檔 error.<代碼> 顯示。
- OpenAPI 規格：/api/openapi.json (前端 TypeScript 型別由此產生)。
"""
import json
import os
import shutil
import threading
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from typing import List, Optional

import cv2
import numpy as np
from fastapi import Depends, FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import PRODUCT_NAME, __version__
from ..core import acquisition, inference, plugin
from ..core import regions as regions_mod
from ..core.calibration import to_display
from ..core.io import IMAGE_EXTENSIONS, ImageFormatError, load_image
from ..core.plugin import JUDGE_FAIL, JUDGE_PASS, JUDGE_REVIEW
from ..i18n import LOCALES, catalog
from ..ingest.watcher import WatchError, add_folder
from ..store.db import now
from . import auth, diagnostics
from . import modules as module_validation
from . import models as model_store
from . import annotations
from .jobs import ImportFailed, build_payload, image_path, import_image, latest_image_regions, queue_reanalysis
from . import workspace as ws_mod
from .workspace import Workspace, WorkspaceError
from . import license as lic
from . import maintenance
from . import archive_import, updates
from .platform import Platform
from .recipes import RecipeStore, RecipeStoreError

REVIEW_JUDGMENTS = (JUDGE_PASS, JUDGE_FAIL, JUDGE_REVIEW)
# 目前結果：同一影像最新一筆紀錄 (SQL 條件，紀錄別名 r)
CURRENT = "r.id = (SELECT MAX(r2.id) FROM runs r2 WHERE r2.image_id = r.image_id)"
IMG_CACHE_ITEMS = 24                     # 預覽影像快取筆數 (PNG，每筆約 1～8 MB)
WEB_DIST = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "web", "dist")


class ApiError(Exception):
    def __init__(self, status, code, detail=""):
        self.status, self.code, self.detail = status, code, str(detail)


# ---------------------------------------------------------------------------
# 請求模型
# ---------------------------------------------------------------------------
class RecipeBody(BaseModel):
    body: dict
    note: str = ""


class PathImport(BaseModel):
    paths: List[str]
    recipe_pk: int
    lot_no: str = ""
    acquisition: str = ""


class Reanalyze(BaseModel):
    recipe_pk: int


class BatchReanalyze(BaseModel):
    run_ids: List[int]
    recipe_pk: Optional[int] = None          # 未指定時使用各紀錄所用配方的最新發布版本
    keep_image_regions: bool = True          # 沿用影像的自訂檢測區域 (PLAN-004 第 6.3 節)


class ReleaseBody(BaseModel):
    reanalyze: str = "none"                  # all_previous／lot／none (PLAN-003 第 5.2 節)
    lot_no: str = ""
    keep_image_regions: bool = True          # 沿用影像的自訂檢測區域 (PLAN-004 第 6.3 節)


class RegionsBody(BaseModel):
    regions: Optional[dict] = None           # 本影像自訂檢測區域；None 表示改回配方區域


class WorkspaceParams(BaseModel):
    body: dict                               # 參數組 (與配方內容同格式)


class WorkspaceFromRuns(BaseModel):
    run_ids: List[int]


class WorkspaceFromRecipe(BaseModel):
    recipe_pk: int


class WorkspacePrefetch(BaseModel):
    ids: List[int]                           # 依優先順序 (目前影像、下一張、上一張)


class WorkspaceAnalyze(BaseModel):
    body: Optional[dict] = None              # 同時更新參數組 (避免前端尚未存檔就分析)


class WorkspaceSaveRecipe(BaseModel):
    mode: str                                # revise：存為來源配方的下一版草稿；new：另存為新配方
    recipe_id: str = ""
    name: dict = {}
    overwrite_draft: bool = False


class TrialBody(BaseModel):
    body: dict                               # 配方內容 (可為尚未儲存的編輯內容)
    run_id: int                              # 以該紀錄的影像與拍攝參數試跑


class ModuleValidationBody(BaseModel):
    status: str                  # validated / revoked
    note: str = ""
    report_name: str = ""


class ReviewBody(BaseModel):
    judgment: str
    comment: str = ""


class WatchBody(BaseModel):
    path: str
    recipe_id: str
    recursive: bool = True
    name_rule: str = ""
    import_existing: bool = False


class WatchPatch(BaseModel):
    enabled: Optional[bool] = None
    recipe_id: Optional[str] = None
    name_rule: Optional[str] = None


class DiagBody(BaseModel):
    run_ids: List[int]
    description: str = ""
    include_images: bool = True
    deidentify: bool = False
    encrypt: bool = False
    split_mb: int = Field(2048, ge=10, le=100000)


class LoginBody(BaseModel):
    username: str
    password: str


class SetupBody(BaseModel):
    username: str
    display_name: str = ""
    password: str


class PasswordBody(BaseModel):
    old_password: str
    new_password: str


class UserCreate(BaseModel):
    username: str
    display_name: str = ""
    role: str
    password: str


class UserPatch(BaseModel):
    role: Optional[str] = None
    active: Optional[bool] = None
    display_name: Optional[str] = None


class ResetBody(BaseModel):
    new_password: str


class VersionBody(BaseModel):
    version: str


class SettingsBody(BaseModel):
    retention_days: Optional[int] = None
    disk_warn_gb: Optional[float] = None
    gpu_inference: Optional[bool] = None
    workspace_retention_days: Optional[int] = None


class ModelStatusBody(BaseModel):
    status: str                  # active / retired


class AnnotationBody(BaseModel):
    module_id: str = "void"
    balls: list = []
    voids: list = []
    note: str = ""


class DatasetBody(BaseModel):
    run_ids: list[int]
    deidentify: bool = False
    module_id: str = "void"
    include_images: bool = False


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
def create_app(settings, workers=None, watch=True, start=True, enforce_license=True, hardware_collector=None):
    """enforce_license／hardware_collector 只供開發與自動測試使用"""
    kw = dict(hardware_collector=hardware_collector) if hardware_collector else {}
    plat = Platform(settings, workers=workers, watch=watch, enforce_license=enforce_license, **kw)

    @asynccontextmanager
    async def lifespan(app):
        if start:
            plat.start()
        yield
        if start:
            plat.stop()

    app = FastAPI(title=PRODUCT_NAME, version=__version__, lifespan=lifespan, openapi_url="/api/openapi.json",
                  docs_url="/api/docs", redoc_url=None)
    app.state.platform = plat

    @app.exception_handler(ApiError)
    async def _api_error(request, exc):
        return JSONResponse(status_code=exc.status, content=dict(error=exc.code, detail=exc.detail))

    db = plat.db
    img_cache, img_cache_lock = OrderedDict(), threading.Lock()

    @app.exception_handler(auth.AuthError)
    async def _auth_error(request, exc):
        return JSONResponse(status_code=exc.status, content=dict(error=exc.code, detail=exc.detail))

    def current_user(request: Request):
        u = auth.session_user(db, request.cookies.get(auth.COOKIE))
        if u is None:
            raise ApiError(401, "not_authenticated")
        return u

    def require(perm):
        """權限檢查；回傳操作者帳號 (寫入稽核紀錄)"""
        def dep(u=Depends(current_user)):
            if u["must_change_password"]:
                raise ApiError(403, "password_change_required")
            if not auth.allowed(u["role"], perm):
                raise ApiError(403, "permission_denied", perm)
            return u["username"]
        return dep

    recipes = RecipeStore(db)

    def _recipe_err(e):
        status = 404 if e.code == "recipe_not_found" else 409 if e.code == "recipe_not_draft" else 400
        return ApiError(status, e.code, e.detail)

    # ---- 登入與帳號 ----
    def _set_cookie(resp, token):
        resp.set_cookie(auth.COOKIE, token, httponly=True, samesite="strict", max_age=auth.SESSION_IDLE_SECONDS,
                        path="/")

    @app.get("/api/auth/state")
    def auth_state(request: Request):
        """登入狀態 (不需登入)：是否需要首次設定、目前使用者與權限"""
        u = auth.session_user(db, request.cookies.get(auth.COOKIE))
        lic_summary = None
        if u:
            st = plat.license_status()
            lic_summary = dict(state=st["state"], analysis_allowed=plat.analysis_allowed(),
                               days_left=st.get("days_left"), expires=st.get("expires"), warn=st.get("warn", False),
                               enforced=plat.enforce_license)
        return dict(setup_required=auth.user_count(db) == 0, product=PRODUCT_NAME, version=__version__,
                    user=auth.public_user(u) if u else None, license=lic_summary,
                    permissions=auth.permissions_of(u["role"]) if u and not u["must_change_password"] else [])

    @app.post("/api/auth/setup")
    def auth_setup(b: SetupBody):
        user = auth.setup_first_admin(db, b.username, b.display_name, b.password)
        token, _ = auth.login(db, b.username, b.password)
        resp = JSONResponse(dict(user=user))
        _set_cookie(resp, token)
        return resp

    @app.post("/api/auth/login")
    def auth_login(b: LoginBody):
        token, user = auth.login(db, b.username, b.password)
        resp = JSONResponse(dict(user=user))
        _set_cookie(resp, token)
        return resp

    @app.post("/api/auth/logout")
    def auth_logout(request: Request):
        auth.logout(db, request.cookies.get(auth.COOKIE))
        resp = JSONResponse(dict(ok=True))
        resp.delete_cookie(auth.COOKIE, path="/")
        return resp

    @app.post("/api/auth/password")
    def auth_password(b: PasswordBody, u=Depends(current_user)):
        auth.change_password(db, u["id"], b.old_password, b.new_password)
        return dict(ok=True)

    @app.get("/api/users")
    def list_users(_u: str = Depends(require("user_manage"))):
        return [auth.public_user(u) for u in db.all("SELECT * FROM users ORDER BY id")]

    @app.post("/api/users")
    def create_user(b: UserCreate, who: str = Depends(require("user_manage"))):
        return auth.create_user(db, b.username, b.display_name, b.role, b.password, who, must_change=True)

    @app.patch("/api/users/{uid}")
    def patch_user(uid: int, b: UserPatch, who: str = Depends(require("user_manage"))):
        return auth.update_user(db, uid, who, role=b.role, active=b.active, display_name=b.display_name)

    @app.post("/api/users/{uid}/reset-password")
    def reset_user_password(uid: int, b: ResetBody, who: str = Depends(require("user_manage"))):
        auth.reset_password(db, uid, b.new_password, who)
        return dict(ok=True)

    # ---- 系統 ----
    @app.get("/api/system")
    def system(_u: str = Depends(require("view"))):
        q = {r["status"]: r["n"] for r in db.all("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")}
        return dict(product=PRODUCT_NAME, version=__version__, schema_version=db.schema_version,
                    modules={k: v.version for k, v in plugin.available().items()}, queue=q,
                    workers=plat.queue.workers, locales=list(LOCALES), time=now(),
                    disk=maintenance.disk_status(settings, db), analysis_allowed=plat.analysis_allowed())

    @app.get("/api/i18n/{locale}")
    def i18n(locale: str):
        if locale not in LOCALES:
            raise ApiError(404, "locale_not_found", locale)
        return catalog(locale)

    @app.get("/api/modules")
    def modules(_u: str = Depends(require("view"))):
        status = {m["module_id"]: m["status"] for m in module_validation.overview(db)}
        return [dict(cls.describe(), validation=status.get(mid, "unvalidated"))
                for mid, cls in plugin.available().items()]

    # ---- 標註與訓練資料 ----
    @app.get("/api/runs/{run_id}/annotation")
    def get_annotation(run_id: int, module_id: str = "void", _u: str = Depends(require("view"))):
        try:
            return annotations.get(db, run_id, module_id)
        except annotations.AnnotationError as e:
            raise ApiError(404 if e.code == "run_not_found" else 400, e.code, e.detail)

    @app.put("/api/runs/{run_id}/annotation")
    def put_annotation(run_id: int, b: AnnotationBody, who: str = Depends(require("annotate"))):
        try:
            return annotations.save(db, run_id, b.module_id, dict(balls=b.balls, voids=b.voids), who, b.note)
        except annotations.AnnotationError as e:
            raise ApiError(404 if e.code == "run_not_found" else 400, e.code, e.detail)

    @app.post("/api/annotations/export")
    def export_dataset(b: DatasetBody, who: str = Depends(require("annotate"))):
        try:
            name, data, _stats = annotations.export_dataset(settings, db, b.run_ids, who, b.deidentify, b.module_id,
                                                            b.include_images)
        except annotations.AnnotationError as e:
            raise ApiError(404 if e.code == "run_not_found" else 400, e.code, e.detail)
        return Response(data, media_type="application/zip", headers={"Content-Disposition": f"attachment; filename={name}"})

    # ---- 深度學習模型 ----
    @app.get("/api/models")
    def list_models(module_id: Optional[str] = None, _u: str = Depends(require("view"))):
        return model_store.list_models(db, module_id)

    @app.post("/api/models/import")
    def import_model(file: UploadFile = File(...), who: str = Depends(require("recipe_edit"))):
        d = os.path.join(settings.data_dir, "models", "incoming")
        os.makedirs(d, exist_ok=True)
        dst = os.path.join(d, f"{time.strftime('%Y%m%d_%H%M%S')}_{os.path.basename(file.filename or 'model.xrvmodel')}")
        with open(dst, "wb") as fo:
            shutil.copyfileobj(file.file, fo)
        try:
            return model_store.import_model(settings, db, dst, who)
        except model_store.ModelError as e:
            db.audit(who, "model.rejected", "model", "", file=os.path.basename(dst), reason=e.code)
            raise ApiError(400, e.code, e.detail)
        finally:
            try:
                os.remove(dst)
            except OSError:
                pass

    @app.post("/api/models/{pk}/status")
    def model_status(pk: int, b: ModelStatusBody, who: str = Depends(require("recipe_edit"))):
        try:
            return model_store.set_status(db, pk, b.status, who)
        except model_store.ModelError as e:
            raise ApiError(404 if e.code == "model_not_found" else 400, e.code, e.detail)

    @app.get("/api/modules/validation")
    def modules_validation(_u: str = Depends(require("view"))):
        return module_validation.overview(db)

    @app.post("/api/modules/{module_id}/validation")
    def set_module_validation(module_id: str, b: ModuleValidationBody, who: str = Depends(require("recipe_edit"))):
        try:
            return module_validation.set_status(db, module_id, b.status, who, b.note, b.report_name)
        except module_validation.ModuleValidationError as e:
            raise ApiError(404 if e.code == "unknown_module" else 400, e.code, e.detail)

    # ---- 配方 ----
    @app.get("/api/recipes")
    def list_recipes(include_retired: bool = False, _u: str = Depends(require("view"))):
        return recipes.list(include_retired)

    @app.get("/api/recipes/{pk}")
    def get_recipe(pk: int, _u: str = Depends(require("view"))):
        r = recipes.get(pk)
        if r is None:
            raise ApiError(404, "recipe_not_found", pk)
        return r

    @app.get("/api/recipe-template/{module_id}")
    def recipe_template(module_id: str, _u: str = Depends(require("view"))):
        try:
            cls = plugin.get(module_id)
        except KeyError:
            raise ApiError(404, "unknown_module", module_id)
        params = {p.key: p.default for p in cls.params}
        notice = None
        if cls.template_model_defaults:
            # 範本預設使用模型：帶入最新啟用、任務相符的模型；沒有時維持模組預設並提示
            mparam = next((p for p in cls.params if p.type == "model"), None)
            usable = [m for m in model_store.list_models(db, module_id, include_retired=False)
                      if mparam and (not mparam.choices or m["task"] in mparam.choices)]
            if usable:
                params.update(cls.template_model_defaults)
                params[mparam.key] = max(usable, key=lambda m: m["id"])["ref"]
            else:
                notice = f"{module_id}_model_missing"
        return dict(recipe_id="", version=1, name={"zh-TW": "", "en": ""}, pixel_size_um=None,
                    calibration_profile=None, quality_rules=[], acquisition_limits={},
                    modules=[dict(module_id=module_id, params=params,
                                  judgment={p.key: p.default for p in cls.judgment_params})],
                    _notice=notice)

    @app.post("/api/recipes")
    def create_recipe(b: RecipeBody, who: str = Depends(require("recipe_edit"))):
        try:
            return recipes.create_draft(b.body, who, b.note)
        except RecipeStoreError as e:
            raise _recipe_err(e)

    @app.put("/api/recipes/{pk}")
    def update_recipe(pk: int, b: RecipeBody, who: str = Depends(require("recipe_edit"))):
        try:
            return recipes.update_draft(pk, b.body, who)
        except RecipeStoreError as e:
            raise _recipe_err(e)

    @app.post("/api/recipes/{pk}/revise")
    def revise_recipe(pk: int, who: str = Depends(require("recipe_edit"))):
        try:
            return recipes.revise(pk, who)
        except RecipeStoreError as e:
            raise _recipe_err(e)

    @app.get("/api/recipes/{pk}/diff")
    def recipe_diff(pk: int, _u: str = Depends(require("view"))):
        try:
            return recipes.diff(pk)
        except RecipeStoreError as e:
            raise _recipe_err(e)

    def _scope_images(row, lot_no=""):
        """發布並重新分析的範圍：目前結果使用同一配方代碼其他版本的影像 (可限定批號)"""
        sql = ("SELECT i.*, l.lot_no FROM runs r JOIN images i ON i.id = r.image_id "
               "LEFT JOIN lots l ON l.id = i.lot_id JOIN recipes rc ON rc.id = r.recipe_pk "
               f"WHERE {CURRENT} AND rc.recipe_id = ? AND r.recipe_pk != ?")
        args = [row["recipe_id"], row["id"]]
        if lot_no:
            sql += " AND l.lot_no = ?"
            args.append(lot_no)
        return db.all(sql + " ORDER BY i.id", args)

    @app.get("/api/recipes/{pk}/reanalysis-scope")
    def reanalysis_scope(pk: int, _u: str = Depends(require("view"))):
        row = recipes.get(pk)
        if row is None:
            raise ApiError(404, "recipe_not_found", pk)
        imgs = _scope_images(row)
        lots = {}
        for i in imgs:
            if i["lot_no"]:
                lots[i["lot_no"]] = lots.get(i["lot_no"], 0) + 1
        avg = db.one("SELECT AVG(elapsed_s) AS s FROM (SELECT elapsed_s FROM runs ORDER BY id DESC LIMIT 50)")["s"]
        return dict(total=len(imgs), skipped=sum(1 for i in imgs if image_path(i) is None),
                    image_regions=sum(1 for i in imgs if latest_image_regions(db, i["id"])),
                    lots=[dict(lot_no=k, n=v) for k, v in sorted(lots.items())],
                    avg_elapsed_s=avg, workers=plat.queue.workers)

    @app.post("/api/recipes/{pk}/release")
    def release_recipe(pk: int, b: Optional[ReleaseBody] = None, who: str = Depends(require("recipe_edit"))):
        b = b or ReleaseBody()
        if b.reanalyze not in ("none", "all_previous", "lot"):
            raise ApiError(400, "invalid_request", b.reanalyze)
        row = recipes.get(pk)
        for m in (row or {}).get("body", {}).get("modules", []):
            if not plat.module_allowed(m["module_id"]):
                raise ApiError(403, "module_not_licensed", m["module_id"])
        if b.reanalyze != "none":
            _require_license()
        try:
            out = recipes.release(pk, who)
        except RecipeStoreError as e:
            raise _recipe_err(e)
        if b.reanalyze != "none":
            imgs = _scope_images(out, b.lot_no if b.reanalyze == "lot" else "")
            q = queue_reanalysis(db, [(i["id"], pk) for i in imgs], who, keep_image_regions=b.keep_image_regions)
            db.audit(who, "recipe.release_reanalyze", "recipe", pk, recipe_id=out["recipe_id"], version=out["version"],
                     scope=b.reanalyze, lot_no=b.lot_no, queued=len(q["job_ids"]), skipped=len(q["skipped"]),
                     keep_image_regions=b.keep_image_regions,
                     job_ids=f"{q['job_ids'][0]}-{q['job_ids'][-1]}" if q["job_ids"] else "")
            plat.queue.notify()
            out["reanalysis"] = dict(queued=len(q["job_ids"]), skipped=q["skipped"])
        return out

    @app.post("/api/recipes/trial")
    def trial_recipe(b: TrialBody, who: str = Depends(require("recipe_edit"))):
        """草稿試跑：以尚未儲存的配方內容分析一張影像；結果不寫入紀錄 (PLAN-003 第 7 節)"""
        _require_license()
        body = dict(b.body)
        body["recipe_id"] = str(body.get("recipe_id") or "trial").strip() or "trial"
        body["version"] = body.get("version") or 1
        try:
            recipe = RecipeStore._validate(body)
        except RecipeStoreError as e:
            raise _recipe_err(e)
        for m in recipe.modules:
            if m.enabled and not plat.module_allowed(m.module_id):
                raise ApiError(403, "module_not_licensed", m.module_id)
        r = db.one("SELECT r.image_id, j.acquisition_json FROM runs r JOIN jobs j ON j.id = r.job_id WHERE r.id = ?",
                   (b.run_id,))
        if r is None:
            raise ApiError(404, "run_not_found", b.run_id)
        img = db.one("SELECT * FROM images WHERE id = ?", (r["image_id"],))
        if image_path(img) is None:
            raise ApiError(410, "image_unavailable", img["file_name"])
        payload = build_payload(settings, db, img, recipe.to_dict(), json.loads(r["acquisition_json"] or "{}"), None)
        t0 = time.time()
        out = plat.interactive.run(payload, key=("trial", who))
        db.audit(who, "recipe.trial", "recipe", body["recipe_id"], run_id=b.run_id, image_id=img["id"],
                 ok=bool(out["ok"]), elapsed_s=round(time.time() - t0, 1))
        if not out["ok"]:
            raise ApiError(422, out["error"], out.get("detail", ""))
        return dict(result=out["result"])

    @app.post("/api/recipes/{pk}/retire")
    def retire_recipe(pk: int, who: str = Depends(require("recipe_edit"))):
        try:
            return recipes.retire(pk, who)
        except RecipeStoreError as e:
            raise _recipe_err(e)

    @app.delete("/api/recipes/{pk}")
    def delete_recipe(pk: int, who: str = Depends(require("recipe_edit"))):
        try:
            recipes.delete_draft(pk, who)
        except RecipeStoreError as e:
            raise _recipe_err(e)
        return dict(ok=True)

    # ---- 匯入與工作 ----
    def _require_license():
        if not plat.analysis_allowed():
            raise ApiError(403, f"license_{plat.license_status()['state']}")

    def _import(path, recipe_pk, who, lot_no, acq, source):
        try:
            r = import_image(settings, db, path, recipe_pk, who, lot_no=lot_no,
                             sample_no=os.path.splitext(os.path.basename(path))[0],
                             acquisition_manual=acquisition.parse_manual(acq) or None, source=source)
        except ImportFailed as e:
            return dict(file=os.path.basename(path), error=e.code, detail=e.detail)
        return dict(file=os.path.basename(path), **r)

    @app.post("/api/imports")
    def upload_images(files: List[UploadFile] = File(...), recipe_pk: int = Form(...), lot_no: str = Form(""),
                            acquisition_text: str = Form("", alias="acquisition"), who: str = Depends(require("import"))):
        _require_license()
        out = []
        day_dir = os.path.join(settings.uploads_dir, time.strftime("%Y%m%d"))
        os.makedirs(day_dir, exist_ok=True)
        for f in files:
            name = os.path.basename(f.filename or "upload")
            if not name.lower().endswith(IMAGE_EXTENSIONS):
                out.append(dict(file=name, error="unsupported_format"))
                continue
            dst = os.path.join(day_dir, f"{time.strftime('%H%M%S')}_{name}")
            with open(dst, "wb") as fo:
                shutil.copyfileobj(f.file, fo)
            out.append(_import(dst, recipe_pk, who, lot_no, acquisition_text, "upload"))
        plat.queue.notify()
        return out

    @app.post("/api/imports/path")
    def import_paths(b: PathImport, who: str = Depends(require("import_path"))):
        _require_license()
        out = [_import(p, b.recipe_pk, who, b.lot_no, b.acquisition, "manual") for p in b.paths]
        plat.queue.notify()
        return out

    @app.get("/api/jobs")
    def list_jobs(status: Optional[str] = None, limit: int = Query(100, le=1000), _u: str = Depends(require("view"))):
        where, args = ("WHERE j.status = ?", [status]) if status else ("", [])
        return db.all(f"SELECT j.*, i.file_name FROM jobs j JOIN images i ON i.id = j.image_id {where} "
                      f"ORDER BY j.id DESC LIMIT ?", (*args, limit))

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: int, who: str = Depends(require("import"))):
        if not plat.queue.cancel(job_id, who):
            raise ApiError(409, "job_not_cancellable", job_id)
        return dict(ok=True)

    @app.post("/api/jobs/{job_id}/retry")
    def retry_job(job_id: int, who: str = Depends(require("import"))):
        if not plat.queue.retry(job_id, who):
            raise ApiError(409, "job_not_retryable", job_id)
        return dict(ok=True)

    @app.post("/api/images/{image_id}/reanalyze")
    def reanalyze(image_id: int, b: Reanalyze, who: str = Depends(require("import"))):
        _require_license()
        img = db.one("SELECT * FROM images WHERE id = ?", (image_id,))
        if img is None:
            raise ApiError(404, "image_not_found", image_id)
        rc = recipes.get(b.recipe_pk)
        if rc is None or rc["status"] != "released":
            raise ApiError(400, "recipe_not_released", b.recipe_pk)
        q = queue_reanalysis(db, [(image_id, b.recipe_pk)], who)
        if not q["job_ids"]:
            raise ApiError(410, "image_unavailable", img["file_name"])
        db.audit(who, "image.reanalyze", "image", image_id, job_id=q["job_ids"][0], recipe_pk=b.recipe_pk)
        plat.queue.notify()
        return dict(job_id=q["job_ids"][0])

    @app.post("/api/runs/reanalyze")
    def reanalyze_runs(b: BatchReanalyze, who: str = Depends(require("import"))):
        """批次重新分析 (紀錄頁勾選)；同一影像只建立一個工作"""
        _require_license()
        if b.recipe_pk is not None:
            rc = recipes.get(b.recipe_pk)
            if rc is None or rc["status"] != "released":
                raise ApiError(400, "recipe_not_released", b.recipe_pk)
        items, no_recipe = [], []
        for rid in b.run_ids:
            r = db.one("SELECT r.image_id, rc.recipe_id, i.file_name FROM runs r JOIN recipes rc ON rc.id = r.recipe_pk "
                       "JOIN images i ON i.id = r.image_id WHERE r.id = ?", (rid,))
            if r is None:
                continue
            pk = b.recipe_pk
            if pk is None:
                latest = recipes.latest_released(r["recipe_id"])
                if latest is None:
                    no_recipe.append(r["file_name"])
                    continue
                pk = latest["id"]
            items.append((r["image_id"], pk))
        q = queue_reanalysis(db, items, who, keep_image_regions=b.keep_image_regions)
        db.audit(who, "runs.reanalyze", "run", "", runs=len(b.run_ids), queued=len(q["job_ids"]),
                 skipped=len(q["skipped"]), recipe_pk=b.recipe_pk, keep_image_regions=b.keep_image_regions)
        plat.queue.notify()
        return dict(queued=len(q["job_ids"]), skipped=q["skipped"], no_recipe=no_recipe)

    @app.get("/api/jobs/reanalysis")
    def reanalysis_progress(_u: str = Depends(require("view"))):
        """進行中的重新分析批次：從最早一筆未完成的重新分析工作起算"""
        m = db.one("SELECT MIN(id) AS m FROM jobs WHERE source = 'reanalyze' AND status IN ('queued', 'running')")["m"]
        if m is None:
            return dict(active=False)
        counts = {x["status"]: x["n"] for x in db.all(
            "SELECT status, COUNT(*) AS n FROM jobs WHERE source = 'reanalyze' AND id >= ? GROUP BY status", (m,))}
        return dict(active=True, total=sum(counts.values()), **counts)

    @app.post("/api/jobs/reanalysis/cancel")
    def cancel_reanalysis(who: str = Depends(require("import"))):
        return dict(cancelled=plat.queue.cancel_queued(who, source="reanalyze"))

    # ---- 分析紀錄 ----
    RUN_SELECT = ("SELECT r.id, r.created_at, r.quality_level, r.reference_only, r.auto_judgment, r.final_judgment, "
                  "r.summary_json, r.elapsed_s, r.software_version, r.image_id, r.job_id, i.file_name, i.sample_no, "
                  "i.kind, i.width, i.height, l.lot_no, rc.recipe_id, rc.version AS recipe_version, r.recipe_pk, "
                  "(SELECT MAX(r2.id) FROM runs r2 WHERE r2.image_id = r.image_id) AS latest_run_id, "
                  "(SELECT j.regions_json IS NOT NULL FROM jobs j WHERE j.id = r.job_id) AS image_regions "
                  "FROM runs r JOIN images i ON i.id = r.image_id LEFT JOIN lots l ON l.id = i.lot_id "
                  "JOIN recipes rc ON rc.id = r.recipe_pk ")

    def _run_row(r):
        r = dict(r)
        r["summary"] = json.loads(r.pop("summary_json"))
        r["reference_only"] = bool(r["reference_only"])
        r["image_regions"] = bool(r["image_regions"])
        latest = r.pop("latest_run_id")
        r["superseded_by"] = latest if latest != r["id"] else None     # 已被同一影像較新的紀錄取代
        return r

    @app.get("/api/runs")
    def list_runs(judgment: Optional[str] = None, lot_no: Optional[str] = None, recipe_id: Optional[str] = None,
                  date_from: Optional[str] = None, date_to: Optional[str] = None, current_only: bool = True,
                  limit: int = Query(100, le=1000), offset: int = 0, _u: str = Depends(require("view"))):
        cond, args = ([CURRENT] if current_only else []), []
        for col, v in (("r.final_judgment = ?", judgment), ("l.lot_no = ?", lot_no), ("rc.recipe_id = ?", recipe_id),
                       ("r.created_at >= ?", date_from), ("r.created_at <= ?", date_to)):
            if v:
                cond.append(col)
                args.append(v)
        where = ("WHERE " + " AND ".join(cond)) if cond else ""
        total = db.one(f"SELECT COUNT(*) AS n FROM runs r JOIN images i ON i.id = r.image_id "
                       f"LEFT JOIN lots l ON l.id = i.lot_id JOIN recipes rc ON rc.id = r.recipe_pk {where}", args)["n"]
        rows = db.all(RUN_SELECT + where + " ORDER BY r.id DESC LIMIT ? OFFSET ?", (*args, limit, offset))
        return dict(total=total, items=[_run_row(r) for r in rows])

    @app.get("/api/runs/export.csv")
    def export_runs_csv(judgment: Optional[str] = None, lot_no: Optional[str] = None, recipe_id: Optional[str] = None,
                        date_from: Optional[str] = None, date_to: Optional[str] = None, current_only: bool = True,
                        locale: str = "zh-TW", _u: str = Depends(require("view"))):
        import csv
        import io
        from ..i18n import t
        rows = list_runs(judgment, lot_no, recipe_id, date_from, date_to, current_only, limit=1000000, offset=0,
                         _u=_u)["items"]
        cols = ["id", "created_at", "lot_no", "sample_no", "file_name", "recipe_id", "recipe_version", "kind",
                "quality_level", "auto_judgment", "final_judgment", "module", "die_shift_dx_px", "die_shift_dy_px",
                "die_shift_se_px", "die_shift_dx_um", "die_shift_dy_um", "sites_used", "software_version"]
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(cols)
        for r in rows:
            for mid, m in (r["summary"].get("modules") or {"": {}}).items():
                s = (m or {}).get("summary") or {}
                d = s.get("die_shift") or {}
                w.writerow([r["id"], r["created_at"], r["lot_no"] or "", r["sample_no"], r["file_name"], r["recipe_id"],
                            r["recipe_version"], r["kind"], t(f"quality.{r['quality_level']}", locale),
                            t(f"judgment.{r['auto_judgment']}", locale), t(f"judgment.{r['final_judgment']}", locale),
                            mid, d.get("dx", ""), d.get("dy", ""), d.get("se", ""), d.get("dx_um", ""),
                            d.get("dy_um", ""), s.get("sites_used", ""), r["software_version"]])
        return Response(("﻿" + buf.getvalue()).encode("utf-8"), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename=runs_{time.strftime('%Y%m%d_%H%M%S')}.csv"})

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: int, _u: str = Depends(require("view"))):
        r = db.one(RUN_SELECT + "WHERE r.id = ?", (run_id,))
        if r is None:
            raise ApiError(404, "run_not_found", run_id)
        row = db.one("SELECT result_path FROM runs WHERE id = ?", (run_id,))
        with open(row["result_path"], encoding="utf-8") as f:
            result = json.load(f)
        reviews = db.all("SELECT * FROM reviews WHERE run_id = ? ORDER BY id", (run_id,))
        # 分析歷程：同一影像的所有紀錄 (新到舊)，附各筆的人工複判供參考
        history = db.all("SELECT r.id, r.created_at, r.auto_judgment, r.final_judgment, r.quality_level, "
                         "rc.recipe_id, rc.version AS recipe_version, j.regions_json IS NOT NULL AS image_regions "
                         "FROM runs r JOIN recipes rc ON rc.id = r.recipe_pk JOIN jobs j ON j.id = r.job_id "
                         "WHERE r.image_id = ? ORDER BY r.id DESC", (r["image_id"],))
        for h in history:
            h["image_regions"] = bool(h["image_regions"])
            h["reviews"] = db.all("SELECT judgment, comment, reviewer, created_at FROM reviews WHERE run_id = ? "
                                  "ORDER BY id", (h["id"],))
        return dict(run=_run_row(r), result=result, reviews=reviews, history=history)

    @app.get("/api/runs/{run_id}/image")
    def run_image(run_id: int, max_size: int = Query(2048, ge=256, le=8192), low: float = 0.5, high: float = 99.5, _u: str = Depends(require("view"))):
        r = db.one("SELECT i.archive_path, i.original_path FROM runs r JOIN images i ON i.id = r.image_id "
                   "WHERE r.id = ?", (run_id,))
        if r is None:
            raise ApiError(404, "run_not_found", run_id)
        path = r["archive_path"] if r["archive_path"] and os.path.isfile(r["archive_path"]) else r["original_path"]
        return _image_png(path, max_size, low, high)

    def _image_png(path, max_size, low, high):
        """影像轉顯示用 PNG (長邊縮至 max_size)；伺服器快取最近幾張"""
        if not os.path.isfile(path):
            raise ApiError(410, "image_unavailable", os.path.basename(path))
        key = (path, os.path.getmtime(path), max_size, low, high)
        with img_cache_lock:
            hit = img_cache.get(key)
            if hit is not None:
                img_cache.move_to_end(key)
        if hit is not None:
            return Response(hit[0], media_type="image/png", headers={"X-Image-Scale": f"{hit[1]:.6f}",
                                                                     "Cache-Control": "private, max-age=3600"})
        try:
            img = load_image(path)
        except ImageFormatError as e:
            raise ApiError(410, e.code, os.path.basename(path))
        disp = to_display(img.pixels.astype(np.float32), low, high)
        h, w = disp.shape
        s = min(1.0, max_size / max(h, w))
        if s < 1.0:
            disp = cv2.resize(disp, (int(round(w * s)), int(round(h * s))), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".png", disp)
        with img_cache_lock:
            img_cache[key] = (buf.tobytes(), s)
            while len(img_cache) > IMG_CACHE_ITEMS:
                img_cache.popitem(last=False)
        return Response(buf.tobytes(), media_type="image/png", headers={"X-Image-Scale": f"{s:.6f}",
                                                                         "Cache-Control": "private, max-age=3600"})

    # ---- 本影像自訂檢測區域 (PLAN-004 第 6 節) ----
    def _run_recipe(run_id):
        r = db.one("SELECT r.image_id, r.recipe_pk, j.acquisition_json FROM runs r JOIN jobs j ON j.id = r.job_id "
                   "WHERE r.id = ?", (run_id,))
        if r is None:
            raise ApiError(404, "run_not_found", run_id)
        img = db.one("SELECT * FROM images WHERE id = ?", (r["image_id"],))
        if image_path(img) is None:
            raise ApiError(410, "image_unavailable", img["file_name"])
        try:
            recipe = recipes.to_recipe(recipes.get(r["recipe_pk"]))
        except RecipeStoreError as e:
            raise _recipe_err(e)
        return r, img, recipe

    def _norm_regions(d):
        try:
            return regions_mod.normalize(d) if d else None
        except regions_mod.RegionError as e:
            raise ApiError(400, "invalid_regions", str(e))

    @app.post("/api/runs/{run_id}/regions/trial")
    def trial_image_regions(run_id: int, b: RegionsBody, who: str = Depends(require("image_regions"))):
        """以同一配方版本＋自訂檢測區域試跑本影像；不產生紀錄"""
        _require_license()
        reg = _norm_regions(b.regions)
        r, img, recipe = _run_recipe(run_id)
        payload = build_payload(settings, db, img, recipe.to_dict(), json.loads(r["acquisition_json"] or "{}"), None,
                                image_regions=reg)
        out = plat.interactive.run(payload, key=("regions", who))
        db.audit(who, "run.regions_trial", "run", run_id, image_id=img["id"], ok=bool(out["ok"]))
        if not out["ok"]:
            raise ApiError(422, out["error"], out.get("detail", ""))
        return dict(result=out["result"])

    @app.post("/api/runs/{run_id}/regions")
    def apply_image_regions(run_id: int, b: RegionsBody, who: str = Depends(require("image_regions"))):
        """套用自訂檢測區域並重新分析 (regions 為 None 時改回配方區域)；新紀錄成為本影像的目前結果"""
        _require_license()
        reg = _norm_regions(b.regions)
        r, img, _recipe = _run_recipe(run_id)
        rc = recipes.get(r["recipe_pk"])
        if rc["status"] != "released":
            raise ApiError(400, "recipe_not_released", f"{rc['recipe_id']} v{rc['version']}")
        q = queue_reanalysis(db, [(img["id"], r["recipe_pk"])], who, source="regions", regions_override=reg or {})
        if not q["job_ids"]:
            raise ApiError(410, "image_unavailable", img["file_name"])
        db.audit(who, "run.regions_override", "run", run_id, image_id=img["id"], job_id=q["job_ids"][0],
                 recipe_id=rc["recipe_id"], recipe_version=rc["version"], regions=reg)
        plat.queue.notify()
        return dict(job_id=q["job_ids"][0])

    # ---- 手動檢測工作區 (PLAN-004 第 4 節) ----
    ws_batches, ws_batch_lock = {}, threading.Lock()

    def _ws(who):
        return Workspace(settings, who)

    def _ws_err(e):
        status = 404 if e.code in ("workspace_image_not_found", "run_not_found") else \
            410 if e.code == "image_unavailable" else 413 if e.code in ("workspace_full", "workspace_too_large") else 400
        return ApiError(status, e.code, e.detail)

    def _ws_recipe(params):
        """參數組 → 已驗證的 pipeline.Recipe (手動檢測不屬於任何配方)"""
        if not params:
            raise ApiError(400, "workspace_no_params")
        try:
            recipe = RecipeStore._validate(ws_mod.analysis_body(params))
        except RecipeStoreError as e:
            raise _recipe_err(e)
        for m in recipe.modules:
            if m.enabled and not plat.module_allowed(m.module_id):
                raise ApiError(403, "module_not_licensed", m.module_id)
        return recipe

    def _ws_analyze_one(who, ws, item, recipe, h):
        if not os.path.isfile(item["path"]):
            return dict(ok=False, error="image_unavailable", detail=item["name"])
        payload = build_payload(settings, db, None, recipe.to_dict(), item.get("acquisition") or {}, None,
                                path=item["path"])
        payload.update(manual=True, overlay_path=ws.overlay_path(item["id"]))
        os.makedirs(os.path.dirname(payload["overlay_path"]), exist_ok=True)
        out = plat.interactive.run(payload, key=(who, item["id"]))
        if out["ok"]:
            out["summary"] = ws.record_result(item["id"], h, out["result"])
        return out

    def _ws_batch_state(who):
        with ws_batch_lock:
            st = ws_batches.get(who)
            return dict(st) if st else None

    @app.get("/api/workspace")
    def workspace_view(who: str = Depends(require("manual_inspect"))):
        out = _ws(who).view()
        out["batch"] = _ws_batch_state(who)
        out["waiting"] = plat.interactive.waiting()
        out["analysis_allowed"] = plat.analysis_allowed()
        return out

    @app.post("/api/workspace/images")
    def workspace_upload(files: List[UploadFile] = File(...), who: str = Depends(require("manual_inspect"))):
        """上傳影像 (可一併上傳同名拍攝參數檔 .json／.txt／.ini)"""
        ws = _ws(who)
        sidecars, images = {}, []
        for f in files:
            name = os.path.basename(f.filename or "upload")
            if name.lower().endswith(ws_mod.SIDECAR_EXTENSIONS):
                sidecars[name] = f.file.read(1 << 20)
            else:
                images.append((name, f))
        added, errors = [], []
        for name, f in images:
            stem = os.path.splitext(name)[0]
            try:
                it = ws.add_upload(name, f.file, {k: v for k, v in sidecars.items() if os.path.splitext(k)[0] == stem})
                added.append(it["id"])
            except WorkspaceError as e:
                errors.append(dict(file=name, error=e.code))
        if added:
            db.audit(who, "workspace.add_images", "workspace", who, source="upload", count=len(added))
        return dict(added=added, errors=errors)

    @app.post("/api/workspace/images/from-runs")
    def workspace_from_runs(b: WorkspaceFromRuns, who: str = Depends(require("manual_inspect"))):
        ws = _ws(who)
        added, skipped, errors = [], 0, []
        for rid in b.run_ids:
            try:
                it = ws.add_from_run(db, rid, image_path)
            except WorkspaceError as e:
                errors.append(dict(run_id=rid, error=e.code))
                if e.code in ("workspace_full",):
                    break
                continue
            if it is None:
                skipped += 1
            else:
                added.append(it["id"])
        if added:
            db.audit(who, "workspace.add_images", "workspace", who, source="runs", count=len(added))
        return dict(added=added, skipped=skipped, errors=errors)

    @app.delete("/api/workspace/images/{item_id}")
    def workspace_remove(item_id: int, who: str = Depends(require("manual_inspect"))):
        try:
            _ws(who).remove(item_id)
        except WorkspaceError as e:
            raise _ws_err(e)
        return dict(ok=True)

    @app.delete("/api/workspace")
    def workspace_clear(who: str = Depends(require("manual_inspect"))):
        with ws_batch_lock:
            st = ws_batches.get(who)
            if st and st["running"]:
                st["cancel"] = True
        _ws(who).clear()
        db.audit(who, "workspace.clear", "workspace", who)
        return dict(ok=True)

    @app.get("/api/workspace/images/{item_id}/image")
    def workspace_image(item_id: int, max_size: int = Query(2048, ge=256, le=8192), low: float = 0.5,
                        high: float = 99.5, who: str = Depends(require("manual_inspect"))):
        try:
            it = _ws(who).item(item_id)
        except WorkspaceError as e:
            raise _ws_err(e)
        return _image_png(it["path"], max_size, low, high)

    @app.get("/api/workspace/images/{item_id}/result")
    def workspace_result(item_id: int, who: str = Depends(require("manual_inspect"))):
        ws = _ws(who)
        try:
            ws.item(item_id)
        except WorkspaceError as e:
            raise _ws_err(e)
        res = ws.get_result(item_id)
        if res is None:
            raise ApiError(404, "workspace_no_result", item_id)
        return res

    @app.put("/api/workspace/params")
    def workspace_params(b: WorkspaceParams, who: str = Depends(require("manual_inspect"))):
        try:
            d = _ws(who).set_params(b.body)
        except WorkspaceError as e:
            raise _ws_err(e)
        return dict(params_hash=ws_mod.params_hash(d["params"]))

    @app.post("/api/workspace/params/from-recipe")
    def workspace_from_recipe(b: WorkspaceFromRecipe, who: str = Depends(require("manual_inspect"))):
        """由配方版本帶入參數組 (覆蓋目前參數)；記錄來源供差異標示與另存"""
        row = recipes.get(b.recipe_pk)
        if row is None:
            raise ApiError(404, "recipe_not_found", b.recipe_pk)
        body = dict(row["body"], modules=[{k: v for k, v in m.items() if k != "module_version"}
                                          for m in row["body"]["modules"]])
        src = dict(recipe_pk=row["id"], recipe_id=row["recipe_id"], version=row["version"], status=row["status"],
                   name=row["name"], body=body)
        _ws(who).set_params(body, source=src)
        db.audit(who, "workspace.load_recipe", "workspace", who, recipe_id=row["recipe_id"], version=row["version"])
        return dict(params=body, source=src)

    @app.post("/api/workspace/images/{item_id}/analyze")
    def workspace_analyze(item_id: int, b: Optional[WorkspaceAnalyze] = None, who: str = Depends(require("manual_inspect"))):
        """以目前參數組分析一張影像 (同步)；結果不寫入正式紀錄"""
        _require_license()
        ws = _ws(who)
        try:
            if b and b.body is not None:
                ws.set_params(b.body)
            d = ws.load()
            it = ws.item(item_id, d)
        except WorkspaceError as e:
            raise _ws_err(e)
        recipe = _ws_recipe(d["params"])
        h = ws_mod.params_hash(d["params"])
        t0 = time.time()
        out = _ws_analyze_one(who, ws, it, recipe, h)
        db.audit(who, "workspace.analyze", "workspace", who, image=it["name"], params_hash=h, ok=bool(out["ok"]),
                 elapsed_s=round(time.time() - t0, 1))
        if not out["ok"]:
            raise ApiError(410 if out["error"] == "image_unavailable" else 422, out["error"], out.get("detail", ""))
        return dict(result=out["result"], summary=out["summary"], params_hash=h)

    @app.post("/api/workspace/prefetch")
    def workspace_prefetch(b: WorkspacePrefetch, who: str = Depends(require("manual_inspect"))):
        """背景預先載入影像並做與參數無關的準備 (最多 3 張)；不產生結果、不寫稽核。授權不可分析或參數無效時略過"""
        if not plat.analysis_allowed():
            return dict(queued=0)
        ws = _ws(who)
        d = ws.load()
        try:
            recipe = _ws_recipe(d["params"])
        except ApiError:
            return dict(queued=0)
        items = {it["id"]: it for it in d["images"]}
        payloads = []
        for i in b.ids[:3]:
            it = items.get(i)
            if it and os.path.isfile(it["path"]):
                payloads.append((i, build_payload(settings, db, None, recipe.to_dict(), {}, None, path=it["path"])))
        return dict(queued=plat.interactive.prefetch(payloads, who))

    @app.post("/api/workspace/analyze-all")
    def workspace_analyze_all(b: Optional[WorkspaceAnalyze] = None, who: str = Depends(require("manual_inspect"))):
        """依清單順序逐張分析 (背景執行，可取消)；已有相同參數結果的影像略過"""
        _require_license()
        ws = _ws(who)
        if b and b.body is not None:
            try:
                ws.set_params(b.body)
            except WorkspaceError as e:
                raise _ws_err(e)
        d = ws.load()
        recipe = _ws_recipe(d["params"])
        h = ws_mod.params_hash(d["params"])
        todo = [it for it in d["images"] if not (it.get("result") and it["result"].get("hash") == h)]
        with ws_batch_lock:
            st = ws_batches.get(who)
            if st and st["running"]:
                raise ApiError(409, "workspace_batch_running")
            st = ws_batches[who] = dict(running=True, cancel=False, total=len(todo), done=0, failed=0, current=None,
                                        params_hash=h, started_at=now())

        def work():
            try:
                for it in todo:
                    with ws_batch_lock:
                        if st["cancel"]:
                            break
                        st["current"] = it["id"]
                    try:
                        out = _ws_analyze_one(who, ws, it, recipe, h)
                    except Exception as e:                        # noqa: BLE001  單張失敗不中斷整批
                        out = dict(ok=False, error="analysis_exception", detail=repr(e))
                    with ws_batch_lock:
                        st["done"] += 1
                        if not out["ok"]:
                            st["failed"] += 1
            finally:
                with ws_batch_lock:
                    st.update(running=False, current=None, finished_at=now())

        db.audit(who, "workspace.analyze_all", "workspace", who, count=len(todo), params_hash=h)
        threading.Thread(target=work, name=f"workspace-{who}", daemon=True).start()
        return dict(total=len(todo))

    @app.post("/api/workspace/analyze-all/cancel")
    def workspace_cancel_all(who: str = Depends(require("manual_inspect"))):
        with ws_batch_lock:
            st = ws_batches.get(who)
            if st and st["running"]:
                st["cancel"] = True
        return dict(ok=True)

    @app.post("/api/workspace/save-recipe")
    def workspace_save_recipe(b: WorkspaceSaveRecipe, who: str = Depends(require("recipe_edit"))):
        """另存為配方草稿：revise = 來源配方的下一版草稿；new = 新配方 (之後依正常流程審閱、發布)"""
        ws = _ws(who)
        d = ws.load()
        _ws_recipe(d["params"])
        body = dict(d["params"])
        body["modules"] = [{k: v for k, v in m.items() if k != "module_version"} for m in body.get("modules", [])]
        try:
            if b.mode == "revise":
                src = d.get("source")
                row = recipes.get(src["recipe_pk"]) if src else None
                if row is None:
                    raise ApiError(400, "workspace_no_source")
                draft = db.one("SELECT id, version FROM recipes WHERE recipe_id = ? AND status = 'draft' "
                               "ORDER BY version DESC LIMIT 1", (row["recipe_id"],))
                if draft and not b.overwrite_draft:
                    raise ApiError(409, "draft_exists", f"{row['recipe_id']} v{draft['version']}")
                target = recipes.revise(row["id"], who)
                out = recipes.update_draft(target["id"], dict(body, name=row["name"]), who)
            elif b.mode == "new":
                rid = b.recipe_id.strip()
                if not rid:
                    raise ApiError(400, "invalid_recipe", "recipe_id")
                if db.one("SELECT 1 AS x FROM recipes WHERE recipe_id = ?", (rid,)):
                    raise ApiError(409, "recipe_id_exists", rid)
                out = recipes.create_draft(dict(body, recipe_id=rid, name=b.name or {}), who, note="manual")
            else:
                raise ApiError(400, "invalid_request", b.mode)
        except RecipeStoreError as e:
            raise _recipe_err(e)
        db.audit(who, "workspace.save_recipe", "recipe", out["id"], recipe_id=out["recipe_id"], version=out["version"],
                 mode=b.mode)
        return out

    @app.get("/api/workspace/export")
    def workspace_export(locale: str = "zh-TW", who: str = Depends(require("manual_inspect"))):
        """匯出 ZIP：結果 JSON、疊圖、結果總表 CSV、參數組；標示為手動檢測 (非正式結果)"""
        import csv
        import io
        import zipfile
        from ..i18n import t
        ws = _ws(who)
        d = ws.load()
        h = ws_mod.params_hash(d["params"]) if d["params"] else None
        os.makedirs(settings.exports_dir, exist_ok=True)
        name = f"manual_inspection_{time.strftime('%Y%m%d_%H%M%S')}.zip"
        path = os.path.join(settings.exports_dir, name)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["file_name", "source", "kind", "width", "height", "params_current", "quality", "judgment", "module",
                    "die_shift_dx_px", "die_shift_dy_px", "die_shift_se_px", "die_shift_dx_um", "die_shift_dy_um",
                    "sites_used", "analyzed_at"])
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("README.txt", t("ui.manual.export_readme", locale) + "\n")
            z.writestr("params.json", json.dumps(dict(params=d["params"], source={k: v for k, v in (d["source"] or {}).items()
                                                                                    if k != "body"} or None,
                                                      params_hash=h), ensure_ascii=False, indent=1))
            used = set()
            for it in d["images"]:
                r = it.get("result")
                stem = os.path.splitext(it["name"])[0]
                while stem in used:
                    stem += "_"
                used.add(stem)
                if r:
                    res = ws.get_result(it["id"])
                    if res is not None:
                        z.writestr(f"results/{stem}.json", json.dumps(res, ensure_ascii=False, indent=1))
                    if os.path.isfile(ws.overlay_path(it["id"])):
                        z.write(ws.overlay_path(it["id"]), f"overlays/{stem}.jpg")
                mods = ((r or {}).get("summary") or {}).get("modules") or {"": {}}
                for mid, m in mods.items():
                    s_ = (m or {}).get("summary") or {}
                    dd = s_.get("die_shift") or {}
                    w.writerow([it["name"], it["source"], it["kind"], it["width"], it["height"],
                                "" if not r else ("yes" if r.get("hash") == h else "no"),
                                t(f"quality.{r['quality']}", locale) if r else "",
                                t(f"judgment.{r['judgment']}", locale) if r else "", mid, dd.get("dx", ""),
                                dd.get("dy", ""), dd.get("se", ""), dd.get("dx_um", ""), dd.get("dy_um", ""),
                                s_.get("sites_used", ""), r.get("analyzed_at", "") if r else ""])
            z.writestr("summary.csv", ("﻿" + buf.getvalue()).encode("utf-8"))
        db.audit(who, "workspace.export", "workspace", who, file=name, images=len(d["images"]))
        return FileResponse(path, media_type="application/zip", filename=name)

    @app.post("/api/runs/{run_id}/review")
    def review(run_id: int, b: ReviewBody, who: str = Depends(require("review"))):
        if b.judgment not in REVIEW_JUDGMENTS:
            raise ApiError(400, "invalid_judgment", b.judgment)
        r = db.one("SELECT final_judgment FROM runs WHERE id = ?", (run_id,))
        if r is None:
            raise ApiError(404, "run_not_found", run_id)
        with db.transaction() as c:
            c.execute("INSERT INTO reviews (run_id, judgment, comment, reviewer, created_at) VALUES (?, ?, ?, ?, ?)",
                      (run_id, b.judgment, b.comment, who, now()))
            c.execute("UPDATE runs SET final_judgment = ? WHERE id = ?", (b.judgment, run_id))
        db.audit(who, "run.review", "run", run_id, before=r["final_judgment"], after=b.judgment, comment=b.comment)
        return dict(ok=True)

    @app.get("/api/lots")
    def lots(limit: int = Query(200, le=2000), _u: str = Depends(require("view"))):
        return db.all("SELECT l.*, COUNT(i.id) AS images FROM lots l LEFT JOIN images i ON i.lot_id = l.id "
                      "GROUP BY l.id ORDER BY l.id DESC LIMIT ?", (limit,))

    @app.get("/api/stats")
    def stats(days: int = Query(30, ge=1, le=3650), _u: str = Depends(require("view"))):
        since = time.strftime("%Y-%m-%dT00:00:00", time.localtime(time.time() - (days - 1) * 86400))
        # 只計各影像的目前結果；日期依影像匯入時間，重新分析不會把舊影像算進今天
        base = f"FROM runs r JOIN images i ON i.id = r.image_id WHERE {CURRENT} AND i.imported_at >= ? "
        by_day = db.all("SELECT substr(i.imported_at, 1, 10) AS day, r.final_judgment AS judgment, COUNT(*) AS n "
                        + base + "GROUP BY day, judgment ORDER BY day", (since,))
        totals = db.all("SELECT r.final_judgment AS judgment, COUNT(*) AS n " + base + "GROUP BY judgment", (since,))
        pending = db.one(f"SELECT COUNT(*) AS n FROM runs r WHERE {CURRENT} AND r.final_judgment = ?",
                         (JUDGE_REVIEW,))["n"]
        return dict(since=since, by_day=by_day, totals=totals, review_pending=pending)

    # ---- 資料夾監看 ----
    @app.get("/api/watch-folders")
    def watch_folders(_u: str = Depends(require("view"))):
        rows = db.all("SELECT * FROM watch_folders ORDER BY id")
        for r in rows:
            r["counts"] = {x["state"]: x["n"] for x in db.all(
                "SELECT state, COUNT(*) AS n FROM watch_seen WHERE folder_id = ? GROUP BY state", (r["id"],))}
        return rows

    @app.post("/api/watch-folders")
    def add_watch(b: WatchBody, who: str = Depends(require("watch_manage"))):
        try:
            fid = add_folder(db, b.path, b.recipe_id, who, b.recursive, b.name_rule, b.import_existing)
        except WatchError as e:
            raise ApiError(400, e.code, e.detail)
        return db.one("SELECT * FROM watch_folders WHERE id = ?", (fid,))

    @app.patch("/api/watch-folders/{fid}")
    def patch_watch(fid: int, b: WatchPatch, who: str = Depends(require("watch_manage"))):
        cur = db.one("SELECT * FROM watch_folders WHERE id = ?", (fid,))
        if cur is None:
            raise ApiError(404, "watch_folder_not_found", fid)
        changes = {k: v for k, v in b.model_dump().items() if v is not None}
        if "recipe_id" in changes and recipes.latest_released(changes["recipe_id"]) is None:
            raise ApiError(400, "recipe_not_released", changes["recipe_id"])
        for k, v in changes.items():
            db.execute(f"UPDATE watch_folders SET {k} = ? WHERE id = ?", (int(v) if isinstance(v, bool) else v, fid))
        db.audit(who, "watch.update", "watch_folder", fid, **changes)
        return db.one("SELECT * FROM watch_folders WHERE id = ?", (fid,))

    @app.post("/api/watch-folders/scan")
    def scan_now(_u: str = Depends(require("watch_manage"))):
        jobs = plat.watcher.scan_all() if plat.watcher else []
        return dict(jobs=jobs)

    # ---- 問題回報包 ----
    @app.post("/api/diagnostics")
    def export_diag(b: DiagBody, who: str = Depends(require("diagnostics"))):
        try:
            r = diagnostics.export(settings, db, b.run_ids, who, b.description, b.include_images, b.deidentify,
                                   b.encrypt, b.split_mb)
        except diagnostics.DiagnosticsError as e:
            raise ApiError(400, e.code, e.detail)
        return dict(name=r["name"], sha256=r["sha256"], size=r["size"], parts=[os.path.basename(p) for p in r["files"]])

    @app.get("/api/diagnostics")
    def list_diag(_u: str = Depends(require("diagnostics"))):
        return db.all("SELECT * FROM diagnostic_exports ORDER BY id DESC LIMIT 200")

    @app.get("/api/diagnostics/files/{name}")
    def download_diag(name: str, _u: str = Depends(require("diagnostics"))):
        if os.path.basename(name) != name or not name.startswith("diag_"):
            raise ApiError(400, "invalid_file_name", name)
        p = os.path.join(settings.exports_dir, name)
        if not os.path.isfile(p):
            raise ApiError(404, "file_not_found", name)
        return FileResponse(p, filename=name, media_type="application/octet-stream")

    # ---- 稽核 ----
    @app.get("/api/audit")
    def audit(limit: int = Query(200, le=5000), action: Optional[str] = None, _u: str = Depends(require("audit_view"))):
        if action:
            return db.all("SELECT * FROM audit_log WHERE action LIKE ? ORDER BY id DESC LIMIT ?", (action + "%", limit))
        return db.all("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))

    # ---- 授權 ----
    @app.get("/api/license")
    def license_status(_u: str = Depends(require("license"))):
        st = plat.license_status(refresh=True)
        return dict(st, enforced=plat.enforce_license)

    @app.get("/api/license/request")
    def license_request(who: str = Depends(require("license"))):
        doc = plat.license.request()
        db.audit(who, "license.request", "license", doc["payload"]["install_id"])
        name = f"license_request_{doc['payload']['machine_code']}.xrvreq"
        return Response(json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"), media_type="application/json",
                        headers={"Content-Disposition": f"attachment; filename={name}"})

    @app.post("/api/license/import")
    def license_import(file: UploadFile = File(...), who: str = Depends(require("license"))):
        try:
            doc = json.loads(file.file.read().decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ApiError(400, "license_invalid")
        try:
            plat.license.import_license(doc, who)
        except lic.LicenseError as e:
            raise ApiError(400, e.code, e.detail)
        plat.queue.notify()
        return plat.license_status(refresh=True)

    @app.post("/api/license/deactivate")
    def license_deactivate(who: str = Depends(require("license"))):
        try:
            proof = plat.license.deactivate(who)
        except lic.LicenseError as e:
            raise ApiError(400, e.code, e.detail)
        plat.license_status(refresh=True)
        return Response(json.dumps(proof, ensure_ascii=False, indent=1).encode("utf-8"), media_type="application/json",
                        headers={"Content-Disposition": "attachment; filename=license_deactivation.xrvdeact"})

    # ---- 系統設定與維護 ----
    @app.get("/api/settings")
    def get_settings(_u: str = Depends(require("settings"))):
        return dict(maintenance.get_settings(db), archive_originals=settings.archive_originals,
                    data_dir=settings.data_dir, workers=plat.queue.workers, inference=inference.available(),
                    workspace_mb=round(ws_mod.disk_usage_bytes(settings) / 1e6, 1))

    @app.put("/api/settings")
    def put_settings(b: SettingsBody, who: str = Depends(require("settings"))):
        try:
            return maintenance.put_settings(db, b.model_dump(exclude_unset=True), who)
        except ValueError as e:
            raise ApiError(400, "invalid_setting", str(e))

    @app.post("/api/maintenance/purge")
    def purge_now(who: str = Depends(require("settings"))):
        days = maintenance.get_settings(db)["retention_days"]
        if not days:
            raise ApiError(400, "retention_not_set")
        return maintenance.purge_archive(settings, db, days, who)

    # ---- 健康檢查 (不需登入；啟動器於進版後呼叫) ----
    @app.get("/api/health")
    def health(selftest: int = 0):
        out = dict(status="ok", version=__version__, schema_version=db.schema_version)
        if selftest:
            from .. import selftest as st
            out["selftest"], out["selftest_detail"] = st.run()
        return out

    # ---- 軟體更新與退版 ----
    @app.get("/api/updates")
    def updates_overview(_u: str = Depends(require("update"))):
        return updates.overview(settings.data_dir, updates.home())

    @app.post("/api/updates/upload")
    def updates_upload(file: UploadFile = File(...), who: str = Depends(require("update"))):
        home = updates.home()
        if not home:
            raise ApiError(400, "update_unavailable")
        d = os.path.join(settings.data_dir, "updates", "incoming")
        os.makedirs(d, exist_ok=True)
        dst = os.path.join(d, f"{time.strftime('%Y%m%d_%H%M%S')}_{os.path.basename(file.filename or 'package.xrvupd')}")
        with open(dst, "wb") as fo:
            shutil.copyfileobj(file.file, fo)
        cur = updates.overview(settings.data_dir, home)["current"]
        st = plat.license_status(refresh=True)
        lic_ok = (not plat.enforce_license) or st["state"] in lic.ANALYSIS_ALLOWED
        try:
            m = updates.stage(dst, home, cur, lic_ok)
        except updates.UpdateError as e:
            db.audit(who, "update.rejected", "update", os.path.basename(dst), reason=e.code, detail=e.detail)
            raise ApiError(400, e.code, e.detail)
        db.audit(who, "update.staged", "update", m["version"], file=os.path.basename(dst))
        return dict(version=m["version"], released_at=m.get("released_at"), notes=m.get("notes", {}),
                    min_from_version=m.get("min_from_version"), runtime_included=m.get("runtime_included", False))

    @app.post("/api/updates/apply")
    def updates_apply(b: VersionBody, who: str = Depends(require("update"))):
        ov = updates.overview(settings.data_dir, updates.home())
        if not ov["supported"]:
            raise ApiError(400, "update_unavailable")
        if not any(i["version"] == b.version for i in ov["installed"]) or b.version == ov["current"]:
            raise ApiError(400, "update_not_staged", b.version)
        running = db.one("SELECT COUNT(*) AS n FROM jobs WHERE status = 'running'")["n"]
        if running:
            raise ApiError(409, "update_jobs_running", str(running))
        db.audit(who, "update.requested", "update", b.version, from_version=ov["current"])
        updates.request(settings.data_dir, "update", b.version, who)
        return dict(ok=True)

    @app.post("/api/updates/rollback")
    def updates_rollback(b: VersionBody, who: str = Depends(require("update"))):
        ov = updates.overview(settings.data_dir, updates.home())
        if not any(r["version"] == b.version for r in ov["rollback_to"]):
            raise ApiError(400, "rollback_unavailable", b.version)
        db.audit(who, "update.rollback_requested", "update", b.version, from_version=ov["current"])
        updates.request(settings.data_dir, "rollback", b.version, who)
        return dict(ok=True)

    @app.get("/api/rollback-archives")
    def rollback_archives(_u: str = Depends(require("update"))):
        return archive_import.list_archives(settings, db)

    @app.post("/api/rollback-archives/{name}/import")
    def rollback_archive_import(name: str, who: str = Depends(require("update"))):
        try:
            return archive_import.import_archive(settings, db, name, who)
        except archive_import.ArchiveError as e:
            raise ApiError(400, e.code, e.detail)

    # ---- 前端 ----
    if os.path.isdir(WEB_DIST):
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")

    return app
