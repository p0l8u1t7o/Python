"""
分析流程：依配方對一張影像執行啟用的檢測模組，輸出可追溯的分析結果。

配方 (第 0～1 階段為 JSON 檔；版本管理於第 2 階段移入資料庫)：
{
  "recipe_id": "bump-default", "version": 1, "name": {"zh-TW": "...", "en": "..."},
  "pixel_size_um": null,                        固定像素尺寸 (µm)；null 時由模組以設計尺寸推得
  "calibration_profile": null,                  暗場／平場校正設定檔代碼
  "quality_rules": [{"metric": "image.snr", "warn_below": 80, "fail_below": 30}],   覆寫預設品質規則
  "acquisition_limits": {"tube_voltage_kv": [60, 130]},                             拍攝參數允許範圍
  "regions": {"reference": {...}, "include": [...], "exclude": [...]},             檢測區域 (選用，regions.py)
  "modules": [{"module_id": "bump_alignment", "params": {...},
               "judgment": {"die_shift_max_um": 5.0}}]                               判定規格
}
"""
import json
import time
import traceback
from dataclasses import asdict, dataclass, field

from .. import __version__
from . import acquisition, judge, plugin, quality
from . import regions as regions_mod
from .calibration import CalibrationError, CalibrationProfile, prepare
from .io import KIND_RGB8, load_image

DEFAULT_CALIBRATION_ROOT = "calibration"


class RecipeError(ValueError):
    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


@dataclass
class ModuleSpec:
    module_id: str
    params: dict = field(default_factory=dict)
    enabled: bool = True
    judgment: dict = field(default_factory=dict)


@dataclass
class Recipe:
    recipe_id: str
    version: int
    name: dict
    modules: list
    pixel_size_um: float = None
    calibration_profile: str = None
    quality_rules: list = field(default_factory=list)
    acquisition_limits: dict = field(default_factory=dict)
    regions: dict = None                   # 檢測區域 (regions.py)；None 為整張影像

    @classmethod
    def from_dict(cls, d):
        try:
            mods = [ModuleSpec(m["module_id"], dict(m.get("params", {})), bool(m.get("enabled", True)),
                               dict(m.get("judgment", {}))) for m in d["modules"]]
            px = d.get("pixel_size_um")
            r = cls(recipe_id=str(d["recipe_id"]), version=int(d["version"]), name=dict(d.get("name", {})),
                    modules=mods, pixel_size_um=float(px) if px else None,
                    calibration_profile=d.get("calibration_profile") or None,
                    quality_rules=[dict(q) for q in d.get("quality_rules", [])],
                    acquisition_limits={k: list(v) for k, v in d.get("acquisition_limits", {}).items()},
                    regions=regions_mod.normalize(d.get("regions")))
            for q in r.quality_rules:
                quality.QualityRule.from_dict(q)
            for k, v in r.acquisition_limits.items():
                if k not in acquisition.ALIASES or len(v) != 2:
                    raise ValueError(f"acquisition_limits.{k}")
        except regions_mod.RegionError as e:
            raise RecipeError("invalid_regions", str(e))
        except (KeyError, TypeError, ValueError) as e:
            raise RecipeError("invalid_recipe", str(e))
        r.validate()
        return r

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def validate(self):
        """檢查模組是否存在、參數是否合法；回傳各模組解析後的完整參數"""
        mods = plugin.available()
        resolved = {}
        for m in self.modules:
            if m.module_id not in mods:
                raise RecipeError("unknown_module", m.module_id)
            try:
                resolved[m.module_id] = mods[m.module_id].resolve_params(m.params)
                mods[m.module_id].resolve_judgment(m.judgment)
            except plugin.ParamError as e:
                raise RecipeError("invalid_param", f"{m.module_id}.{e.key}: {e.code}")
        return resolved

    def rules(self):
        """平台預設 → 各模組預設 → 配方覆寫"""
        mods = plugin.available()
        module_rules = [r for m in self.modules if m.enabled for r in mods[m.module_id].quality_rules]
        return quality.merge_rules(quality.PLATFORM_RULES, module_rules,
                                   [quality.QualityRule.from_dict(q) for q in self.quality_rules])

    def to_dict(self):
        return asdict(self)


@dataclass
class AnalysisContext:
    image: object          # io.ImageData
    prepared: object       # calibration.Prepared
    pixel_size_um: float = None
    region_mask: object = None     # 檢測區域遮罩 (bool 陣列，True = 檢測)；None 為整張影像
    region_groups: object = None   # 「視為一個陣列」區域編號遮罩 (int32，0 = 無)；None 為沒有這類區域
    region_labels: dict = None     # {強制陣列序號: 區域名稱}
    models: dict = None            # 深度學習模型 {"模型代碼@版本": dict(path, meta)}
    gpu: bool = False              # 推論使用 GPU (系統設定)

    def in_region(self, x, y):
        """模組以此判斷目標中心是否在檢測區域內"""
        return regions_mod.inside(self.region_mask, x, y)

    def region_group(self, x, y):
        """支援 supports_region_arrays 的模組以此取得目標所在的強制陣列序號 (0 = 由模組自動分群)"""
        return regions_mod.group_at(self.region_groups, x, y)


@dataclass
class AnalysisResult:
    image: dict
    software_version: str
    recipe: dict
    reference_only: bool
    notes: list
    quality: dict
    judgment: str
    judgment_reasons: list
    acquisition: dict
    calibration: dict
    modules: list
    elapsed_s: float
    started_at: str
    unvalidated_modules: list = field(default_factory=list)    # 未驗證的模組 (判定最多需複判)
    regions_source: str = "recipe"     # 生效的檢測區域來源：recipe = 配方；image = 本影像自訂檢測區域 (PLAN-004)
    manual: bool = False               # 手動檢測 (非正式結果，不寫入紀錄)


def load_profile(recipe, calibration_root):
    if not recipe.calibration_profile:
        return None
    return CalibrationProfile.load(calibration_root or DEFAULT_CALIBRATION_ROOT, recipe.calibration_profile)


def module_series(version):
    """驗證以「主版.次版」為單位：修訂版號只修正錯誤，不改變量測結果"""
    return ".".join(str(version).split(".")[:2])


def analyze_image(path, recipe, calibration_root=None, acquisition_manual=None, profile=None,
                  acquisition_record=None, validated=None, models=None, gpu=False, preloaded=None):
    """
    分析一張影像。無法讀取的影像拋出 io.ImageFormatError；校正設定檔錯誤拋出 CalibrationError。
    個別模組執行失敗時該模組狀態為 error，不影響其他模組。
    acquisition_record：已收集好的拍攝參數 (匯入時由原始檔位置讀取)；給定時不再尋找參數檔。
    models：配方參照的深度學習模型 {"模型代碼@版本": dict(path, meta)}；gpu：推論使用 GPU。
    validated：已驗證的 (模組代碼, 主版.次版) 集合；給定時，不在其中的模組判定最多為需複判
               (None 表示不檢查，例如工程用命令列)。
    preloaded：(ImageData, Prepared) 已載入並校正的影像 (互動分析快取)；給定時不重新讀檔與校正。
    回傳 (AnalysisResult, Prepared)
    """
    t0 = time.time()
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    if preloaded is not None:
        img, prep = preloaded
    else:
        img = load_image(path)
        if profile is None:
            profile = load_profile(recipe, calibration_root)
        prep = prepare(img, profile=profile)
    region_mask, region_scaled = regions_mod.build_mask(recipe.regions, img.shape)
    ctx = AnalysisContext(image=img, prepared=prep, pixel_size_um=recipe.pixel_size_um, region_mask=region_mask,
                          region_groups=regions_mod.build_groups(recipe.regions, img.shape),
                          region_labels={i: s.get("label") or str(i) for i, s in regions_mod.array_shapes(recipe.regions)},
                          models=dict(models or {}), gpu=bool(gpu))
    resolved = recipe.validate()
    notes = []
    if region_scaled:
        notes.append("regions_scaled")
    # 8-bit 轉存影像：可分析，但結果僅供參考 (正式判定只接受 16-bit 原始影像)
    reference_only = img.kind == KIND_RGB8
    if reference_only:
        notes.append("non_raw_image")
    results = []
    for spec in recipe.modules:
        if not spec.enabled:
            continue
        cls = plugin.get(spec.module_id)
        t1 = time.time()
        if img.kind not in cls.supported_kinds:
            r = plugin.ModuleResult(spec.module_id, cls.version, plugin.STATUS_NO_RESULT,
                                    resolved[spec.module_id], reasons=["unsupported_image_kind"])
        else:
            try:
                r = cls().run(ctx, resolved[spec.module_id])
            except Exception:                                     # noqa: BLE001  模組錯誤不中斷整張分析
                r = plugin.ModuleResult(spec.module_id, cls.version, plugin.STATUS_ERROR, resolved[spec.module_id],
                                        reasons=["module_exception"])
                r.summary = dict(traceback=traceback.format_exc(limit=5))
        r.elapsed_s = time.time() - t1
        results.append(r)

    # 成像品質閘門 (平台指標 + 模組指標) 與拍攝參數檢查
    metrics = quality.image_metrics(img)
    for r in results:
        metrics.update(r.metrics)
    level, checks = quality.evaluate(metrics, recipe.rules(), img.kind)
    acq = acquisition_record or acquisition.collect(img.path, acquisition_manual)
    acq_checks = acquisition.limit_checks(acq["params"], recipe.acquisition_limits)
    checks += acq_checks
    for c in acq_checks:
        level = quality.worst(level, c["level"])
    if level == quality.FAIL:
        notes.append("image_quality_insufficient")
    elif level == quality.WARN:
        notes.append("image_quality_warning")
    info = dict(path=img.path, name=img.name, sha256=img.sha256, kind=img.kind, width=img.shape[1],
                height=img.shape[0], source_channels=img.source_channels)
    res = AnalysisResult(image=info, software_version=__version__, recipe=recipe.to_dict(),
                         reference_only=reference_only, notes=notes,
                         quality=dict(level=level, metrics=metrics, checks=checks), judgment="", judgment_reasons=[],
                         acquisition=acq, calibration=prep.calibration, modules=results,
                         elapsed_s=0.0, started_at=started)
    if validated is not None:
        vset = {tuple(v) for v in validated}
        res.unvalidated_modules = [r.module_id for r in results
                                   if (r.module_id, module_series(r.module_version)) not in vset]
        if res.unvalidated_modules:
            notes.append("module_unvalidated")
    judge.judge_modules(res, recipe)
    res.judgment, res.judgment_reasons = judge.overall(res)
    res.elapsed_s = time.time() - t0
    return res, prep


__all__ = ["Recipe", "RecipeError", "analyze_image", "AnalysisResult", "CalibrationError", "load_profile"]
