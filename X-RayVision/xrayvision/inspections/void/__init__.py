"""檢測模組：空洞檢測 (Void Inspection)，焊球與凸塊內的空洞，逐顆計算空洞率"""
from ...core.io import KIND_RAW16, KIND_RGB8
from ...core.plugin import (JUDGE_FAIL, JUDGE_NOT_JUDGED, JUDGE_PASS, JUDGE_REVIEW, STATUS_NO_RESULT, STATUS_OK,
                            Finding, InspectionModule, ModuleResult, Param, register)
from ...core.quality import QualityRule
from ...core.units import add_um
from . import algorithm

# 參數結構鍵 → 演算法設定鍵
_PARAM_TO_CFG = dict(
    ball_radius_min_px="r_min",
    ball_radius_max_px="r_max",
    min_void_diameter_ratio="min_diam_ratio",
    sigma_k="sigma_k",
    min_depth="min_depth",
    rim_exclusion="rim",
    max_fit_rms="max_fit_rms",
    method="method",
    model=None,
)

_BOTH = (KIND_RAW16, KIND_RGB8)


@register
class VoidInspection(InspectionModule):
    module_id = "void"
    version = "1.1.0"
    names = {"zh-TW": "空洞檢測", "en": "Void Inspection"}
    supported_kinds = _BOTH
    params = (
        Param("ball_radius_min_px", "float", 20.0, {"zh-TW": "焊點半徑搜尋下限", "en": "Ball radius search minimum"},
              min=5.0, max=500.0, unit="px"),
        Param("ball_radius_max_px", "float", 120.0, {"zh-TW": "焊點半徑搜尋上限", "en": "Ball radius search maximum"},
              min=5.0, max=500.0, unit="px"),
        Param("min_void_diameter_ratio", "float", 0.08,
              {"zh-TW": "最小空洞直徑（焊點直徑比例）", "en": "Minimum void diameter (ratio of ball diameter)"},
              min=0.03, max=0.5, unit="ratio"),
        Param("sigma_k", "float", 4.0, {"zh-TW": "空洞偵測雜訊倍數", "en": "Void detection noise factor"},
              min=2.0, max=10.0, unit="sigma", advanced=True),
        Param("min_depth", "float", 0.07, {"zh-TW": "空洞最小相對深度", "en": "Minimum relative void depth"},
              min=0.01, max=0.5, unit="ratio", advanced=True),
        Param("rim_exclusion", "float", 0.10, {"zh-TW": "邊緣排除環帶", "en": "Rim exclusion band"},
              min=0.0, max=0.3, unit="ratio", advanced=True),
        Param("max_fit_rms", "float", 0.12, {"zh-TW": "外形擬合誤差上限", "en": "Maximum shape fit error"},
              min=0.02, max=0.5, unit="ratio", advanced=True),
        Param("method", "enum", "rule", {"zh-TW": "空洞分割方法", "en": "Void segmentation method"},
              choices=("rule", "model", "both")),
        Param("model", "model", "", {"zh-TW": "深度學習模型", "en": "Deep learning model"},
              choices=("void_segmentation",)),
    )
    # 新增配方預設使用深度學習模型 (有啟用中的空洞模型時)；沒有模型時範本維持規則式
    template_model_defaults = {"method": "model"}
    # 品質規則初始值 (依合成影像與 Batch2 訂定；取得實際空洞影像後校正)
    quality_rules = (
        QualityRule("void.measurable_ratio", warn_below=0.5, fail_below=0.2, kinds=_BOTH),
        QualityRule("void.contrast", warn_below=8.0, fail_below=5.0),
        QualityRule("void.min_detectable_pct", warn_above=5.0, fail_above=15.0),
    )
    judgment_params = (
        Param("void_pct_max", "float", 25.0, {"zh-TW": "單顆空洞率上限", "en": "Maximum void ratio per ball"},
              min=0.0, max=100.0, unit="%"),
        Param("largest_void_pct_max", "float", None,
              {"zh-TW": "最大單一空洞上限", "en": "Maximum single void ratio"}, min=0.0, max=100.0, unit="%"),
        Param("total_void_pct_max", "float", None, {"zh-TW": "總空洞率上限", "en": "Maximum total void ratio"},
              min=0.0, max=100.0, unit="%"),
        Param("max_failed_balls", "int", 0, {"zh-TW": "允許超規焊點數", "en": "Allowed out-of-spec balls"},
              min=0, max=10000),
        Param("max_unmeasured_balls", "int", 0, {"zh-TW": "允許未量測焊點數", "en": "Allowed unmeasured balls"},
              min=0, max=10000, advanced=True),
        Param("confidence_k", "float", 2.0, {"zh-TW": "判定信心倍數", "en": "Confidence factor"},
              min=0.0, max=5.0, unit="sigma", advanced=True),
    )
    finding_table = dict(category="ball", sort="void_pct", limit=10,
                         columns=("void_pct", "largest_void_pct", "void_count", "void_pct_se"))
    # 模組驗證 (validate-module)：驗收標準依規劃書 PLAN-002 第 8 節
    validation_criteria = {
        "detection_rate": (">=", 0.95),          # 直徑 >= 焊點直徑 15% 的空洞
        "false_call_rate": ("<=", 0.02),         # 無空洞焊點的誤報率
        "void_pct_error_p95": ("<=", 2.0),       # 空洞率誤差 95% 分位 (百分點)
        "false_pass": ("<=", 0),                 # 漏判 (實際超規卻判合格) 不可發生
        "unmeasured_ratio": ("<=", 0.05),
    }

    @classmethod
    def validation_metrics(cls, pairs, spec):
        from .validate import metrics
        return metrics(pairs, spec)

    repeat_anchor = "ball"
    repeat_keys = ("void_pct",)
    overlay_styles = {
        "ball": {"color": (0, 200, 0), "thickness": 2},
        "void": {"color": (0, 0, 255), "thickness": 2},
        "unused": {"color": (150, 150, 150), "thickness": 1},
    }

    def run(self, ctx, params):
        cfg = dict(algorithm.DEFAULTS)
        for k, v in params.items():
            if _PARAM_TO_CFG[k]:
                cfg[_PARAM_TO_CFG[k]] = v
        if cfg["r_max"] < cfg["r_min"]:
            cfg["r_min"], cfg["r_max"] = cfg["r_max"], cfg["r_min"]
        # 深度學習模型：method 為 model／both 時需要；找不到模型時 model 方法無法判定，both 退回規則式並需複判
        model, model_reason = None, ""
        if params["method"] != "rule":
            model = (ctx.models or {}).get(params["model"]) if params["model"] else None
            if model is None:
                model_reason = "model_unavailable"
        if params["method"] == "model" and model is None:
            return ModuleResult(module_id=self.module_id, module_version=self.version, status=STATUS_NO_RESULT,
                                params=dict(params), reasons=[model_reason])
        res = algorithm.analyze(ctx.prepared.absorption, cfg,
                                in_region=ctx.in_region if ctx.region_mask is not None else None,
                                model=model, gpu=ctx.gpu)
        result = ModuleResult(module_id=self.module_id, module_version=self.version, status=STATUS_OK,
                              params=dict(params), rejects=dict(res["rejects"]),
                              rejected=[dict(r) for r in res["rejected"]])
        result.metrics = {f"{self.module_id}.{k}": v for k, v in res["metrics"].items()}
        px = ctx.pixel_size_um
        balls = res["balls"]
        used = [b for b in balls if b["used"]]
        fid = 0
        for i, b in enumerate(balls, 1):
            fid += 1
            ball_id = fid                                  # 空洞物件以 flags.ball 指向所屬焊點
            meas = dict(void_pct=b["void_pct"], largest_void_pct=b["largest_void_pct"], void_count=b["void_count"],
                        **{k: b[k] for k in ("void_pct_rule", "void_pct_model") if k in b},
                        void_pct_se=b["void_pct_se"], ball_r_px=b["r"], void_area_px2=b["void_area_px2"],
                        ball_area_px2=b["ball_area_px2"], contrast=b["contrast"], fit_rms=b["rms"],
                        min_detectable_pct=b["min_detectable_pct"])
            add_um(meas, px)
            result.findings.append(Finding(
                id=ball_id, category="ball", geometry={"ball": dict(type="circle", x=b["x"], y=b["y"], r=b["r"])},
                measurements=meas, used=b["used"], reason=b["reason"],
                flags=dict(label=f"ball{i}", pad=b["pad"] is not None, pad_hidden=bool(b.get("pad_hidden")),
                           **({"model_disagree": bool(b["model_disagree"])} if "model_disagree" in b else {}))))
            for v in b["voids"]:
                fid += 1
                vm = dict(area_px2=v["area_px2"], ratio_pct=100.0 * v["area_px2"] / b["ball_area_px2"],
                          depth=v["depth"])
                add_um(vm, px)
                result.findings.append(Finding(
                    id=fid, category="void", geometry={"void": dict(type="polygon", points=v["contour"])},
                    measurements=vm, flags=dict(ball=ball_id, rim=bool(v["rim"]))))
        # 未量測焊點 (外形不符、對比不足、重疊、擬合失敗) 列入判定，不會被略過；
        # 位於影像邊緣的焊點由相鄰影像檢測，不列入
        n_unmeasured = sum(1 for b in balls if not b["used"]) + sum(res["rejects"].get(k, 0)
                                                                    for k in ("overlap", "fit_failed"))
        area_all = sum(b["ball_area_px2"] for b in used)
        result.summary = dict(
            balls_measured=len(used), balls_unmeasured=n_unmeasured, candidates=res["n_cand"],
            balls_with_voids=sum(1 for b in used if b["void_count"]),
            max_void_pct=max((b["void_pct"] for b in used), default=0.0),
            mean_void_pct=(sum(b["void_pct"] for b in used) / len(used)) if used else 0.0,
            max_largest_void_pct=max((b["largest_void_pct"] for b in used), default=0.0),
            total_void_pct=(100.0 * sum(b["void_area_px2"] for b in used) / area_all) if area_all else 0.0,
            pixel_size_um=px, shape=res["shape"], method=params["method"],
            model=params["model"] if model is not None else "")
        if model_reason:
            result.reasons.append(model_reason)
        if not used:
            result.status = STATUS_NO_RESULT
            result.reasons.append("no_balls_found" if not balls else "no_measurable_balls")
        return result

    def judge(self, result, spec, pixel_size_um=None):
        """
        逐顆焊點：空洞率 ± k·估計誤差 與上限比較
          下限 (空洞率 - k·誤差) 超過上限 → 超規；上限 (空洞率 + k·誤差) 超過上限 → 接近規格 (需複判)
        超規焊點數 > 允許數 → 不合格；有接近規格的焊點或未量測焊點超過允許數 → 需複判
        最大單一空洞、總空洞率 (有設定時) 同樣判定。未設定任何上限 → 未判定
        """
        lim = spec.get("void_pct_max")
        lim_big = spec.get("largest_void_pct_max")
        lim_total = spec.get("total_void_pct_max")
        if lim is None and lim_big is None and lim_total is None:
            return JUDGE_NOT_JUDGED, []
        k = spec["confidence_k"]
        balls = [f for f in result.findings if f.category == "ball" and f.used]
        failed, near, reasons = [], [], []
        for f in balls:
            m = f.measurements
            se = m.get("void_pct_se") or 0.0
            label = f.flags.get("label", f"ball{f.id}")
            for value, limit, code in ((m["void_pct"], lim, "void_pct"),
                                       (m["largest_void_pct"], lim_big, "largest_void_pct")):
                if limit is None:
                    continue
                if value - k * se > limit:
                    failed.append(label)
                    reasons.append(f"{code}_exceeds_limit:{label}")
                    break
                if value + k * se > limit:
                    near.append(label)
                    reasons.append(f"{code}_near_limit:{label}")
                    break
        level = JUDGE_PASS
        if len(failed) > spec["max_failed_balls"]:
            level = JUDGE_FAIL
        elif near:
            level = JUDGE_REVIEW
        if lim_total is not None:
            total = (result.summary or {}).get("total_void_pct", 0.0)
            if total > lim_total:
                level = JUDGE_FAIL
                reasons.append("total_void_pct_exceeds_limit:image")
        # 規則式與模型差異大 (method=both)、或指定的模型無法使用：需複判
        disagree = [f.flags.get("label", f"ball{f.id}") for f in balls if f.flags.get("model_disagree")]
        if disagree and level != JUDGE_FAIL:
            level = JUDGE_REVIEW
        reasons += [f"model_rule_disagree:{x}" for x in disagree]
        if "model_unavailable" in (result.reasons or []) and level != JUDGE_FAIL:
            level = JUDGE_REVIEW
            reasons.append("model_unavailable")
        unmeasured = (result.summary or {}).get("balls_unmeasured", 0)
        if unmeasured > spec["max_unmeasured_balls"] and level != JUDGE_FAIL:
            level = JUDGE_REVIEW
            reasons.append("balls_not_measured")
        if not balls and level == JUDGE_PASS:
            level = JUDGE_REVIEW
            reasons.append("no_measurable_balls")
        return level, reasons
