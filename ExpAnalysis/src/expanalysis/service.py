"""服務層 — 把資料層、物理層、AI 層串成 API 直接可用的操作。

為什麼需要這一層
----------------
擬合 80 個 k_eff 要 2~3 秒、GP 映射要 1 秒、LOBO 交叉驗證要十幾秒。
如果每個 HTTP 請求都重算，UI 會卡到不能用。這一層負責：

  * 以「資料版本」為鍵的記憶體快取；任何寫入都會讓版本前進、快取失效
  * 保證同一份分析結果在不同端點之間一致（前端切頁不會看到兩組數字）
  * 把所有失敗路徑收斂成明確的降級行為，而不是丟 traceback 給前端

執行緒安全：FastAPI 的同步端點跑在 threadpool，故所有重算都在鎖內進行，
避免兩個請求同時觸發同一份昂貴計算。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import numpy as np

from .config import SETTINGS
from .data.db import Database, get_db
from .data.repository import BatchRepository
from .fitting.bootstrap import bootstrap_keff
from .fitting.fit_keff import fit_all
from .logging_setup import get_logger
from .ml.anomaly import detect_anomalies
from .ml.gp_map import fit_keff_mapping
from .ml.residual import ResidualCorrector
from .ml.validation import leave_one_batch_out
from .optimize.grid_search import forward_predict, scan_parameter_grid
from .physics.profile_grid import get_profile_grid
from .physics.yield_calc import compute_purity_window

log = get_logger(__name__)


@dataclass
class AnalysisBundle:
    """一次完整分析的產物。所有端點共用同一份，確保數字一致。"""

    version: int
    fits: dict = field(default_factory=dict)          # {batch_id: {element: KeffFit}}
    mapping: object = None
    anomalies: list = field(default_factory=list)
    corrector: ResidualCorrector | None = None
    elements: list[str] = field(default_factory=list)
    c0_median: dict[str, float] = field(default_factory=dict)
    zone_len_frac_median: float = 0.10
    computed_ms: int = 0
    duration_s: float = 0.0
    warnings: list[str] = field(default_factory=list)


class AnalysisService:
    def __init__(self, db: Database | None = None):
        self.db = db or get_db()
        self.repo = BatchRepository(self.db)
        self._lock = threading.RLock()
        self._version = 0
        self._bundle: AnalysisBundle | None = None
        self._lobo_cache: dict[int, object] = {}
        self._bootstrap_done: set[int] = set()
        self._excluded: set[tuple[str, str]] = set()

    # ── 快取控制 ────────────────────────────────────────────────
    def invalidate(self) -> None:
        with self._lock:
            self._version += 1
            self._bundle = None
            self._lobo_cache.clear()
            self._bootstrap_done.clear()

    @property
    def version(self) -> int:
        return self._version

    # ── 核心分析 ────────────────────────────────────────────────
    def bundle(self, with_bootstrap: bool = True) -> AnalysisBundle:
        """取得（必要時重算）完整分析結果。"""
        with self._lock:
            if self._bundle is not None and (
                    not with_bootstrap or self._version in self._bootstrap_done):
                return self._bundle
            return self._recompute(with_bootstrap)

    def _recompute(self, with_bootstrap: bool) -> AnalysisBundle:
        t0 = time.perf_counter()
        details = self.repo.all_details()
        warnings: list[str] = []

        if not details:
            b = AnalysisBundle(version=self._version, warnings=["資料庫中沒有任何批次。"])
            self._bundle = b
            return b

        fits = fit_all(details)

        # ── bootstrap 不確定度（可關閉以加速）─────────────────
        if with_bootstrap:
            by_id = {d.batch.batch_id: d for d in details}
            for bid, per_el in fits.items():
                d = by_id.get(bid)
                if d is None:
                    continue
                for el, f in per_el.items():
                    pts = d.points(el)
                    try:
                        bs = bootstrap_keff(
                            [p.x_norm for p in pts], [p.value_ppm for p in pts],
                            [p.lod_ppm for p in pts], [p.censored for p in pts],
                            zone_len_frac=d.batch.zone_len_frac,
                            n_passes=d.batch.n_passes, c0_ppm=f.c0_ppm,
                            sigma_log=f.sigma_log, k_eff=f.k_eff, n_draws=300,
                        )
                        f.k_lo, f.k_hi, f.k_se = bs.k_lo, bs.k_hi, bs.k_se
                    except (ValueError, FloatingPointError) as exc:
                        log.warning("bootstrap 失敗 %s/%s：%s", bid, el, exc)
            self._bootstrap_done.add(self._version)

        # ── (v, T) → k_eff 映射：兩階段，讓 L3 保護 L2 ─────────
        # 第一階段先用全部資料擬一個映射；此時異常批次（例如取樣位置頭尾
        # 顛倒的那一批，k_eff 會被推到 1）會把回歸線整條拉歪。
        # 第二階段把「高嚴重度且建議排除」的批次拿掉後重擬，再重新偵測一次。
        # 這正是「AI 只保護準確度、不參與預測」的具體體現。
        batches = {d.batch.batch_id: d.batch for d in details}
        rows_all = [
            {"batch_id": bid, "element": el, "k_eff": f.k_eff, "k_se": f.k_se,
             "speed_mm_hr": batches[bid].speed_mm_hr, "temp_c": batches[bid].temp_c}
            for bid, per_el in fits.items() for el, f in per_el.items()
            if bid in batches
        ]
        mapping = fit_keff_mapping(rows_all, use_gp=True)
        anomalies = detect_anomalies(fits, mapping, batches)

        excluded = {(a.batch_id, a.element) for a in anomalies
                    if a.severity == "high" and a.exclude_recommended}
        if excluded:
            rows_clean = [r for r in rows_all
                          if (r["batch_id"], r["element"]) not in excluded]
            # 每個元素至少要留下 4 筆才值得重擬，否則寧可留著髒資料並標示警告
            keep_counts: dict[str, int] = {}
            for r in rows_clean:
                keep_counts[r["element"]] = keep_counts.get(r["element"], 0) + 1
            if keep_counts and min(keep_counts.values()) >= 4:
                mapping = fit_keff_mapping(rows_clean, use_gp=True)
                anomalies = detect_anomalies(fits, mapping, batches)
                ex_txt = "、".join(f"{b}/{e}" for b, e in sorted(excluded))
                warnings.append(
                    f"參數映射已排除 {len(excluded)} 組高嚴重度異常資料後重新擬合"
                    f"（{ex_txt}）。原始資料仍保留在資料庫中，可在「資料稽核」"
                    f"頁檢視排除理由。")
            else:
                warnings.append(
                    "偵測到高嚴重度異常，但排除後剩餘批次不足 4 筆，"
                    "映射仍使用全部資料——請優先確認這些批次的原始紀錄。")
        warnings.extend(mapping.warnings)
        self._excluded = excluded

        # ── L1 殘差修正器（預設關閉，須通過 LOBO 才啟用）───────
        from .ml.validation import _residual_samples
        corrector = ResidualCorrector(clip_frac=SETTINGS.residual_clip_frac)
        try:
            corrector.fit(_residual_samples(details, fits, mapping, 240))
        except (ValueError, np.linalg.LinAlgError) as exc:
            log.warning("殘差修正器訓練失敗：%s", exc)

        elements = sorted({el for per_el in fits.values() for el in per_el})
        c0_med = {
            el: float(np.median([f.c0_ppm for per_el in fits.values()
                                 for e2, f in per_el.items() if e2 == el]))
            for el in elements
        }
        zone_med = float(np.median([d.batch.zone_len_frac for d in details]))

        bundle = AnalysisBundle(
            version=self._version, fits=fits, mapping=mapping, anomalies=anomalies,
            corrector=corrector, elements=elements, c0_median=c0_med,
            zone_len_frac_median=zone_med,
            computed_ms=int(time.time() * 1000),
            duration_s=time.perf_counter() - t0,
            warnings=warnings,
        )
        self._bundle = bundle
        log.info("分析完成：%d 批次、%d 元素，耗時 %.2f 秒",
                 len(details), len(elements), bundle.duration_s)
        return bundle

    # ── 對外操作 ────────────────────────────────────────────────
    def overview(self) -> dict:
        b = self.bundle()
        details = self.repo.all_details()
        if not details:
            return {"n_batches": 0, "elements": [], "warnings": b.warnings,
                    "empty": True}

        keff_summary = {}
        for el in b.elements:
            ks = [f.k_eff for per in b.fits.values() for e2, f in per.items() if e2 == el]
            keff_summary[el] = {
                "median": float(np.median(ks)),
                "min": float(np.min(ks)), "max": float(np.max(ks)),
                "n": len(ks),
                "bps": b.mapping[el].bps.to_dict() if el in b.mapping else None,
                "gp_used": b.mapping[el].gp_used if el in b.mapping else False,
                "removable": _removability(float(np.median(ks))),
            }

        yields = []
        for d in details:
            y = self.batch_yield(d.batch.batch_id)
            if y is not None:
                yields.append(y)

        sev = {"high": 0, "medium": 0, "low": 0}
        for a in b.anomalies:
            sev[a.severity] += 1

        return {
            "empty": False,
            "n_batches": len(details),
            "n_measurements": sum(len(d.measurements) for d in details),
            "n_censored": sum(1 for d in details for m in d.measurements if m.censored),
            "elements": b.elements,
            "keff_summary": keff_summary,
            "yield_stats": {
                "mean": float(np.mean(yields)) if yields else None,
                "median": float(np.median(yields)) if yields else None,
                "min": float(np.min(yields)) if yields else None,
                "max": float(np.max(yields)) if yields else None,
                "std": float(np.std(yields)) if len(yields) > 1 else None,
            },
            "anomaly_counts": sev,
            "speed_range": [min(d.batch.speed_mm_hr for d in details),
                            max(d.batch.speed_mm_hr for d in details)],
            "temp_range": [min(d.batch.temp_c for d in details),
                           max(d.batch.temp_c for d in details)],
            "pass_range": [min(d.batch.n_passes for d in details),
                           max(d.batch.n_passes for d in details)],
            "threshold_ppm": SETTINGS.purity_threshold_ppm,
            "warnings": b.warnings,
            "analysis_duration_s": round(b.duration_s, 3),
        }

    def batch_payload(self, batch_id: str) -> dict | None:
        """單一批次的完整分析資料，含實測 vs 模型疊圖所需的曲線。"""
        d = self.repo.get_detail(batch_id)
        if d is None:
            return None
        b = self.bundle()
        fits = b.fits.get(batch_id, {})

        curves = {}
        profiles = {}
        grid = get_profile_grid(d.batch.zone_len_frac, d.batch.n_passes, 240)
        for el, f in fits.items():
            prof = grid.profile_at_k(f.k_eff, f.c0_ppm)
            profiles[el] = prof
            curves[el] = {
                "x_model": [round(float(v), 5) for v in grid.x_norm],
                "y_model": [float(v) for v in prof],
                "x_obs": f.x_norm, "y_obs": f.obs_ppm,
                "y_pred_at_obs": f.pred_ppm,
                "censored": f.censored_flags,
                "residuals": f.residuals,
                "fit": f.to_dict(),
            }

        window = None
        if profiles:
            win = compute_purity_window(
                grid.x_norm, profiles, SETTINGS.purity_threshold_ppm,
                head_crop_frac=d.batch.head_crop_frac)
            window = win.to_dict()

        return {
            "batch": d.batch.to_dict(),
            "element_specs": [s.to_dict() for s in d.element_specs],
            "elements": d.elements,
            "curves": curves,
            "total_ppm": [float(v) for v in
                          np.sum(list(profiles.values()), axis=0)] if profiles else [],
            "x_norm": [round(float(v), 5) for v in grid.x_norm],
            "window": window,
            "anomalies": [a.to_dict() for a in b.anomalies if a.batch_id == batch_id],
        }

    def batch_yield(self, batch_id: str) -> float | None:
        """該批次依擬合模型算出的 6N 得料率。"""
        d = self.repo.get_detail(batch_id)
        if d is None:
            return None
        fits = self.bundle().fits.get(batch_id, {})
        if not fits:
            return None
        grid = get_profile_grid(d.batch.zone_len_frac, d.batch.n_passes, 240)
        profiles = {el: grid.profile_at_k(f.k_eff, f.c0_ppm) for el, f in fits.items()}
        win = compute_purity_window(grid.x_norm, profiles,
                                    SETTINGS.purity_threshold_ppm,
                                    head_crop_frac=d.batch.head_crop_frac)
        return win.yield_frac

    def keff_table(self) -> list[dict]:
        b = self.bundle()
        details = {d.batch.batch_id: d.batch for d in self.repo.all_details()}
        rows = []
        for bid, per_el in b.fits.items():
            batch = details.get(bid)
            for el, f in per_el.items():
                rows.append({
                    "batch_id": bid, "element": el,
                    "k_eff": f.k_eff, "k_lo": f.k_lo, "k_hi": f.k_hi, "k_se": f.k_se,
                    "speed_mm_hr": batch.speed_mm_hr if batch else None,
                    "temp_c": batch.temp_c if batch else None,
                    "n_passes": batch.n_passes if batch else None,
                    "c0_ppm": f.c0_ppm, "sigma_log": f.sigma_log,
                    "rmse_log": f.rmse_log,
                    "n_points": f.n_points, "n_censored": f.n_censored,
                    "interpretation": f.interpretation,
                    "note": f.note,
                })
        rows.sort(key=lambda r: (r["element"], r["speed_mm_hr"] or 0))
        return rows

    def mapping_payload(self, n_curve: int = 60) -> dict:
        """參數映射視圖：z vs v 的散點與 GP 灰帶曲線。"""
        b = self.bundle()
        if b.mapping is None:
            return {"elements": [], "models": {}}
        details = {d.batch.batch_id: d.batch for d in self.repo.all_details()}
        if not details:
            return {"elements": [], "models": {}}

        v_lo = min(x.speed_mm_hr for x in details.values())
        v_hi = max(x.speed_mm_hr for x in details.values())
        pad = max(0.15 * (v_hi - v_lo), 0.3)
        v_curve = np.linspace(max(v_lo - pad, 0.05), v_hi + pad, n_curve)
        t_med = float(np.median([x.temp_c for x in details.values()]))

        out = {}
        for el, m in b.mapping.models.items():
            k, lo, hi = m.predict(v_curve, np.full_like(v_curve, t_med))
            z, z_std = m.predict_z(v_curve, np.full_like(v_curve, t_med))
            from .physics.bps import bps_linearize
            pts = [
                {"batch_id": r["batch_id"], "speed_mm_hr": r["speed_mm_hr"],
                 "temp_c": r["temp_c"], "k_eff": r["k_eff"],
                 "z": float(bps_linearize(r["k_eff"])),
                 "k_lo": r.get("k_lo"), "k_hi": r.get("k_hi")}
                for r in self.keff_table() if r["element"] == el
            ]
            out[el] = {
                "v_curve": [float(v) for v in v_curve],
                "temp_used": t_med,
                "k_curve": [float(v) for v in k],
                "k_lo": [float(v) for v in lo],
                "k_hi": [float(v) for v in hi],
                "z_curve": [float(v) for v in z],
                "z_std": [float(v) for v in z_std],
                "bps": m.bps.to_dict(),
                "gp_used": m.gp_used,
                "kernel": m.kernel_repr,
                "points": pts,
                "v_range_observed": [float(v_lo), float(v_hi)],
            }
        return {"elements": sorted(out), "models": out,
                "warnings": b.mapping.warnings}

    def simulate(self, speed: float, temp: float, n_passes: int,
                 zone_len_frac: float | None = None,
                 c0_ppm: dict[str, float] | None = None,
                 use_ai: bool = False,
                 head_crop_frac: float = 0.03,
                 threshold_ppm: float | None = None) -> dict:
        """正向模擬。永遠回傳純物理與（可選）物理+AI 兩組結果。"""
        b = self.bundle()
        if b.mapping is None or not b.mapping.elements:
            raise ValueError("尚未建立參數映射，請先匯入或產生批次資料。")

        zone = zone_len_frac if zone_len_frac is not None else b.zone_len_frac_median
        c0 = c0_ppm or b.c0_median
        thr = threshold_ppm if threshold_ppm is not None else SETTINGS.purity_threshold_ppm

        phys = forward_predict(b.mapping, speed, temp, n_passes, zone, c0,
                               threshold_ppm=thr, head_crop_frac=head_crop_frac,
                               corrector=None)
        payload = {"physics": phys.to_dict(), "ai": None, "dual_track": None}

        corrector = b.corrector
        if use_ai and corrector is not None and not corrector.enabled:
            # L1 殘差修正必須先通過留一批交叉驗證才允許啟用。使用者第一次在
            # 「模擬與預測」頁勾雙軌時，驗收可能還沒跑過——這裡按需觸發一次，
            # 結果會進快取，之後不會重算。不這樣做的話，使用者會永遠看到
            # 「未套用」，卻不知道是因為驗收沒跑而不是因為 AI 沒用。
            try:
                self.lobo()
            except (ValueError, RuntimeError) as exc:
                log.warning("按需執行 LOBO 驗收失敗：%s", exc)
        if use_ai and corrector is not None and corrector.enabled:
            ai = forward_predict(b.mapping, speed, temp, n_passes, zone, c0,
                                 threshold_ppm=thr, head_crop_frac=head_crop_frac,
                                 corrector=corrector)
            payload["ai"] = ai.to_dict()
            payload["dual_track"] = corrector.dual_track(
                phys.yield_nominal, ai.yield_nominal, speed, temp, n_passes).to_dict()
        elif corrector is not None:
            payload["dual_track"] = corrector.dual_track(
                phys.yield_nominal, phys.yield_nominal, speed, temp, n_passes).to_dict()
        return payload

    def optimize(self, speed_range=None, temp_range=None, pass_choices=None,
                 throughput_weight: float = 0.0,
                 zone_len_frac: float | None = None) -> dict:
        b = self.bundle()
        if b.mapping is None or not b.mapping.elements:
            raise ValueError("尚未建立參數映射，請先匯入或產生批次資料。")
        details = self.repo.all_details()
        sp = speed_range or _padded(
            [d.batch.speed_mm_hr for d in details], 0.25, lo_min=0.3)
        tp = temp_range or _padded([d.batch.temp_c for d in details], 0.15)
        pc = tuple(pass_choices or sorted({d.batch.n_passes for d in details})[:6]) or (8,)
        zone = zone_len_frac if zone_len_frac is not None else b.zone_len_frac_median

        res = scan_parameter_grid(
            b.mapping, b.c0_median, zone,
            speed_range=sp, temp_range=tp, pass_choices=pc,
            threshold_ppm=SETTINGS.purity_threshold_ppm,
            throughput_weight=throughput_weight,
        )
        return res.to_dict()

    def bo_observations(self) -> list[dict]:
        """把歷史批次轉成貝氏最佳化的觀測值。"""
        rows = []
        for d in self.repo.all_details():
            y = self.batch_yield(d.batch.batch_id)
            if y is None:
                continue
            rows.append({"batch_id": d.batch.batch_id,
                         "speed_mm_hr": d.batch.speed_mm_hr,
                         "temp_c": d.batch.temp_c,
                         "n_passes": d.batch.n_passes,
                         "yield_frac": y})
        return rows

    def make_oracle(self, zone_len_frac: float | None = None):
        """以既有模型建構「虛擬產線」，供 DOE 對比使用。"""
        b = self.bundle()
        zone = zone_len_frac if zone_len_frac is not None else b.zone_len_frac_median

        def oracle(speed: float, temp: float, n_passes: int) -> float:
            pred = forward_predict(b.mapping, speed, temp, int(n_passes), zone,
                                   b.c0_median,
                                   threshold_ppm=SETTINGS.purity_threshold_ppm)
            return pred.yield_nominal

        return oracle

    def anomalies(self) -> list[dict]:
        return [a.to_dict() for a in self.bundle().anomalies]

    def lobo(self, use_residual_ai: bool = True) -> dict:
        with self._lock:
            key = self._version
            hit = self._lobo_cache.get(key)
            if hit is not None:
                return hit
            b = self.bundle()
            details = self.repo.all_details()
            res = leave_one_batch_out(details, b.fits, use_residual_ai=use_residual_ai)
            if b.corrector is not None:
                b.corrector.enabled = res.gate_passed
                b.corrector.gate_note = res.verdict
            payload = res.to_dict()
            self._lobo_cache[key] = payload
            return payload


def _removability(k: float) -> str:
    if k < 0.15:
        return "易去除"
    if k < 0.40:
        return "中等"
    if k < 0.75:
        return "困難"
    return "偏析法無效"


def _padded(values: list[float], frac: float, lo_min: float | None = None) -> tuple[float, float]:
    lo, hi = min(values), max(values)
    pad = max((hi - lo) * frac, abs(hi) * 0.05, 1e-6)
    out_lo = lo - pad
    if lo_min is not None:
        out_lo = max(out_lo, lo_min)
    return (float(out_lo), float(hi + pad))


_SERVICE: AnalysisService | None = None
_SERVICE_LOCK = threading.Lock()


def get_service() -> AnalysisService:
    global _SERVICE
    with _SERVICE_LOCK:
        if _SERVICE is None:
            _SERVICE = AnalysisService()
        return _SERVICE


def reset_service() -> None:
    global _SERVICE
    with _SERVICE_LOCK:
        _SERVICE = None
