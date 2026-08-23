"""本地模板模式的中文回覆組裝。

所有數字直接取自工具回傳的結構化結果，這一層只負責把它們放進句子裡，
**不做任何運算**（連百分比換算都只是 ×100 的格式化）。
"""

from __future__ import annotations


def _pct(v, nd: int = 1) -> str:
    return "—" if v is None else f"{float(v) * 100:.{nd}f}%"


def _num(v, nd: int = 4) -> str:
    return "—" if v is None else f"{float(v):.{nd}f}"


def render_tool_result(tool: str, r: dict) -> str:
    if "error" in r:
        return f"查詢失敗：{r['error']}\n\n（本回覆為本地模板模式；未設定 LLM API 金鑰時系統會自動退回此模式，數字仍完全正確。）"

    fn = _RENDERERS.get(tool)
    body = fn(r) if fn else "已取得資料，但本地模板模式沒有對應的呈現方式。"
    return body + "\n\n_本回覆由本地模板模式生成（未使用外部 LLM）。所有數字均來自物理模型與擬合結果。_"


def _overview(r: dict) -> str:
    if r.get("empty"):
        return "資料庫目前沒有任何批次。請先匯入 CSV，或在「資料」頁產生合成資料集。"
    lines = [
        f"目前共 {r['n_batches']} 個批次、{r['n_measurements']} 個量測點"
        f"（其中 {r['n_censored']} 點低於檢測極限，已以設限資料處理）。",
        "",
        "**各元素的偏析可去除性**（k_eff 越低越容易除）：",
    ]
    for el, v in r.get("keff_summary", {}).items():
        bps = v.get("bps") or {}
        lines.append(
            f"- {el}：k_eff 中位數 {_num(v['median'])}"
            f"（範圍 {_num(v['min'])} ~ {_num(v['max'])}）→ **{v['removable']}**；"
            f"BPS 擬合 k0={_num(bps.get('k0'))}、δ/D={_num(bps.get('delta_over_d'), 3)}、"
            f"R²={_num(bps.get('r2'), 3)}"
        )
    ys = r.get("yield_stats") or {}
    lines += [
        "",
        f"6N 得料率（門檻：總雜質 {r.get('threshold_ppm')} ppm）："
        f"平均 {_pct(ys.get('mean'))}、中位數 {_pct(ys.get('median'))}、"
        f"最佳 {_pct(ys.get('max'))}。",
        f"製程涵蓋範圍：速率 {r['speed_range'][0]}~{r['speed_range'][1]} mm/hr、"
        f"溫度 {r['temp_range'][0]}~{r['temp_range'][1]} °C、"
        f"純化次數 {r['pass_range'][0]}~{r['pass_range'][1]} 次。",
    ]
    ac = r.get("anomaly_counts") or {}
    if sum(ac.values()):
        lines.append(f"資料稽核：高嚴重度 {ac.get('high', 0)} 項、"
                     f"中 {ac.get('medium', 0)} 項、低 {ac.get('low', 0)} 項，"
                     f"詳見「資料稽核」頁。")
    return "\n".join(lines)


def _batches(r: dict) -> str:
    lines = [f"共 {r['n_total']} 個批次，列出前 {len(r['batches'])} 筆：", "",
             "| 批次 | 日期 | 速率 mm/hr | 溫度 °C | 次數 | 得料率 |",
             "|---|---|---|---|---|---|"]
    for b in r["batches"]:
        lines.append(f"| {b['batch_id']} | {b['run_date'] or '—'} | {b['speed_mm_hr']} | "
                     f"{b['temp_c']} | {b['n_passes']} | {_pct(b.get('yield_frac'))} |")
    return "\n".join(lines)


def _batch(r: dict) -> str:
    b = r["batch"]
    w = r.get("window") or {}
    lines = [
        f"**批次 {b['batch_id']}**（{b.get('run_date') or '日期未記錄'}）",
        f"製程條件：速率 {b['speed_mm_hr']} mm/hr、溫度 {b['temp_c']} °C、"
        f"純化 {b['n_passes']} 次、熔區 {b['zone_len_mm']} mm / 錠長 {b['ingot_len_mm']} mm"
        f"（l/L = {_num(b.get('zone_len_frac'), 3)}）、氣氛 {b.get('atmosphere')}。",
        "",
        f"6N 得料率 **{_pct(r.get('yield_frac'))}**；高純區為 x/L "
        f"{_num(w.get('head_cut_frac'), 3)} ~ {_num(w.get('tail_cut_frac'), 3)}，"
        f"雜質濃縮區自 x/L {_num(w.get('concentrate_start_frac'), 3)} 起。"
        f"切點由 **{w.get('limiting_element') or '—'}** 決定。",
        "",
        "**各元素擬合結果**：",
    ]
    for el, v in (r.get("elements") or {}).items():
        ci = v.get("k_ci") or [None, None]
        ci_txt = f"（95% CI {_num(ci[0])}~{_num(ci[1])}）" if ci[0] is not None else ""
        lines.append(f"- {el}：k_eff = {_num(v['k_eff'])} {ci_txt}，C0 = {v['c0_ppm']} ppm，"
                     f"{v['n_points']} 點中 {v['n_censored']} 點低於檢測極限。{v['interpretation']}。")
        if v.get("note"):
            lines.append(f"  - ⚠ {v['note']}")
    for a in r.get("anomalies") or []:
        lines.append(f"\n⚠ **資料稽核（{a['severity']}）**：{a['reasons'][0]}")
    return "\n".join(lines)


def _compare(r: dict) -> str:
    a, b, d = r["batch_a"], r["batch_b"], r["param_diff"]
    lines = [
        f"**{b['batch_id']} vs {a['batch_id']}**",
        f"得料率：{_pct(a.get('yield_frac'))} → {_pct(b.get('yield_frac'))}",
        f"製程差異：速率 {a['speed_mm_hr']} → {b['speed_mm_hr']} mm/hr（{d['speed_mm_hr']:+g}）、"
        f"溫度 {a['temp_c']} → {b['temp_c']} °C（{d['temp_c']:+g}）、"
        f"次數 {a['n_passes']} → {b['n_passes']}（{d['n_passes']:+d}）。",
        "",
        "| 元素 | k_eff (A) | k_eff (B) | 實際變化 | 模型預期 | 無法解釋 |",
        "|---|---|---|---|---|---|",
    ]
    for el, v in (r.get("elements") or {}).items():
        lines.append(
            f"| {el} | {_num(v['k_eff_a'])} | {_num(v['k_eff_b'])} | "
            f"{v['k_eff_diff']:+.4f} | "
            f"{('%+.4f' % v['expected_diff_from_model']) if v.get('expected_diff_from_model') is not None else '—'} | "
            f"{('%+.4f' % v['unexplained']) if v.get('unexplained') is not None else '—'} |")
    lines += ["", "「模型預期」是依速率與溫度差異、由 BPS/GP 映射推算的 k_eff 變化。"
                  "若「無法解釋」的部分接近 0，代表這次差異可以完全由製程參數說明；"
                  "若明顯不為 0，就要往量測或製程偏移的方向查。"]
    return "\n".join(lines)


def _mapping(r: dict) -> str:
    bps = r.get("bps") or {}
    lines = [
        f"**{r['element']} 的製程參數映射**",
        f"BPS 線性化：ln(1/k_eff − 1) = ln(1/k0 − 1) − (δ/D)·v",
        f"- 平衡分配係數 k0 = {_num(bps.get('k0'))}",
        f"- 斜率 δ/D = {_num(bps.get('delta_over_d'), 4)} hr/mm"
        f"（標準誤 {_num(bps.get('slope_se'), 4)}）",
        f"- R² = {_num(bps.get('r2'), 3)}，樣本數 {bps.get('n_points')}",
        f"- 高斯過程：{'已啟用' if r.get('gp_used') else '未啟用（批次數不足，使用線性模型）'}",
        f"- 歷史速率涵蓋範圍：{r['v_range_observed'][0]} ~ {r['v_range_observed'][1]} mm/hr",
        "",
        f"在溫度 {r.get('temp_used_for_curve')} °C 下，k_eff 隨速率的變化：",
        "",
        "| 速率 mm/hr | k_eff | 95% 區間 |",
        "|---|---|---|",
    ]
    for p in r.get("k_at_v", []):
        lines.append(f"| {p['v']} | {_num(p['k'])} | {_num(p['k_lo'])} ~ {_num(p['k_hi'])} |")
    if bps.get("linearity_note"):
        lines += ["", f"⚠ {bps['linearity_note']}"]
    return "\n".join(lines)


def _predict(r: dict) -> str:
    c, w = r["conditions"], r.get("window") or {}
    lines = [
        f"**條件：速率 {c['speed_mm_hr']} mm/hr、溫度 {c['temp_c']} °C、"
        f"純化 {c['n_passes']} 次**",
        "",
        f"預測 6N 得料率：**{_pct(r['yield_nominal'])}**"
        f"（樂觀 {_pct(r['yield_optimistic'])} / 悲觀 {_pct(r['yield_pessimistic'])}）",
        f"高純區 x/L {_num(w.get('head_cut_frac'), 3)} ~ {_num(w.get('tail_cut_frac'), 3)}；"
        f"雜質濃縮區自 x/L {_num(w.get('concentrate_start_frac'), 3)} 起。"
        f"限制元素為 {w.get('limiting_element') or '—'}。",
        "",
        "各元素預測 k_eff：",
    ]
    for el, k in (r.get("k_eff") or {}).items():
        ci = (r.get("k_ci") or {}).get(el) or [None, None]
        lines.append(f"- {el}：{_num(k)}（95% CI {_num(ci[0])} ~ {_num(ci[1])}）")
    if not r.get("in_training_range"):
        lines += ["", "⚠ 此條件落在歷史批次涵蓋範圍之外，屬於外插預測，"
                      "不確定度大幅上升，AI 修正已自動停用。"]
    for w_ in r.get("warnings") or []:
        lines.append(f"⚠ {w_}")
    return "\n".join(lines)


def _recommend(r: dict) -> str:
    def block(title, s, extra=""):
        if not s:
            return f"**{title}**：無\n"
        return (f"**{title}**\n"
                f"- 速率 {s['speed_mm_hr']} mm/hr、溫度 {s['temp_c']} °C、"
                f"純化 {s['n_passes']} 次\n"
                f"- 預測得料率 {_pct(s['yield_nominal'])}"
                f"（悲觀 {_pct(s['yield_pessimistic'])}）\n"
                f"- 限制元素：{s.get('limiting_element') or '—'}"
                f"{'；在歷史資料範圍內' if s.get('in_training_range') else '；⚠ 落在外插區'}\n"
                + (f"- {extra}\n" if extra else ""))

    pa = r.get("pass_advice") or {}
    lines = [
        f"在 {r['n_evaluated']} 組參數組合上做了物理模擬，結果如下。",
        "",
        block("可直接執行的建議（穩健）", r.get("best_robust"),
              "此建議只在歷史資料涵蓋範圍內挑選，並以悲觀情境排序，是可以直接下給產線的一組。"),
        block("理論最高得料率", r.get("best")),
        block("產能導向建議", r.get("best_throughput"),
              (r.get("best_throughput") or {}).get("rationale", "")),
    ]
    if pa:
        lines += [
            "**純化次數建議**",
            f"- 建議跑 **{pa.get('recommended_passes')}** 次即可達到可達最大得料率"
            f"（{_pct(pa.get('best_yield'))}）的 95%",
            f"- 第 {pa.get('saturation_pass')} 次之後每多跑一趟，得料率增加不到 0.5 個百分點",
            f"- 分布形狀約在第 {pa.get('ultimate_pass')} 次收斂到極限分布，之後再做完全沒有增益",
            "",
        ]
    for n in r.get("notes") or []:
        lines.append(f"⚠ {n}")
    return "\n".join(lines)


def _suggest(r: dict) -> str:
    if not r.get("suggestions"):
        return "\n".join(["目前無法給出建議：", ""] + [f"- {n}" for n in r.get("notes", [])])
    lines = [f"依目前 {r['n_observations']} 批資料（最佳得料率 "
             f"{_pct(r.get('best_observed_yield'))}），建議接下來這幾批：", ""]
    for s in r["suggestions"]:
        lines += [
            f"**第 {s['rank']} 批**：速率 {s['speed_mm_hr']} mm/hr、"
            f"溫度 {s['temp_c']} °C、純化 {s['n_passes']} 次",
            f"- {s['rationale']}",
            "",
        ]
    lines += [f"_{n}_" for n in r.get("notes", [])]
    return "\n".join(lines)


def _anomalies(r: dict) -> str:
    if not r.get("findings"):
        return "資料稽核沒有發現異常。"
    lines = [f"共 {r['n']} 項稽核發現：", ""]
    for f in r["findings"]:
        lines.append(f"**[{f['severity'].upper()}] {f['batch_id']} / {f['element']}**")
        for reason in f["reasons"]:
            lines.append(f"- {reason}")
        if f.get("suggested_action"):
            lines.append(f"- 建議動作：{f['suggested_action']}")
        lines.append("")
    return "\n".join(lines)


def _validation(r: dict) -> str:
    if not r.get("n_points"):
        return r.get("verdict") or "資料不足，無法執行交叉驗證。"
    lines = [
        f"**留一批交叉驗證**（{r['n_batches']} 折、{r['n_points']} 個未設限測點）",
        "",
        "| 指標 | 純物理 | 物理 + AI |",
        "|---|---|---|",
        f"| 平均絕對誤差 (ppm) | {_num(r['physics_mae_ppm'], 4)} | {_num(r.get('ai_mae_ppm'), 4)} |",
        f"| 最大誤差 (ppm) | {_num(r['physics_max_ppm'], 4)} | {_num(r.get('ai_max_ppm'), 4)} |",
        f"| 對數空間平均誤差 | {_num(r['physics_mae_log'], 4)} | {_num(r.get('ai_mae_log'), 4)} |",
        "",
        f"**結論**：{r.get('verdict')}",
    ]
    return "\n".join(lines)


_RENDERERS = {
    "get_overview": _overview,
    "list_batches": _batches,
    "get_batch": _batch,
    "compare_batches": _compare,
    "get_parameter_mapping": _mapping,
    "predict_profile": _predict,
    "recommend_parameters": _recommend,
    "suggest_next_experiments": _suggest,
    "get_anomalies": _anomalies,
    "get_validation": _validation,
}
