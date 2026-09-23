"""
量測不變性與重複性驗證 (成像條件對策第五層)

輸入：同一樣品、同一視野，以不同拍攝條件 (管電壓、功率、曝光) 或重複拍攝的多張影像的分析結果
      (序列化後的 dict，即 result.json 的內容；已存檔的結果也可直接重新驗證)。
輸出：
  - 影像層級：各張的整體結果 (例如晶片偏移) 與張間最大差異，對照容許值判定是否通過。
  - 物件層級：兩兩配對同一物件 (以模組宣告的 repeat_anchor 圓心、相似變換對位)，
    比較 repeat_keys 量測值的差異 (重拍雜訊) 與相關係數。
  - 成像條件：各張的拍攝參數與品質指標 (成像條件指紋)。
"""
import itertools

import numpy as np

from . import plugin
from .geometry import similarity_lsq


def _module(result, module_id):
    return next((m for m in result["modules"] if m["module_id"] == module_id), None)


def pair_compare(m1, m2, anchor, keys, first_radius=15.0, match_radius=1.5):
    """兩張影像同一模組的逐物件比較；無法對位 (視野不同) 時回傳 None"""
    f1 = [f for f in m1["findings"] if f["used"] and anchor in f["geometry"]]
    f2 = [f for f in m2["findings"] if f["used"] and anchor in f["geometry"]]
    if len(f1) < 10 or len(f2) < 10:
        return None
    q1 = np.array([[f["geometry"][anchor]["x"], f["geometry"][anchor]["y"]] for f in f1])
    q2 = np.array([[f["geometry"][anchor]["x"], f["geometry"][anchor]["y"]] for f in f2])
    D = np.hypot(q1[:, None, 0] - q2[None, :, 0], q1[:, None, 1] - q2[None, :, 1])
    j, ok = D.argmin(1), D.min(1) < first_radius
    if ok.sum() < 0.5 * min(len(f1), len(f2)):
        return None
    M = similarity_lsq(q1[ok], q2[j[ok]])
    pr = q1 @ M[:, :2].T + M[:, 2]
    D = np.hypot(pr[:, None, 0] - q2[None, :, 0], pr[:, None, 1] - q2[None, :, 1])
    j, ok = D.argmin(1), D.min(1) < match_radius
    if ok.sum() < 0.5 * min(len(f1), len(f2)):
        return None
    idx = np.flatnonzero(ok)
    out = dict(n=int(len(idx)), scale_ppm=float((np.hypot(M[0, 0], M[1, 0]) - 1) * 1e6),
               align_residual_px=float(np.median(D.min(1)[ok])), keys={})
    for k in keys:
        a = np.array([f1[i]["measurements"][k] for i in idx])
        b = np.array([f2[j[i]]["measurements"][k] for i in idx])
        corr = float(np.corrcoef(a, b)[0, 1]) if a.std() > 0 and b.std() > 0 else None
        out["keys"][k] = dict(repeat_noise=float((a - b).std() / np.sqrt(2)), object_sd=float(a.std()), corr=corr,
                              mean_diff=float((a - b).mean()))
    return out


def invariance(results, module_id, tolerance_px):
    """
    results：分析結果 dict 清單 (同一視野)。
    回傳 dict：images (各張結果與條件)、spread (影像層級最大差異)、pairs、passed。
    """
    cls = plugin.get(module_id)
    rows = []
    for r in results:
        m = _module(r, module_id)
        vec = (m["summary"] or {}).get(cls.summary_vector) if m else None
        rows.append(dict(name=r["image"]["name"], kind=r["image"]["kind"], quality=r["quality"]["level"],
                         acquisition=r["acquisition"]["params"],
                         fingerprint={k: v for k, v in r["quality"]["metrics"].items()
                                      if k.startswith("image.") or k in (f"{module_id}.contrast",
                                                                          f"{module_id}.edge_width_px")},
                         status=m["status"] if m else "missing",
                         dx=vec["dx"] if vec else None, dy=vec["dy"] if vec else None, se=vec["se"] if vec else None))
    valid = [x for x in rows if x["dx"] is not None]
    spread = None
    if len(valid) >= 2:
        dx = np.array([x["dx"] for x in valid])
        dy = np.array([x["dy"] for x in valid])
        spread = dict(dx=float(dx.max() - dx.min()), dy=float(dy.max() - dy.min()),
                      max_pairwise=float(max(np.hypot(a["dx"] - b["dx"], a["dy"] - b["dy"])
                                             for a, b in itertools.combinations(valid, 2))),
                      mean_dx=float(dx.mean()), mean_dy=float(dy.mean()))
    pairs = []
    for (i, a), (k, b) in itertools.combinations(enumerate(results), 2):
        ma, mb = _module(a, module_id), _module(b, module_id)
        if ma is None or mb is None:
            continue
        c = pair_compare(ma, mb, cls.repeat_anchor, cls.repeat_keys)
        pairs.append(dict(a=a["image"]["name"], b=b["image"]["name"], result=c))
    passed = spread is not None and spread["max_pairwise"] <= tolerance_px and len(valid) == len(rows)
    return dict(module_id=module_id, tolerance_px=tolerance_px, images=rows, spread=spread, pairs=pairs,
                passed=bool(passed))


def to_markdown(v, locale_t):
    """驗證報告 (Markdown)；locale_t 為語系取字函式"""
    L = [f"# {locale_t('validation.title')}", "",
         f"- {locale_t('validation.module')}: {locale_t('module.' + v['module_id'])}",
         f"- {locale_t('validation.tolerance')}: {v['tolerance_px']:.3f} px",
         f"- {locale_t('validation.result')}: **{locale_t('validation.passed' if v['passed'] else 'validation.failed')}**",
         "", f"## {locale_t('validation.images')}", "",
         "| # | " + " | ".join(locale_t(f"validation.col.{c}") for c in ("image", "kind", "quality", "dx", "dy", "se",
                                                                            "acquisition")) + " |",
         "|---|---|---|---|---|---|---|---|"]
    def num(z, fmt="+.3f"):
        return "-" if z is None else format(z, fmt)

    for i, x in enumerate(v["images"], 1):
        acq = ", ".join(f"{locale_t('acquisition.' + k)}={val}" for k, val in x["acquisition"].items()
                        if k != "extra") or "-"
        L.append(f"| {i} | {x['name']} | {locale_t('image.kind.' + x['kind'])} | {locale_t('quality.' + x['quality'])} | "
                 f"{num(x['dx'])} | {num(x['dy'])} | "
                 f"{num(x['se'], '.3f')} | {acq} |")
    if v["spread"]:
        s = v["spread"]
        L += ["", f"{locale_t('validation.spread')}: dx {s['dx']:.3f} px, dy {s['dy']:.3f} px, "
                  f"{locale_t('validation.max_pairwise')} {s['max_pairwise']:.3f} px"]
    L += ["", f"## {locale_t('validation.fingerprint')}", ""]
    keys = sorted({k for x in v["images"] for k in x["fingerprint"]})
    L += [f"| {locale_t('validation.col.image')} | " + " | ".join(locale_t("metric." + k) for k in keys) + " |",
          "|---|" + "---|" * len(keys)]
    for x in v["images"]:
        L.append(f"| {x['name']} | " + " | ".join(f"{x['fingerprint'].get(k, float('nan')):.4g}" for k in keys) + " |")
    L += ["", f"## {locale_t('validation.pairs')}", ""]
    for p in v["pairs"]:
        c = p["result"]
        if c is None:
            L.append(f"- {p['a']} / {p['b']}: {locale_t('validation.not_same_fov')}")
            continue
        parts = [f"{k}: {locale_t('validation.repeat_noise')} {d['repeat_noise']:.3f} px, "
                 f"{locale_t('validation.object_sd')} {d['object_sd']:.3f} px, {locale_t('validation.corr')} "
                 f"{'-' if d['corr'] is None else format(d['corr'], '.2f')}" for k, d in c["keys"].items()]
        L.append(f"- {p['a']} / {p['b']}: {locale_t('validation.matched')} {c['n']}, "
                 f"{locale_t('validation.scale_diff')} {c['scale_ppm']:+.0f} ppm; " + "; ".join(parts))
    return "\n".join(L) + "\n"
