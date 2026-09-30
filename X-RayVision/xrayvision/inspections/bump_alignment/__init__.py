"""檢測模組：微凸塊對位 (Micro Bump Alignment)"""
from ...core.io import KIND_RAW16, KIND_RGB8
from ...core.plugin import (JUDGE_FAIL, JUDGE_NOT_JUDGED, JUDGE_PASS, JUDGE_REVIEW, STATUS_NO_RESULT, STATUS_OK,
                            Finding, Group, InspectionModule, ModuleResult, Param, register)
from ...core.quality import QualityRule
from ...core.units import add_um
from . import algorithm

# 參數結構鍵 → 演算法設定鍵 (None 表示由模組外殼處理，不傳給演算法)
_PARAM_TO_CFG = dict(
    bump_level="bump_level",
    pad_level="pad_level",
    lobe_mode="lobe",
    bump_radius_min_px="bump_r_min",
    bump_radius_max_px="bump_r_max",
    large_ball_ratio="ball_ratio",
    min_array_size="min_array",
    max_contour_rms_px="max_rms",
    radius_tolerance="r_dev",
    trace_max_deg="trace_max_deg",
    lobe_min_span_deg="lobe_min_span",
    shift_inlier_tol_px="shift_tol",
    design_pitch_um=None,
)

_BOTH = (KIND_RAW16, KIND_RGB8)


@register
class BumpAlignment(InspectionModule):
    module_id = "bump_alignment"
    version = "1.1.1"
    names = {"zh-TW": "微凸塊對位", "en": "Micro Bump Alignment"}
    supported_kinds = _BOTH
    supports_region_arrays = True
    params = (
        Param("bump_level", "float", 0.75, {"zh-TW": "凸塊輪廓高度", "en": "Bump contour level"},
              min=0.5, max=0.95, unit="ratio"),
        Param("pad_level", "float", 0.25, {"zh-TW": "焊墊輪廓高度", "en": "Pad contour level"},
              min=0.05, max=0.5, unit="ratio"),
        Param("lobe_mode", "enum", "auto", {"zh-TW": "焊墊露出弧模式", "en": "Exposed pad arc mode"},
              choices=("auto", "on", "off")),
        Param("design_pitch_um", "float", 0.0, {"zh-TW": "凸塊設計間距", "en": "Bump design pitch"},
              min=0.0, max=10000.0, unit="um"),
        Param("bump_radius_min_px", "float", 12.0, {"zh-TW": "凸塊半徑搜尋下限", "en": "Bump radius search minimum"},
              min=3.0, max=200.0, unit="px"),
        Param("bump_radius_max_px", "float", 48.0, {"zh-TW": "凸塊半徑搜尋上限", "en": "Bump radius search maximum"},
              min=3.0, max=200.0, unit="px"),
        Param("large_ball_ratio", "float", 1.8, {"zh-TW": "大球判定倍率", "en": "Large ball radius ratio"},
              min=1.2, max=5.0, unit="ratio", advanced=True),
        Param("min_array_size", "int", 6, {"zh-TW": "陣列最少凸塊數", "en": "Minimum bumps per array"},
              min=3, max=1000),
        Param("max_contour_rms_px", "float", 2.0, {"zh-TW": "輪廓圓度誤差上限", "en": "Maximum contour roundness error"},
              min=0.3, max=10.0, unit="px", advanced=True),
        Param("radius_tolerance", "float", 0.15, {"zh-TW": "半徑一致性容許比例", "en": "Radius consistency tolerance"},
              min=0.02, max=0.5, unit="ratio", advanced=True),
        Param("trace_max_deg", "float", 40.0, {"zh-TW": "走線干擾最大角寬", "en": "Maximum trace interference width"},
              min=5.0, max=120.0, unit="deg", advanced=True),
        Param("lobe_min_span_deg", "float", 50.0, {"zh-TW": "露出弧最小角寬", "en": "Minimum exposed arc width"},
              min=10.0, max=180.0, unit="deg", advanced=True),
        Param("shift_inlier_tol_px", "float", 0.5, {"zh-TW": "偏移估計內點容差下限", "en": "Minimum inlier tolerance"},
              min=0.1, max=10.0, unit="px", advanced=True),
    )
    # 品質規則初始值 (依 Batch1／Batch2 訂定；取得現場參數掃描影像後校正)
    quality_rules = (
        QualityRule("bump_alignment.sites_used", warn_below=30, fail_below=10, kinds=_BOTH),
        QualityRule("bump_alignment.oblique_angle_deg", warn_above=25.0, fail_above=30.0, kinds=_BOTH),
        QualityRule("bump_alignment.measurable_ratio", warn_below=0.4, fail_below=0.2),
        QualityRule("bump_alignment.contrast", warn_below=0.04, fail_below=0.02),
        QualityRule("bump_alignment.edge_width_ratio", warn_above=0.2, fail_above=0.3),
        QualityRule("bump_alignment.pitch_deviation", warn_above=0.03, fail_above=0.08, kinds=_BOTH),
    )
    judgment_params = (
        Param("die_shift_max_um", "float", None, {"zh-TW": "晶片偏移上限", "en": "Maximum die shift"},
              min=0.0, max=1000.0, unit="um"),
        Param("die_shift_max_px", "float", None, {"zh-TW": "晶片偏移上限（像素）", "en": "Maximum die shift (pixels)"},
              min=0.0, max=1000.0, unit="px", advanced=True),
        Param("confidence_k", "float", 2.0, {"zh-TW": "判定信心倍數", "en": "Confidence factor"},
              min=0.0, max=5.0, unit="sigma", advanced=True),
        Param("check_groups", "bool", True, {"zh-TW": "逐陣列判定", "en": "Judge each array"}, advanced=True),
    )
    repeat_anchor = "bump"
    repeat_keys = ("dx_px", "dy_px")
    summary_vector = "die_shift"
    overlay_styles = {
        "pad": {"color": (0, 200, 0), "thickness": 2},
        "bump": {"color": (0, 0, 255), "thickness": 2},
        "offset": {"color": (0, 255, 255), "thickness": 2, "scale": 10.0},
        "unused": {"color": (150, 150, 150), "thickness": 1},
        "group": {"color": (255, 160, 0), "thickness": 3},
        "group_shift": {"color": (255, 160, 0), "thickness": 5, "scale": 40.0},
    }

    def run(self, ctx, params):
        cfg = dict(algorithm.DEFAULTS)
        for k, v in params.items():
            if _PARAM_TO_CFG[k]:
                cfg[_PARAM_TO_CFG[k]] = v
        res = algorithm.analyze(ctx.prepared.absorption, ctx.image.kind, cfg,
                                in_region=ctx.in_region if ctx.region_mask is not None else None,
                                array_of=ctx.region_group if ctx.region_groups is not None else None)
        result = ModuleResult(module_id=self.module_id, module_version=self.version, status=STATUS_OK,
                              params=dict(params), rejects=res["rejects"], rejected=res["rejected"])
        result.metrics = {f"{self.module_id}.{k}": v for k, v in res["metrics"].items()}
        if res["R0"] is None:
            result.status = STATUS_NO_RESULT
            result.reasons.append("no_bumps_found")
            return result

        # 像素尺寸：配方固定值優先；否則由設計間距與實測 pitch 推得
        pitch_px = res["metrics"].get("pitch_px")
        design = params["design_pitch_um"] or None
        px_um, px_src = ctx.pixel_size_um, "recipe" if ctx.pixel_size_um else None
        if px_um is None and design and pitch_px:
            px_um, px_src = design / pitch_px, "design_pitch"
        if design and pitch_px and ctx.pixel_size_um:
            result.metrics[f"{self.module_id}.pitch_deviation"] = abs(pitch_px * ctx.pixel_size_um / design - 1)

        for i, s in enumerate(res["sites"], 1):
            f = _finding(i, s)
            add_um(f.measurements, px_um)
            result.findings.append(f)
        for a in res["arrays"]:
            est = _est_um(a["est"], px_um)
            meas = add_um(dict(bump_r_px=a["bump_r"], pad_r_px=a["pad_r"], pitch_px=a["pitch"]), px_um)
            label = (ctx.region_labels or {}).get(a["region"], "") if a["region"] else ""
            result.groups.append(Group(id=a["id"], category="bump_array", bbox=a["bbox"], size=a["n_sites"],
                                       estimate=est, grade=a["grade"], measurements=meas,
                                       source="region" if a["region"] else "auto", label=label))
            if a["region"] and est is None:
                result.reasons.append(f"region_array_insufficient_sites:group{a['id']}")
        used = [s for s in res["sites"] if s["used"]]
        result.summary = dict(die_shift=_est_um(res["est"], px_um), grade=res["grade"], bump_radius_px=res["R0"],
                              candidates=res["n_cand"], large_balls=res["n_balls"],
                              sites_measured=len(res["sites"]), sites_used=len(used),
                              lobe_sites=sum(s["pad"]["mode"] == "lobe" for s in used),
                              pixel_size_um=px_um, pixel_size_source=px_src)
        if res["est"] is None:
            result.status = STATUS_NO_RESULT
            result.reasons.append("insufficient_sites")
        return result


    def judge(self, result, spec, pixel_size_um=None):
        """
        晶片偏移判定：偏移量 |shift| 與標準誤 se，k = confidence_k
          |shift| + k·se <= 上限 → 合格；|shift| - k·se > 上限 → 不合格；其餘 → 需複判 (接近規格邊界)
        上限優先使用 µm (需像素尺寸)；只設定 px 上限時以 px 判定。
        check_groups=True 時，等級 mid 以上的各陣列也逐一判定，任一陣列不合格即不合格。
        """
        lim_um, lim_px, k = spec.get("die_shift_max_um"), spec.get("die_shift_max_px"), spec["confidence_k"]
        if lim_um is not None and pixel_size_um:
            limit, scale = lim_um, pixel_size_um
        elif lim_px is not None:
            limit, scale = lim_px, 1.0
        elif lim_um is not None:
            return JUDGE_REVIEW, ["pixel_size_unknown"]
        else:
            return JUDGE_NOT_JUDGED, []
        e = (result.summary or {}).get("die_shift")
        if not e:
            return JUDGE_REVIEW, ["insufficient_sites"]
        items = [("image", e)]
        if spec["check_groups"]:
            items += [(f"group{g.id}", g.estimate) for g in result.groups if g.estimate and g.grade in ("high", "mid")]
        level, reasons = JUDGE_PASS, []
        for name, est in items:
            mag, se = est["mag"] * scale, est["se"] * scale
            if mag - k * se > limit:
                level = JUDGE_FAIL
                reasons.append(f"die_shift_exceeds_limit:{name}")
            elif mag + k * se > limit and level != JUDGE_FAIL:
                level = JUDGE_REVIEW
                reasons.append(f"die_shift_near_limit:{name}")
        return level, reasons


def _est_um(e, px_um):
    if e is None or not px_um:
        return e
    e = dict(e)
    for k in ("dx", "dy", "mag", "rms", "se"):
        e[k + "_um"] = e[k] * px_um
    return e


def _finding(i, s):
    b, p = s["bump"], s["pad"]
    geom = {
        "bump": dict(type="circle", x=b["x"], y=b["y"], r=b["r"]),
        "pad": dict(type="circle", x=p["x"], y=p["y"], r=p["r"]),
        "offset": dict(type="vector", x=p["x"], y=p["y"], dx=s["dx"], dy=s["dy"]),
    }
    meas = dict(dx_px=s["dx"], dy_px=s["dy"], offset_px=s["d"], bump_r_px=b["r"], pad_r_px=p["r"],
                bump_rms_px=b["rms"], pad_rms_px=p["rms"], bump_coverage=b["cov"], pad_coverage=p["cov"],
                contrast=s["contrast"], edge_width_px=s["model_w"], lobe_span_deg=p["span"],
                axis_ratio=s["axis_ratio"])
    return Finding(id=i, category="bump_site", geometry=geom, measurements=meas, group=s["array"], used=s["used"],
                   reason=s["reason"], flags=dict(inlier=s["inlier"], pad_mode=p["mode"], pad_free_radius=p["free"]))
