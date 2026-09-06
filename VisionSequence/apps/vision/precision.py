"""精度驗證與 GR&R（WP-13）：重複性、再現性、GR&R（AIAG MSA 第 4 版 ANOVA 法）；JSON＋markdown 報告。

三種模式：
- repeatability：同一張影像跑 N 次（`input_image` 固定）→ 各具名數值輸出的 σ／極差；確定性流程理論上 0，非 0 就是演算法本身的不確定性。
- reproducibility：同一件重新取像 N 次（每次向來源要新影像）→ 含取像雜訊與光源波動。
- grr：多件 × 多次（每件 r 次）→ ANOVA：EV（設備變異＝重複性）、PV（零件變異）、GRR、TV、%GR&R、ndc；有公差時另給 %GR&R（對公差）、Cg／Cgk。

只分析數值型的具名輸出（bool 不算）；每個公式都寫進報告，客戶驗收看得到算法。執行不走 runner 佇列（不計統計、不寫 FlowRun、不發 SSE），
與批次測試同一條路：`runner.compiled_for` 編一次、`engine.execute(input_image=)` 逐次跑、跑完 `store.drop_run`。
"""

from __future__ import annotations

import math
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

import numpy as np

MODES = ("repeatability", "reproducibility", "grr")
#: %GR&R 判定（AIAG MSA 4th ed.）：< 10% 優、10～30% 可接受（視應用）、> 30% 不可接受
GRR_EXCELLENT = 10.0
GRR_ACCEPTABLE = 30.0
NDC_MIN = 5


class PrecisionError(Exception):
    pass


def _numeric(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)) and math.isfinite(float(v)):
        return float(v)
    return None


def describe(values: list[float]) -> dict[str, Any]:
    """n、平均、樣本標準差（ddof=1；n<2 為 0）、極差、最小、最大、6σ。"""
    arr = np.asarray(values, dtype=np.float64)
    n = int(arr.size)
    if n == 0:
        return {"n": 0, "mean": None, "std": None, "range": None, "min": None, "max": None, "six_sigma": None}
    std = float(arr.std(ddof=1)) if n > 1 else 0.0
    return {"n": n, "mean": float(arr.mean()), "std": std, "range": float(arr.max() - arr.min()), "min": float(arr.min()), "max": float(arr.max()), "six_sigma": 6.0 * std}


def numeric_outputs(samples: list[dict[str, Any]]) -> tuple[dict[str, list[float]], list[str]]:
    """每次執行的 outputs dict 清單 → {name: [values]}（只收每次都是數值的輸出）；回傳略過的名稱。"""
    names: list[str] = []
    for s in samples:
        for k in s:
            if k not in names:
                names.append(k)
    series: dict[str, list[float]] = {}
    skipped: list[str] = []
    for name in names:
        vals = [_numeric(s.get(name)) for s in samples]
        if vals and all(v is not None for v in vals):
            series[name] = [float(v) for v in vals]  # type: ignore[arg-type]
        else:
            skipped.append(name)
    return series, skipped


def capability(std: float, mean: float, tolerance: float | None, reference: float | None) -> dict[str, Any]:
    """Cg／Cgk（量具能力，AIAG MSA 4th ed. type-1 study 慣例）：Cg = 0.2·T / (6·σ)，Cgk = (0.1·T − |x̄ − ref|) / (3·σ)；≥ 1.33 合格。"""
    out: dict[str, Any] = {}
    if tolerance and tolerance > 0:
        out["cg"] = (0.2 * tolerance) / (6.0 * std) if std > 0 else float("inf")
        if reference is not None:
            out["bias"] = mean - reference
            out["cgk"] = (0.1 * tolerance - abs(mean - reference)) / (3.0 * std) if std > 0 else float("inf")
    return out


def grr_anova(parts: dict[str, list[float]], tolerance: float | None = None) -> dict[str, Any]:
    """單一評估者的 GR&R（AIAG MSA 4th ed. 第 III 章 B 節 ANOVA 法，零件 × 試驗）：
    MS_part = r·Σ(ȳp − ȳ)² / (p − 1)、MS_e = ΣΣ(y − ȳp)² / (p·(r − 1))
    EV = √MS_e、PV = √max(0, (MS_part − MS_e) / r)、GRR = EV（沒有評估者變異）、TV = √(GRR² + PV²)
    %GR&R = 100·GRR / TV、%PV = 100·PV / TV、ndc = ⌊1.41·PV / GRR⌋；有公差 T：%GR&R(tol) = 100·6·GRR / T。
    試驗次數不齊時截到最少的一致（記在 trials）。"""
    keys = list(parts)
    if len(keys) < 2:
        raise PrecisionError("GR&R needs at least two parts")
    r = min(len(parts[k]) for k in keys)
    if r < 2:
        raise PrecisionError("GR&R needs at least two trials per part")
    y = np.array([parts[k][:r] for k in keys], dtype=np.float64)  # (p, r)
    p = len(keys)
    part_means = y.mean(axis=1)
    grand = float(y.mean())
    ms_part = r * float(((part_means - grand) ** 2).sum()) / (p - 1)
    ms_e = float(((y - part_means[:, None]) ** 2).sum()) / (p * (r - 1))
    ev = math.sqrt(max(0.0, ms_e))
    pv = math.sqrt(max(0.0, (ms_part - ms_e) / r))
    grr = ev
    tv = math.sqrt(grr * grr + pv * pv)
    pct_grr = 100.0 * grr / tv if tv > 0 else 0.0
    pct_pv = 100.0 * pv / tv if tv > 0 else 0.0
    ndc = int(math.floor(1.41 * pv / grr)) if grr > 0 else None
    out: dict[str, Any] = {
        "parts": p, "trials": r, "grand_mean": grand, "part_means": {k: float(m) for k, m in zip(keys, part_means)},
        "ms_part": ms_part, "ms_error": ms_e, "ev": ev, "av": 0.0, "grr": grr, "pv": pv, "tv": tv,
        "pct_grr": pct_grr, "pct_pv": pct_pv, "ndc": ndc,
        "verdict": "excellent" if pct_grr < GRR_EXCELLENT else ("acceptable" if pct_grr <= GRR_ACCEPTABLE else "unacceptable"),
        "method": "AIAG MSA 4th ed. ANOVA, one appraiser",
    }
    if tolerance and tolerance > 0:
        out["tolerance"] = tolerance
        out["pct_grr_tolerance"] = 100.0 * 6.0 * grr / tolerance
        out["cg"] = (0.2 * tolerance) / (6.0 * ev) if ev > 0 else float("inf")
    return out


# ---------------------------------------------------------------- 執行
def run_outputs(flow, images: list[np.ndarray | None], *, trigger: str = "precision", timeout_s: float = 30.0, on_progress: Callable[[int, int], None] | None = None) -> tuple[list[dict[str, Any]], list[float]]:
    """把流程對每張影像跑一次（None＝讓流程自己的來源取像），回每次的具名輸出與耗時 ms。不走 runner 佇列。"""
    from apps.vision import engine
    from apps.vision.images import store as image_store
    from apps.vision.runner import runner

    compiled = runner.compiled_for(flow)
    runner._prefetch(compiled)
    outs: list[dict[str, Any]] = []
    durations: list[float] = []
    for i, img in enumerate(images):
        report = engine.execute(
            compiled, flow_id=flow.id, flow_version=flow.version, trigger=trigger, grab=runner._grab, asset_path=runner._asset_path,
            preview=False, input_image=img, run_id=f"prec{uuid.uuid4().hex[:12]}", deadline=time.perf_counter() + timeout_s,
        )
        image_store.drop_run(report.id)
        if report.status == "error":
            raise PrecisionError(f"Run {i + 1} failed: {report.error or 'error'}")
        outs.append(dict(report.outputs))
        durations.append(float(report.duration_ms))
        if on_progress is not None:
            on_progress(i + 1, len(images))
    return outs, durations


def _grab_source(source_id: int | None):
    from apps.vision.sources import grab_by_id, last_error_of

    if source_id is None:
        return None
    img = grab_by_id(source_id)
    if img is None:
        raise PrecisionError(f"Source {source_id} did not return a picture ({last_error_of(source_id) or 'no error reported'})")
    return img


def study(flow, mode: str, *, repeat: int = 30, source_id: int | None = None, parts: dict[str, list[np.ndarray]] | None = None,
          tolerance: dict[str, float] | None = None, reference: dict[str, float] | None = None, on_progress: Callable[[int, int], None] | None = None) -> dict[str, Any]:
    """跑一個精度研究，回 JSON 可序列化的結果（含每個輸出的統計、公式、判定）。"""
    if mode not in MODES:
        raise PrecisionError(f"mode must be one of {', '.join(MODES)}")
    tolerance = tolerance or {}
    reference = reference or {}
    started = time.perf_counter()
    result: dict[str, Any] = {
        "mode": mode, "flow_id": flow.id, "flow_name": flow.name, "flow_version": flow.version, "source_id": source_id,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "outputs": {}, "skipped_outputs": [],
    }
    if mode == "repeatability":
        if repeat < 2:
            raise PrecisionError("repeat must be at least 2")
        img = _grab_source(source_id)
        if img is None:
            # 沒指定來源：先讓流程自己取一張，之後固定用它
            first, _ = run_outputs(flow, [None], timeout_s=60)
            from apps.vision.runner import runner
            from apps.vision.sources import grab_by_id

            sid = _flow_source_id(runner.compiled_for(flow))
            img = grab_by_id(sid) if sid is not None else None
            if img is None:
                raise PrecisionError("The flow has no image source to grab from; pass source_id")
        outs, durations = run_outputs(flow, [img] * repeat, on_progress=on_progress)
        result["repeat"] = repeat
    elif mode == "reproducibility":
        if repeat < 2:
            raise PrecisionError("repeat must be at least 2")
        images: list[np.ndarray | None] = [_grab_source(source_id) for _ in range(repeat)] if source_id is not None else [None] * repeat
        outs, durations = run_outputs(flow, images, on_progress=on_progress)
        result["repeat"] = repeat
    else:
        if not parts or len(parts) < 2:
            raise PrecisionError("GR&R needs at least two parts, each with at least two pictures")
        outs = []
        durations = []
        part_index: list[tuple[str, int]] = []
        total = sum(len(v) for v in parts.values())
        done = 0
        for name, imgs in parts.items():
            if len(imgs) < 2:
                raise PrecisionError(f"Part {name} has fewer than two pictures")
            o, d = run_outputs(flow, list(imgs))
            outs.extend(o)
            durations.extend(d)
            part_index.extend((name, i) for i in range(len(imgs)))
            done += len(imgs)
            if on_progress is not None:
                on_progress(done, total)
        result["parts"] = {name: len(imgs) for name, imgs in parts.items()}
    series, skipped = numeric_outputs(outs)
    result["skipped_outputs"] = skipped
    result["runs"] = len(outs)
    result["duration_ms"] = describe(durations)
    for name, values in series.items():
        entry: dict[str, Any] = {"stats": describe(values), "values": values}
        tol = tolerance.get(name)
        ref = reference.get(name)
        if tol:
            entry["tolerance"] = tol
        if ref is not None:
            entry["reference"] = ref
        if mode in ("repeatability", "reproducibility"):
            st = entry["stats"]
            entry.update(capability(st["std"], st["mean"], tol, ref))
            if tol:
                entry["pct_six_sigma_of_tolerance"] = 100.0 * st["six_sigma"] / tol
        else:
            per_part: dict[str, list[float]] = {}
            for (pname, _i), v in zip(part_index, values):
                per_part.setdefault(pname, []).append(v)
            entry["grr"] = grr_anova(per_part, tol)
            entry["per_part"] = {k: describe(v) for k, v in per_part.items()}
        result["outputs"][name] = entry
    result["elapsed_s"] = round(time.perf_counter() - started, 3)
    result["formulas"] = FORMULAS[mode]
    return result


def _flow_source_id(compiled) -> int | None:
    for cn in compiled.nodes.values():
        params = cn.node.get("params") or {}
        for p in cn.tool.params:
            if p.kind == "source" and params.get(p.key) not in (None, ""):
                try:
                    return int(params[p.key])
                except (TypeError, ValueError):
                    return None
    return None


FORMULAS = {
    "repeatability": [
        "σ = sample standard deviation of the N runs on the same picture (ddof = 1); range = max − min",
        "6σ / T = share of the tolerance consumed by six standard deviations (when a tolerance is given)",
        "Cg = 0.2·T / (6·σ); Cgk = (0.1·T − |mean − reference|) / (3·σ); both ≥ 1.33 pass (AIAG MSA 4th ed., gauge capability)",
    ],
    "reproducibility": [
        "σ = sample standard deviation of the N runs, each on a fresh picture of the same part (ddof = 1); range = max − min",
        "6σ / T = share of the tolerance consumed by six standard deviations (when a tolerance is given)",
        "Cg = 0.2·T / (6·σ); Cgk = (0.1·T − |mean − reference|) / (3·σ); both ≥ 1.33 pass",
    ],
    "grr": [
        "ANOVA, one appraiser (AIAG MSA 4th ed. chapter III section B): MS_part = r·Σ(ȳ_p − ȳ)² / (p − 1); MS_error = ΣΣ(y − ȳ_p)² / (p·(r − 1))",
        "EV (repeatability) = √MS_error; PV (part variation) = √max(0, (MS_part − MS_error) / r); GRR = EV; TV = √(GRR² + PV²)",
        "%GR&R = 100·GRR / TV (< 10% excellent, 10–30% acceptable, > 30% unacceptable); ndc = ⌊1.41·PV / GRR⌋ (≥ 5 acceptable)",
        "With a tolerance T: %GR&R(tolerance) = 100·6·GRR / T; Cg = 0.2·T / (6·EV)",
    ],
}


# ---------------------------------------------------------------- 報告
def _fmt(v: Any, nd: int = 4) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        if math.isinf(v):
            return "∞"
        return f"{v:.{nd}f}"
    return str(v)


def markdown_report(result: dict[str, Any]) -> str:
    """可直接貼進客戶文件的 markdown：標題、方法、每個輸出一張表、公式、判定。"""
    mode = result["mode"]
    title = {"repeatability": "Repeatability study", "reproducibility": "Reproducibility study", "grr": "Gauge R&R study"}[mode]
    lines = [f"# {title} — {result['flow_name']}", "",
             f"- Flow: {result['flow_name']} (id {result['flow_id']}, version {result['flow_version']})",
             f"- Mode: {mode}" + (f", {result['repeat']} runs" if mode != "grr" else f", {len(result.get('parts', {}))} parts × {min(result['parts'].values()) if result.get('parts') else 0} trials"),
             f"- Generated: {result['generated_at']}; total runs {result['runs']}; run time mean {_fmt(result['duration_ms'].get('mean'), 1)} ms",
             ""]
    if not result["outputs"]:
        lines.append("No numeric named outputs were produced by the flow.")
    for name, entry in result["outputs"].items():
        st = entry["stats"]
        lines.append(f"## Output `{name}`")
        lines.append("")
        if mode == "grr":
            g = entry["grr"]
            lines.append("| Metric | Value |")
            lines.append("|---|---|")
            lines.append(f"| Parts × trials | {g['parts']} × {g['trials']} |")
            lines.append(f"| Grand mean | {_fmt(g['grand_mean'])} |")
            lines.append(f"| EV (repeatability, σ) | {_fmt(g['ev'])} |")
            lines.append(f"| PV (part variation, σ) | {_fmt(g['pv'])} |")
            lines.append(f"| GRR (σ) | {_fmt(g['grr'])} |")
            lines.append(f"| TV (total, σ) | {_fmt(g['tv'])} |")
            lines.append(f"| %GR&R (of total variation) | {_fmt(g['pct_grr'], 2)} % — **{g['verdict']}** |")
            lines.append(f"| %PV | {_fmt(g['pct_pv'], 2)} % |")
            lines.append(f"| ndc (distinct categories) | {_fmt(g['ndc'])} {'(≥ 5 acceptable)' if g['ndc'] is not None else ''} |")
            if "tolerance" in g:
                lines.append(f"| Tolerance | {_fmt(g['tolerance'])} |")
                lines.append(f"| %GR&R (of tolerance) | {_fmt(g['pct_grr_tolerance'], 2)} % |")
                lines.append(f"| Cg | {_fmt(g['cg'], 2)} |")
            lines.append("")
            lines.append("| Part | n | mean | σ | range |")
            lines.append("|---|---|---|---|---|")
            for pname, ps in entry["per_part"].items():
                lines.append(f"| {pname} | {ps['n']} | {_fmt(ps['mean'])} | {_fmt(ps['std'])} | {_fmt(ps['range'])} |")
        else:
            lines.append("| Metric | Value |")
            lines.append("|---|---|")
            lines.append(f"| n | {st['n']} |")
            lines.append(f"| Mean | {_fmt(st['mean'])} |")
            lines.append(f"| σ (sample) | {_fmt(st['std'])} |")
            lines.append(f"| Range (max − min) | {_fmt(st['range'])} |")
            lines.append(f"| Min / max | {_fmt(st['min'])} / {_fmt(st['max'])} |")
            lines.append(f"| 6σ | {_fmt(st['six_sigma'])} |")
            if "tolerance" in entry:
                lines.append(f"| Tolerance | {_fmt(entry['tolerance'])} |")
                lines.append(f"| 6σ / tolerance | {_fmt(entry['pct_six_sigma_of_tolerance'], 2)} % |")
                lines.append(f"| Cg | {_fmt(entry.get('cg'), 2)} {'(≥ 1.33 pass)' if entry.get('cg') is not None else ''} |")
            if "cgk" in entry:
                lines.append(f"| Bias (mean − reference) | {_fmt(entry['bias'])} |")
                lines.append(f"| Cgk | {_fmt(entry['cgk'], 2)} (≥ 1.33 pass) |")
        lines.append("")
    if result.get("skipped_outputs"):
        lines.append(f"Non-numeric outputs not analysed: {', '.join(result['skipped_outputs'])}")
        lines.append("")
    lines.append("## Method")
    lines.append("")
    for f in result["formulas"]:
        lines.append(f"- {f}")
    lines.append("")
    return "\n".join(lines)


def check_limits(result: dict[str, Any], max_sigma: dict[str, float] | None = None, max_grr: float | None = None) -> list[str]:
    """CI 門檻：每個輸出的 σ 上限（'*' 代表全部）、%GR&R 上限；回不合格的說明清單（空＝通過）。"""
    failures: list[str] = []
    for name, entry in result["outputs"].items():
        limit = None
        if max_sigma:
            limit = max_sigma.get(name, max_sigma.get("*"))
        if limit is not None and entry["stats"]["std"] is not None and entry["stats"]["std"] > limit:
            failures.append(f"{name}: σ {entry['stats']['std']:.4f} > {limit}")
        if max_grr is not None and "grr" in entry and entry["grr"]["pct_grr"] > max_grr:
            failures.append(f"{name}: %GR&R {entry['grr']['pct_grr']:.2f} > {max_grr}")
    return failures
