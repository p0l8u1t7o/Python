"""
Flip-Chip X 光互動標註工具 (網頁版)

功能：
    1. 匯入 X 光影像 (tif/png/jpg/bmp)，用同目錄 FlipChipShift.py 的演算法量測，
       把「晶片矩形 / 金屬凸塊圓 / 基板焊點圓」三類結果疊在影像上。
    2. 使用者在網頁上框選 / 套索圈選物件，重新指定類別 (晶片、金屬凸塊、基板焊點、忽略)，
       也可以手動新增漏檢的物件或刪除誤檢。標註結果存在 data/labels/<id>.json。
    3. 匯出「演算法結果 + 使用者分類 + 差異清單」的 JSON 與 Markdown，
       作為與語言模型討論演算法優化的基準文件。
    4. 依「同一片晶片的凸塊大小一致、凸塊落在焊點內」做品質篩選，對每個主要晶片矩形
       穩健估計整體位移 (晶片要移動多少才會和焊點重合)，被篩掉的位點在疊圖上淡化。

啟動：
    python app.py [--port 8002] [--data D:/data/xray]
    瀏覽器開 http://127.0.0.1:8002/
"""
import argparse
import copy
import datetime as dt
import json
import os
import uuid

import cv2
import numpy as np
from flask import Flask, jsonify, render_template, request, send_from_directory, abort

import FlipChipShift as F   # 同層目錄的演算法核心

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

ALLOWED_EXT = {".tif", ".tiff", ".png", ".jpg", ".jpeg", ".bmp"}
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
P0 = copy.deepcopy(F.P)          # 演算法參數基準，每次分析前還原再套 --scale
CLASS_NAMES = {"die": "晶片", "bump": "金屬凸塊", "pad": "基板焊點", "ignore": "忽略"}


def _shift(sh):
    if not sh:
        return None
    out = {k: (_f(v, 3) if isinstance(v, float) else v) for k, v in sh.items() if k != "corr_um"}
    if sh.get("corr_um"):
        out["corr_um"] = [_f(sh["corr_um"][0], 1), _f(sh["corr_um"][1], 1)]
    return out


def _range(rn):
    return {k: (_f(v, 3) if isinstance(v, float) else v) for k, v in rn.items()} if rn else None


def _variants(vs):
    if not vs:
        return None
    return {name: (dict(corr_dx=_f(sh["corr_dx"], 3), corr_dy=_f(sh["corr_dy"], 3), n_in=sh["n_in"], n_used=sh["n_used"]) if sh else None)
            for name, sh in vs.items()}


def _f(v, nd=2):
    """numpy / float 轉成可 JSON 化的數字；NaN 轉 None"""
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return v
    if v != v:
        return None
    return round(v, nd)


def run_algorithm(path, scale=1.0, limit=5.0, px_um=None, roi=None):
    """跑 FlipChipShift.process_image，整理成前端要的 JSON；roi=(x,y,w,h) 只算該區域"""
    F.P.clear()
    F.P.update(copy.deepcopy(P0))
    F.apply_scale(scale)
    res = F.process_image(path, px_um, roi=roi)
    H, W = res["gray"].shape
    regions = []
    for rg in res["regions"]:
        regions.append(dict(
            id=int(rg["id"]), parent=int(rg.get("parent", 0)), level=int(rg["level"]), thr=_f(rg["thr"], 1),
            x=int(rg["x"]), y=int(rg["y"]), w=int(rg["w"]), h=int(rg["h"]), fill=_f(rg["fill"]),
            n_sites=int(rg.get("n_sites", 0)), n_two_level=int(rg.get("n_two_level", 0)), kind=rg.get("kind", ""),
            mean_dx=_f(rg.get("mean_dx")), mean_dy=_f(rg.get("mean_dy")), mean_mag=_f(rg.get("mean_mag")),
            coherence=_f(rg.get("coherence")), t_stat=_f(rg.get("t_stat"), 1),
            rot_deg=_f(rg.get("rot_deg"), 3), verdict=rg.get("verdict", ""), level_verdict=rg.get("level_verdict", ""),
            contrast=_f(rg.get("contrast"), 1), primary=bool(rg.get("primary")), n_used=int(rg.get("n_used", 0)),
            shift=_shift(rg.get("shift")), shift_two=_shift(rg.get("shift_two")),
            shift_range=_range(rg.get("shift_range")), shift_variants=_variants(rg.get("shift_variants")),
        ))
    sites = []
    for s in res["sites"]:
        p, b = s["pad"], s["bump"]
        sites.append(dict(
            id=int(s["id"]), region=int(s.get("region", 0)), cluster=int(s.get("cluster", 0)), type=s["kind"],
            pad=dict(x=_f(p["x"]), y=_f(p["y"]), r=_f(p["r"]), rms=_f(p["rms"]), cov=_f(p["cov"])),
            bump=(dict(x=_f(b["x"]), y=_f(b["y"]), r=_f(b["r"]), rms=_f(b["rms"]), cov=_f(b["cov"])) if b else None),
            dx=_f(s.get("dx")), dy=_f(s.get("dy")), d=_f(s.get("d")), sep=_f(s.get("sep")),
            sep_local=_f(s.get("sep_local")), resid_c=_f(s.get("resid_c")),
            depth=_f(p["bg_lv"] - p["disc_lv"], 1), note=s.get("note", ""),
            mode=s.get("mode", ""), lobe_span=_f(s.get("lobe_span"), 0), lobe_depth=_f(s.get("lobe_depth")),
            used=bool(s.get("used")), reject=s.get("reject", ""),
            shift_inlier=(None if s.get("shift_inlier") is None else bool(s.get("shift_inlier"))),
        ))
    clusters = []
    for c in res["clusters"]:
        clusters.append({k: (_f(v, 3) if isinstance(v, float) else v) for k, v in c.items()})
    two = [s for s in sites if s["type"] == "two-level"]
    d = np.array([s["d"] for s in two]) if two else np.array([])
    summary = dict(
        width=W, height=H, candidates=int(res["n_cand"]), sites=len(sites), two_level=len(two),
        single=len(sites) - len(two),
        offset_median=_f(np.median(d)) if len(d) else None, offset_p95=_f(np.percentile(d, 95)) if len(d) else None,
        offset_max=_f(d.max()) if len(d) else None, over_limit=int((d > limit).sum()) if len(d) else 0,
        global_transform={k: _f(v, 3) for k, v in res["gt"].items()} if res["gt"] else None,
        regions=len(regions), clusters=len(clusters),
        shift_regions=[f"D{r['id']}" for r in regions if r["level_verdict"] in ("高", "中", "高(低可信)")],
        n_used=int(res.get("n_used", 0)),
        modes={k: int(v) for k, v in __import__("collections").Counter(s.get("mode", "-") for s in res["sites"]).items()},
        roi=list(res["roi"]) if res.get("roi") else None,
        die_shifts=[dict(region=int(rg["id"]), bbox=[int(rg["x"]), int(rg["y"]), int(rg["w"]), int(rg["h"])],
                         shift=_shift(rg["shift"]), shift_two=_shift(rg.get("shift_two")),
                         shift_range=_range(rg.get("shift_range")), shift_variants=_variants(rg.get("shift_variants")))
                    for rg in res.get("die_shifts", [])],
        shift_all=_shift(res.get("shift_all")), shift_all_range=_range(res.get("shift_all_range")),
        shift_all_variants=_variants(res.get("shift_all_variants")), variant_names=res.get("variant_names", []),
        sizes=[{k: (_f(v, 2) if isinstance(v, float) else v) for k, v in row.items()} for row in F.size_summary(res["sites"], res["regions"])],
        params=dict(scale=scale, limit=limit, px_um=px_um, pad_r=list(F.P["pad_r"]), min_sep=F.P["min_sep"],
                    lo_frac=F.P["lo_frac"], hi_frac=F.P["hi_frac"], gauss_sigma=F.P["gauss_sigma"],
                    q_r_tol=F.P["q_r_tol"], q_depth_ratio=F.P["q_depth_ratio"], shift_tol=F.P["shift_tol"]),
    )
    return dict(regions=regions, sites=sites, clusters=clusters, summary=summary), res


def create_app(data_dir):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
    up_dir = os.path.join(data_dir, "uploads")
    img_dir = os.path.join(data_dir, "display")
    res_dir = os.path.join(data_dir, "results")
    lab_dir = os.path.join(data_dir, "labels")
    for d in (up_dir, img_dir, res_dir, lab_dir):
        os.makedirs(d, exist_ok=True)

    def _safe_id(image_id):
        if not image_id or any(ch not in "0123456789abcdef" for ch in image_id):
            abort(404)
        return image_id

    def _load_json(path):
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    # ------------------------------------------------------------ 頁面與影像
    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/img/<path:name>")
    def display_image(name):
        return send_from_directory(img_dir, name)

    # ------------------------------------------------------------ 分析
    @app.route("/api/analyze", methods=["POST"])
    def analyze():
        f = request.files.get("image")
        if f is None or not f.filename:
            return jsonify(error="沒有收到影像檔"), 400
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in ALLOWED_EXT:
            return jsonify(error=f"不支援的格式 {ext}"), 400
        try:
            scale = float(request.form.get("scale", 1.0))
            limit = float(request.form.get("limit", 5.0))
            px_um = float(request.form.get("px_um") or 0) or None
        except ValueError:
            return jsonify(error="scale / limit / px_um 必須是數字"), 400
        image_id = uuid.uuid4().hex
        src = os.path.join(up_dir, image_id + ext)
        f.save(src)
        try:
            data, res = run_algorithm(src, scale, limit, px_um)
        except Exception as e:  # noqa: BLE001
            return jsonify(error=f"分析失敗: {e}"), 500
        # 顯示用影像：去噪後 (演算法看到的) 與只做中值 5 的原圖，各存一張 JPEG
        den = np.clip(res["den"], 0, 255).astype(np.uint8)
        cv2.imwrite(os.path.join(img_dir, image_id + ".jpg"), den, [cv2.IMWRITE_JPEG_QUALITY, 88])
        raw = cv2.medianBlur(res["gray"], 5)
        cv2.imwrite(os.path.join(img_dir, image_id + "_raw.jpg"), raw, [cv2.IMWRITE_JPEG_QUALITY, 85])
        data["image"] = dict(id=image_id, name=f.filename, width=data["summary"]["width"],
                             height=data["summary"]["height"], display=f"/img/{image_id}.jpg",
                             raw=f"/img/{image_id}_raw.jpg", analyzed_at=dt.datetime.now().isoformat(timespec="seconds"),
                             upload=image_id + ext, parent=None, roi=None)
        with open(os.path.join(res_dir, image_id + ".json"), "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        return jsonify(data)

    @app.route("/api/reanalyze/<image_id>", methods=["POST"])
    def reanalyze(image_id):
        """對已上傳的影像重新分析：可帶 roi=[x,y,w,h] 只算該區域；結果另存為新的 id，顯示影像沿用原本的"""
        parent = _load_json(os.path.join(res_dir, _safe_id(image_id) + ".json"))
        if parent is None:
            abort(404)
        body = request.get_json(silent=True) or {}
        root = parent["image"].get("parent") or parent["image"]["id"]
        root_data = _load_json(os.path.join(res_dir, root + ".json")) or parent
        upload = root_data["image"].get("upload")
        src = os.path.join(up_dir, upload) if upload else None
        if not src or not os.path.exists(src):
            return jsonify(error="找不到原始上傳檔，請重新匯入"), 404
        try:
            scale = float(body.get("scale", 1.0)); limit = float(body.get("limit", 5.0))
            px_um = float(body.get("px_um") or 0) or None
            roi = body.get("roi")
            if roi is not None:
                roi = [int(round(float(v))) for v in roi]
                if len(roi) != 4 or roi[2] < 40 or roi[3] < 40:
                    return jsonify(error="ROI 太小 (至少 40x40 px)"), 400
        except (TypeError, ValueError):
            return jsonify(error="參數格式錯誤"), 400
        try:
            data, res = run_algorithm(src, scale, limit, px_um, roi)
        except Exception as e:  # noqa: BLE001
            return jsonify(error=f"分析失敗: {e}"), 500
        new_id = uuid.uuid4().hex
        data["image"] = dict(root_data["image"], id=new_id, parent=root, roi=roi,
                             analyzed_at=dt.datetime.now().isoformat(timespec="seconds"))
        with open(os.path.join(res_dir, new_id + ".json"), "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        return jsonify(data)

    @app.route("/api/results")
    def list_results():
        items = []
        for name in sorted(os.listdir(res_dir)):
            if not name.endswith(".json"):
                continue
            d = _load_json(os.path.join(res_dir, name))
            if not d:
                continue
            lab = _load_json(os.path.join(lab_dir, name))
            items.append(dict(id=d["image"]["id"], name=d["image"]["name"] + (f"  [ROI {tuple(d['image']['roi'])}]" if d["image"].get("roi") else ""),
                              analyzed_at=d["image"].get("analyzed_at", ""),
                              sites=d["summary"]["sites"], regions=d["summary"]["regions"],
                              labeled=(len([o for o in (lab or {}).get("objects", []) if o.get("user_class") or o.get("deleted") or o.get("added")])
                                       if lab else 0)))
        items.sort(key=lambda x: x["analyzed_at"], reverse=True)
        return jsonify(items)

    @app.route("/api/results/<image_id>")
    def get_result(image_id):
        d = _load_json(os.path.join(res_dir, _safe_id(image_id) + ".json"))
        if d is None:
            abort(404)
        d["labels"] = _load_json(os.path.join(lab_dir, image_id + ".json"))
        return jsonify(d)

    # ------------------------------------------------------------ 標註存取
    @app.route("/api/labels/<image_id>", methods=["GET", "POST"])
    def labels(image_id):
        path = os.path.join(lab_dir, _safe_id(image_id) + ".json")
        if request.method == "GET":
            return jsonify(_load_json(path) or dict(image_id=image_id, objects=[], notes=""))
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get("objects"), list):
            return jsonify(error="格式錯誤：需要 {objects: [...]}"), 400
        body["image_id"] = image_id
        body["saved_at"] = dt.datetime.now().isoformat(timespec="seconds")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(body, fh, ensure_ascii=False, indent=1)
        return jsonify(ok=True, saved_at=body["saved_at"], count=len(body["objects"]))

    # ------------------------------------------------------------ 匯出給語言模型
    @app.route("/api/export/<image_id>", methods=["POST"])
    def export(image_id):
        data = _load_json(os.path.join(res_dir, _safe_id(image_id) + ".json"))
        if data is None:
            abort(404)
        labels_body = request.get_json(silent=True) or _load_json(os.path.join(lab_dir, image_id + ".json")) or {}
        pkg = build_export(data, labels_body)
        return jsonify(pkg)

    return app


# ---------------------------------------------------------------------------
# 匯出內容
# ---------------------------------------------------------------------------
def algorithm_objects(data):
    """把演算法結果攤平成物件清單 (與前端相同的 oid 規則)：D# 晶片矩形、P# 焊點圓、B# 凸塊圓"""
    objs = []
    for rg in data["regions"]:
        objs.append(dict(oid=f"D{rg['id']}", alg_class="die", shape="rect", x=rg["x"], y=rg["y"], w=rg["w"], h=rg["h"],
                         meta=dict(parent=rg["parent"], level=rg["level"], fill=rg["fill"], n_sites=rg["n_sites"],
                                   n_two_level=rg["n_two_level"], mean_dx=rg["mean_dx"], mean_dy=rg["mean_dy"],
                                   coherence=rg["coherence"], t_stat=rg["t_stat"], verdict=rg["verdict"])))
    for s in data["sites"]:
        base = dict(site=s["id"], region=s["region"], cluster=s["cluster"], type=s["type"], dx=s["dx"], dy=s["dy"],
                    offset=s["d"], edge_sep=s["sep"], depth=s["depth"], note=s["note"],
                    used=s.get("used"), reject=s.get("reject", ""), shift_inlier=s.get("shift_inlier"))
        objs.append(dict(oid=f"P{s['id']}", alg_class="pad", shape="circle", cx=s["pad"]["x"], cy=s["pad"]["y"], r=s["pad"]["r"],
                         meta=dict(base, fit_rms=s["pad"]["rms"], edge_cov=s["pad"]["cov"])))
        if s["bump"]:
            objs.append(dict(oid=f"B{s['id']}", alg_class="bump", shape="circle", cx=s["bump"]["x"], cy=s["bump"]["y"], r=s["bump"]["r"],
                             meta=dict(base, fit_rms=s["bump"]["rms"], edge_cov=s["bump"]["cov"])))
    return objs


def build_export(data, labels_body):
    objs = {o["oid"]: o for o in algorithm_objects(data)}
    user = {o["oid"]: o for o in labels_body.get("objects", []) if o.get("oid")}
    merged = []
    for oid, o in objs.items():
        u = user.get(oid, {})
        m = dict(o)
        m["user_class"] = u.get("user_class") or None
        m["deleted"] = bool(u.get("deleted"))
        m["final_class"] = "deleted" if m["deleted"] else (m["user_class"] or o["alg_class"])
        m["agree"] = (not m["deleted"]) and (m["user_class"] in (None, o["alg_class"]))
        merged.append(m)
    added = []
    for oid, u in user.items():
        if u.get("added") and not u.get("deleted"):
            added.append(dict(oid=oid, alg_class=None, user_class=u.get("user_class"), shape=u.get("shape"),
                              x=u.get("x"), y=u.get("y"), w=u.get("w"), h=u.get("h"),
                              cx=u.get("cx"), cy=u.get("cy"), r=u.get("r"), final_class=u.get("user_class"), added=True))
    # 統計
    conf = {}
    for m in merged:
        conf.setdefault(m["alg_class"], {}).setdefault(m["final_class"], 0)
        conf[m["alg_class"]][m["final_class"]] += 1
    disagreements = [m for m in merged if not m["agree"]]
    s = data["summary"]
    img = data["image"]
    lines = []
    lines.append(f"# Flip-Chip X 光量測：演算法結果 vs 人工分類基準")
    lines.append("")
    lines.append(f"- 影像: {img['name']} ({s['width']}x{s['height']} px)，分析時間 {img.get('analyzed_at', '')}" +
                 (f"，ROI {tuple(s['roi'])}" if s.get("roi") else ""))
    if s.get("modes"):
        lines.append(f"- 位點量測模式: " + ", ".join(f"{k} {v}" for k, v in s["modes"].items()) +
                     "（lobe = 焊點露出弧擬合的雙圓；concentric = 同心兩層；single = 分不出兩層）")
    lines.append(f"- 演算法參數: scale={s['params']['scale']}, pad_r={s['params']['pad_r']}, min_sep={s['params']['min_sep']}, "
                 f"lo/hi_frac={s['params']['lo_frac']}/{s['params']['hi_frac']}, gauss_sigma={s['params']['gauss_sigma']}")
    lines.append(f"- 演算法輸出: 候選 {s['candidates']}、位點 {s['sites']} (two-level {s['two_level']} / single {s['single']})、"
                 f"晶片矩形 {s['regions']}、群 {s['clusters']}")
    if s["offset_median"] is not None:
        lines.append(f"- two-level 偏移量 px: 中位 {s['offset_median']}、P95 {s['offset_p95']}、最大 {s['offset_max']}，"
                     f"超過 {s['params']['limit']} px: {s['over_limit']} 顆")
    if s["global_transform"]:
        g = s["global_transform"]
        lines.append(f"- 全域相似變換 (焊點→凸塊): 平移 ({g['tx']}, {g['ty']}) px, 旋轉 {g['rot_deg']} deg, 縮放 {g['scale']}")
    lines.append("")
    lines.append("## 整體位移估計 (品質篩選後的穩健內點平均；correction = 晶片要移動多少才會和焊點重合)")
    lines.append(f"- 品質篩選後可用位點 {s.get('n_used', 0)} / {s['sites']}（篩選規則：凸塊半徑與同矩形中位數差 <= {s['params'].get('q_r_tol', 0.12):.0%}、"
                 f"深度 >= 中位數 x {s['params'].get('q_depth_ratio', 0.5)}、凸塊落在焊點內、擬合可靠、不貼影像邊）")
    for dsh in s.get("die_shifts", []):
        sh = dsh["shift"]
        lines.append(f"- 晶片 D{dsh['region']} bbox {tuple(dsh['bbox'])}: 凸塊-焊點偏移 ({sh['dx']:+.2f}, {sh['dy']:+.2f}) px → "
                     f"**晶片需位移 ({sh['corr_dx']:+.2f}, {sh['corr_dy']:+.2f}) px**" +
                     (f" = ({sh['corr_um'][0]:+.1f}, {sh['corr_um'][1]:+.1f}) um" if sh.get("corr_um") else "") +
                     f"，內點 {sh['n_in']}/{sh['n_used']} ({sh['ratio']:.0%})，±{sh['se']} px，信心 {sh['grade']}" +
                     (f"，旋轉 {sh['rot_deg']:+.3f} deg，縮放 {sh.get('scale_ppm', 0):+.0f} ppm (邊角差 {sh.get('edge_var', 0)} px)" if sh.get("rot_deg") is not None else ""))
        if dsh.get("shift_two"):
            t2 = dsh["shift_two"]
            lines.append(f"  - 只用 two-level 位點: ({t2['corr_dx']:+.2f}, {t2['corr_dy']:+.2f}) px，內點 {t2['n_in']}/{t2['n_used']}，信心 {t2['grade']}")
        rn = dsh.get("shift_range")
        if rn:
            vs = "; ".join(f"{k} ({v['corr_dx']:+.2f}, {v['corr_dy']:+.2f}) n={v['n_in']}" if v else f"{k} -" for k, v in (dsh.get("shift_variants") or {}).items())
            lines.append(f"  - 前處理敏感度 ({rn['n_variants']} 種去噪): dx {rn['dx_min']:+.2f}~{rn['dx_max']:+.2f}, dy {rn['dy_min']:+.2f}~{rn['dy_max']:+.2f} → "
                         f"系統 ±({rn['sys_dx']:.2f}, {rn['sys_dy']:.2f}) px，合併不確定度 ±{rn['total']:.2f} px [{vs}]")
    if not s.get("die_shifts"):
        lines.append("- 沒有主要晶片矩形達到最少可用位點數")
    if s.get("shift_all"):
        sa = s["shift_all"]
        lines.append(f"- 全圖所有可用位點: 晶片需位移 ({sa['corr_dx']:+.2f}, {sa['corr_dy']:+.2f}) px，內點 {sa['n_in']}/{sa['n_used']} ({sa['ratio']:.0%})，信心 {sa['grade']}")
    lines.append("")
    lines.append("## 圓尺寸統計 (px；直徑)")
    lines.append("| 矩形 | 位點 | 有凸塊 | 可用 | 焊點直徑 中位 (最小~最大) | 凸塊直徑 中位 (最小~最大) | 可用凸塊直徑 中位 (最小~最大) |")
    lines.append("|---|---|---|---|---|---|---|")
    g = lambda v: "-" if v is None else f"{v:.1f}"
    for row in s.get("sizes", []):
        lines.append(f"| {('D%d' % row['region']) if row['region'] else '外'} | {row['n']} | {row['n_bump']} | {row['n_used']} | "
                     f"{g(row['pad_d_med'])} ({g(row['pad_d_min'])}~{g(row['pad_d_max'])}) | {g(row['bump_d_med'])} ({g(row['bump_d_min'])}~{g(row['bump_d_max'])}) | "
                     f"{g(row['bump_d_used_med'])} ({g(row['bump_d_used_min'])}~{g(row['bump_d_used_max'])}) |")
    lines.append("- 每個圓的圓心 / 半徑 / 直徑 / 面積 (px) 在 JSON 的 objects 內 (cx, cy, r)。")
    lines.append("")
    lines.append("## 類別定義")
    lines.append("- die (晶片): 背景灰階圖上比周圍暗、填滿率高的矩形區域 (可巢狀，parent 為包住它的外層矩形)")
    lines.append("- pad (基板焊點): 位點斜坡 75% 等高線擬合的外圓")
    lines.append("- bump (金屬凸塊): 位點斜坡 25% 等高線擬合的內圓；two-level 表示內外圓半徑差夠大、偏移量可信；single 表示分不出兩層")
    lines.append("")
    lines.append("## 晶片矩形")
    lines.append("| 矩形 | parent | 層 | bbox (x,y,w,h) | 填滿率 | 邊界對比 | 主要 | 位點 | 可用 | 需位移 (dx,dy) | 內點 | 信心 | 人工 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for rg in data["regions"]:
        u = user.get(f"D{rg['id']}", {})
        uc = "刪除" if u.get("deleted") else CLASS_NAMES.get(u.get("user_class") or "", "") or "同意"
        sh = rg.get("shift")
        corr = f"({sh['corr_dx']:+.2f},{sh['corr_dy']:+.2f})" if sh else "-"
        inl = f"{sh['n_in']}/{sh['n_used']}" if sh else "-"
        lines.append(f"| D{rg['id']} | {('D%d' % rg['parent']) if rg['parent'] else '-'} | {rg['level']} | ({rg['x']},{rg['y']},{rg['w']},{rg['h']}) | "
                     f"{rg['fill']} | {rg.get('contrast', '-')} | {'*' if rg.get('primary') else ''} | {rg['n_sites']} | {rg.get('n_used', 0)} | {corr} | {inl} | "
                     f"{sh['grade'] if sh else '-'} | {uc} |")
    lines.append("")
    lines.append("## 人工分類統計 (列 = 演算法類別，欄 = 人工最終類別)")
    classes = ["die", "pad", "bump", "ignore", "deleted"]
    lines.append("| 演算法 \\ 人工 | " + " | ".join(classes) + " | 同意率 |")
    lines.append("|---|" + "---|" * (len(classes) + 1))
    for ac in ("die", "pad", "bump"):
        row = conf.get(ac, {})
        tot = sum(row.values())
        agree = row.get(ac, 0)
        lines.append(f"| {ac} | " + " | ".join(str(row.get(c, 0)) for c in classes) +
                     f" | {agree}/{tot} ({(100.0 * agree / tot if tot else 0):.0f}%) |")
    # 品質篩選與人工刪除的一致性 (只看焊點物件，一顆位點算一次)
    qa = dict(both_keep=0, alg_keep_user_del=0, alg_del_user_keep=0, both_del=0)
    for m in merged:
        if m["alg_class"] != "pad":
            continue
        used = bool(m.get("meta", {}).get("used"))
        if used and not m["deleted"]: qa["both_keep"] += 1
        elif used and m["deleted"]: qa["alg_keep_user_del"] += 1
        elif not used and not m["deleted"]: qa["alg_del_user_keep"] += 1
        else: qa["both_del"] += 1
    n_labeled = sum(1 for m in merged if m["user_class"] or m["deleted"])
    lines.append("")
    lines.append(f"- 人工動過的物件: {n_labeled}，新增物件: {len(added)}，與演算法不同的: {len(disagreements)}")
    lines.append(f"- 品質篩選 vs 人工 (位點)：兩者都保留 {qa['both_keep']}、演算法保留但人工刪除 {qa['alg_keep_user_del']}、"
                 f"演算法篩掉但人工保留 {qa['alg_del_user_keep']}、兩者都排除 {qa['both_del']}")
    if labels_body.get("notes"):
        lines.append(f"- 使用者備註: {labels_body['notes']}")
    lines.append("")
    lines.append("## 與演算法不同的物件 (最多列 60 筆，完整清單在 JSON)")
    lines.append("| 物件 | 演算法 | 人工 | 位置 | 半徑/尺寸 | 篩選 | 量測 (type, offset, edge_sep, depth, note) |")
    lines.append("|---|---|---|---|---|---|---|")
    for m in disagreements[:60]:
        if m["shape"] == "circle":
            pos, size = f"({m['cx']},{m['cy']})", f"r={m['r']}"
        else:
            pos, size = f"({m['x']},{m['y']})", f"{m['w']}x{m['h']}"
        mt = m.get("meta", {})
        meas = (f"{mt.get('type', '')}, {mt.get('offset', '')}, {mt.get('edge_sep', '')}, {mt.get('depth', '')}, {mt.get('note', '')}"
                if m["alg_class"] != "die" else mt.get("verdict", ""))
        q = ("used" if mt.get("used") else (mt.get("reject") or "-")) if m["alg_class"] != "die" else "-"
        lines.append(f"| {m['oid']} | {m['alg_class']} | {m['final_class']} | {pos} | {size} | {q} | {meas} |")
    if added:
        lines.append("")
        lines.append("## 人工新增 (演算法漏檢) 的物件")
        lines.append("| 物件 | 類別 | 形狀 | 位置 | 尺寸 |")
        lines.append("|---|---|---|---|---|")
        for a in added:
            if a["shape"] == "circle":
                lines.append(f"| {a['oid']} | {a['user_class']} | circle | ({a['cx']},{a['cy']}) | r={a['r']} |")
            else:
                lines.append(f"| {a['oid']} | {a['user_class']} | rect | ({a['x']},{a['y']}) | {a['w']}x{a['h']} |")
    lines.append("")
    lines.append("## 請語言模型協助的方向")
    lines.append("1. 根據不同意/漏檢/誤檢的分佈 (位置、半徑、深度、edge_sep、note)，指出演算法哪個階段 (偵測 / 圓擬合 / two-level 判定 / 晶片矩形) 最需要調整，並建議具體參數或方法。")
    lines.append("2. 若某些物件人工歸為 bump 但演算法只給 single，說明可能的影像原因與可行的量測改法。")
    lines.append("3. 評估晶片矩形分割是否符合實際晶片邊界，提出更穩健的邊緣特徵做法。")
    markdown = "\n".join(lines)
    package = dict(
        image=img, summary=s, regions=data["regions"], clusters=data["clusters"], quality_vs_user=qa,
        objects=merged + added, confusion=conf, disagreements=[m["oid"] for m in disagreements],
        user_notes=labels_body.get("notes", ""), exported_at=dt.datetime.now().isoformat(timespec="seconds"),
    )
    return dict(markdown=markdown, json=package)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Flip-Chip X 光互動標註工具")
    ap.add_argument("--port", type=int, default=8002)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--data", default=os.path.join(BASE_DIR, "data"), help="上傳 / 結果 / 標註的存放資料夾")
    args = ap.parse_args()
    application = create_app(args.data)
    print(f"資料夾: {args.data}\n開啟 http://{args.host}:{args.port}/")
    application.run(host=args.host, port=args.port, debug=False, threaded=True)
