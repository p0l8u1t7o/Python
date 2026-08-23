"""端對端測試：合成資料 → 擬合 → 映射 → 最佳化 → API。

最重要的一條是 test_recovers_true_keff_end_to_end：整套流程對已知真值的
還原能力。它是所有「模型可信」主張的根據。
"""

from __future__ import annotations

import numpy as np
import pytest

from expanalysis.data.synthetic import SyntheticConfig, generate_dataset, true_keff
from expanalysis.fitting import fit_batch
from expanalysis.ml import detect_anomalies, fit_keff_mapping, suggest_next_batches


@pytest.fixture(scope="module")
def dataset():
    cfg = SyntheticConfig(n_batches=20)
    details, truth = generate_dataset(cfg)
    fits = {d.batch.batch_id: fit_batch(d) for d in details}
    return cfg, details, truth, fits


def test_recovers_true_keff_end_to_end(dataset):
    """已知真實 k_eff → 生成含雜訊與設限的曲線 → 反解，中位誤差應 < 5%。"""
    cfg, details, truth, fits = dataset
    by_id = {r["batch_id"]: r for r in truth["batches"]}
    errs = {}
    for bid, per_el in fits.items():
        if by_id[bid]["anomaly"]:
            continue                     # 刻意注入的異常批次不列入還原度評估
        for el, f in per_el.items():
            tv = by_id[bid]["true_keff"][el]
            errs.setdefault(el, []).append((f.k_eff - tv) / tv)
    for el, vals in errs.items():
        med = abs(np.median(vals))
        assert med < 0.05, f"{el} 的中位相對誤差 {med:.1%} 過大"


def test_mapping_predicts_in_range_accurately(dataset):
    """映射在資料涵蓋範圍內的預測誤差中位數應 < 5%。"""
    cfg, details, truth, fits = dataset
    by_id = {d.batch.batch_id: d.batch for d in details}
    truth_by_id = {r["batch_id"]: r for r in truth["batches"]}
    rows = [{"batch_id": bid, "element": el, "k_eff": f.k_eff, "k_se": None,
             "speed_mm_hr": by_id[bid].speed_mm_hr, "temp_c": by_id[bid].temp_c}
            for bid, per in fits.items() for el, f in per.items()
            if not truth_by_id[bid]["anomaly"]]
    mapping = fit_keff_mapping(rows)

    for el in mapping.elements:
        errs = []
        for bid, b in by_id.items():
            if truth_by_id[bid]["anomaly"]:
                continue
            tv = true_keff(el, b.speed_mm_hr, truth_by_id[bid]["temp_actual_c"], cfg)
            pv = float(mapping[el].predict(b.speed_mm_hr, b.temp_c, return_ci=False)[0])
            errs.append((pv - tv) / tv)
        assert abs(np.median(errs)) < 0.05, f"{el}: {np.median(errs):+.1%}"


def test_mapping_recovers_slope_sign(seeded_service):
    """delta/D 必須為正——速率越快純化越差，這是 BPS 的基本結論。

    這裡刻意走**服務層**而不是直接呼叫 fit_keff_mapping：服務層會先偵測異常、
    把高嚴重度批次排除後再重擬映射。下一條測試證明少了這一步就會出錯。
    """
    mapping = seeded_service.bundle().mapping
    for el in mapping.elements:
        assert mapping[el].bps.delta_over_d > 0, el


def test_one_corrupted_batch_can_flip_the_slope(dataset):
    """為什麼需要「先排除異常再擬映射」的兩階段設計。

    取樣位置頭尾顛倒的那一批會讓 k_eff 被推到上限 0.999。只要一筆這樣的
    資料混進去，整條 BPS 回歸線就會被拉歪——某些元素的 delta/D 甚至變成負的
    （代表「速率越快純化越好」，與物理相反）。這條測試把這個風險釘住。
    """
    cfg, details, truth, fits = dataset
    by_id = {d.batch.batch_id: d.batch for d in details}
    rows = [{"batch_id": bid, "element": el, "k_eff": f.k_eff, "k_se": None,
             "speed_mm_hr": by_id[bid].speed_mm_hr, "temp_c": by_id[bid].temp_c}
            for bid, per in fits.items() for el, f in per.items()]
    dirty = fit_keff_mapping(rows)
    bad_ids = set(truth["injected_anomalies"])
    clean = fit_keff_mapping([r for r in rows if r["batch_id"] not in bad_ids])

    assert all(clean[el].bps.delta_over_d > 0 for el in clean.elements)
    assert all(clean[el].bps.r2 > dirty[el].bps.r2 - 1e-9 for el in clean.elements)


def test_confidence_band_widens_outside_data(dataset):
    """外插區的不確定區間必須比內插區寬，否則這個區間沒有意義。"""
    cfg, details, truth, fits = dataset
    by_id = {d.batch.batch_id: d.batch for d in details}
    rows = [{"batch_id": bid, "element": el, "k_eff": f.k_eff, "k_se": None,
             "speed_mm_hr": by_id[bid].speed_mm_hr, "temp_c": by_id[bid].temp_c}
            for bid, per in fits.items() for el, f in per.items()]
    mapping = fit_keff_mapping(rows)
    m = mapping[mapping.elements[0]]
    v_lo, v_hi = m.x_train[:, 0].min(), m.x_train[:, 0].max()
    t_mid = float(np.median(m.x_train[:, 1]))
    _, in_std = m.predict_z((v_lo + v_hi) / 2, t_mid)
    _, out_std = m.predict_z(v_hi * 2.5, t_mid)
    assert out_std[0] > in_std[0]
    assert not m.in_training_range(v_hi * 2.5, t_mid)[0]
    assert m.in_training_range((v_lo + v_hi) / 2, t_mid)[0]


def test_detects_injected_anomalies(seeded_service, dataset):
    """刻意注入的兩種異常（熱電偶飄移、取樣位置顛倒）都必須被抓到。

    熱電偶飄移是「所有元素同方向偏移約 1.5 個標準差」——逐元素的門檻永遠
    抓不到它，必須靠批次層級的跨元素一致性規則。這條測試守住那條規則。
    """
    _, _, truth, _ = dataset
    findings = seeded_service.anomalies()
    flagged = {f["batch_id"] for f in findings if f["severity"] in ("high", "medium")}
    for bid, kind in truth["injected_anomalies"].items():
        assert bid in flagged, f"{bid}（{kind}）未被偵測到"


def test_anomalous_batch_is_excluded_from_mapping(seeded_service, dataset):
    """高嚴重度異常必須被排除在映射訓練集之外，且系統要明說排除了什麼。"""
    _, _, truth, _ = dataset
    excluded = {b for b, _ in seeded_service._excluded}
    assert excluded, "應該至少排除一批"
    assert excluded <= set(truth["injected_anomalies"]), \
        f"排除了非注入的批次：{excluded - set(truth['injected_anomalies'])}"
    assert any("排除" in w for w in seeded_service.bundle().warnings)


def test_bayesopt_needs_enough_observations():
    out = suggest_next_batches([{"speed_mm_hr": 1, "temp_c": 180,
                                 "n_passes": 8, "yield_frac": 0.3}])
    assert out["suggestions"] == []
    assert out["notes"]


def test_bayesopt_returns_distinct_suggestions(dataset):
    cfg, details, truth, fits = dataset
    rng = np.random.default_rng(0)
    obs = [{"speed_mm_hr": float(v), "temp_c": float(t), "n_passes": 8,
            "yield_frac": float(0.7 * np.exp(-0.25 * v) + 0.02 * rng.normal())}
           for v, t in zip(np.linspace(1, 6, 10), np.linspace(170, 200, 10))]
    out = suggest_next_batches(obs, (0.5, 8.0), (165.0, 205.0), (6, 8, 10),
                               n_suggest=3)
    assert len(out["suggestions"]) == 3
    keys = {(s["speed_mm_hr"], s["temp_c"], s["n_passes"]) for s in out["suggestions"]}
    assert len(keys) == 3, "三個建議不該落在同一點"


# ── API 層 ─────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def client(seeded_service):
    from fastapi.testclient import TestClient
    from expanalysis.api.app import create_app
    import expanalysis.service as service_mod
    service_mod._SERVICE = seeded_service
    return TestClient(create_app())


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] and body["checks"]["database"]["ok"]


def test_overview_and_keff(client):
    ov = client.get("/api/analysis/overview").json()
    assert ov["n_batches"] == 20
    assert set(ov["elements"]) == {"Cu", "Fe", "Ni", "Sn"}
    rows = client.get("/api/analysis/keff?element=Cu").json()
    assert len(rows) == 20 and all(r["element"] == "Cu" for r in rows)


def test_simulate_and_optimize(client):
    r = client.post("/api/simulate", json={"speed_mm_hr": 2.0, "temp_c": 185,
                                           "n_passes": 8})
    assert r.status_code == 200
    p = r.json()["physics"]
    assert 0.0 <= p["yield_nominal"] <= 1.0
    assert p["yield_pessimistic"] <= p["yield_nominal"] <= p["yield_optimistic"]

    g = client.post("/api/optimize/grid", json={"throughput_weight": 0.0}).json()
    assert g["best_robust"]["in_training_range"] is True
    assert g["best_robust"]["yield_pessimistic"] <= g["best_robust"]["yield_nominal"]


@pytest.mark.parametrize("payload,field", [
    ({"speed_mm_hr": -1, "temp_c": 185, "n_passes": 8}, "speed_mm_hr"),
    ({"speed_mm_hr": 2, "temp_c": 20, "n_passes": 8}, "temp_c"),
    ({"speed_mm_hr": 2, "temp_c": 185, "n_passes": 0}, "n_passes"),
])
def test_simulate_validation_errors(client, payload, field):
    r = client.post("/api/simulate", json=payload)
    assert r.status_code == 422
    body = r.json()
    assert body["ok"] is False and field in body["error"]["message"]


def test_nan_is_serialized_as_null_not_500(client):
    """NaN 不是合法 JSON。若不消毒，端點會變成 500，使用者只會看到
    「伺服器錯誤」而不知道真正的意思是「這個數字算不出來」。"""
    r = client.post("/api/optimize/suggest", json={"n_suggest": 2})
    assert r.status_code == 200
    assert "NaN" not in r.text and "Infinity" not in r.text


def test_assistant_template_mode_answers_with_real_numbers(client):
    r = client.post("/api/assistant/chat", json={"question": "整體狀況如何？"})
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "template"
    assert "get_overview" in body["tools_used"]
    assert "20 個批次" in body["answer"]


def test_unknown_batch_returns_404(client):
    r = client.get("/api/batches/NOT-A-BATCH")
    assert r.status_code == 404
    assert r.json()["ok"] is False
