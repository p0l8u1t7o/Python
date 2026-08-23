"""合成資料產生器 — demo 與方法驗證用。

用途有兩個，缺一不可：

1. **方法驗證**：以已知的真實 k0 與 delta/D 生成資料，再讓整套流程反解，
   檢查能不能還原。還原不了就代表方法有問題，這比在真實資料上「看起來
   合理」可靠得多。tests/ 就是靠這個把關。

2. **對客戶 demo**：在拿到客戶歷史批次之前，先用合成資料把整套工具跑起來，
   會議上可以實際操作。所有畫面都標示「合成資料」，不會被誤認為實測結果。

真實度設計
----------
  * 各元素有不同的 k0（Cu 最好除、Sn 最難），符合實務觀察
  * 量測誤差為**乘法性**（對數常態），因為 ppm 級分析的相對誤差才是穩定的
  * 低於 LOD 的點標記為左設限，LOD 依分析方法而異（GDMS 比 ICP-MS 低）
  * C0 本身有批間變異（進料不是每批都一樣）
  * 刻意植入兩種異常批次供 L3 異常偵測驗證：
      - 熱電偶飄移：記錄溫度與實際差 25°C
      - 取樣位置記錄錯誤：頭尾顛倒
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..physics.bps import keff_from_bps
from ..physics.multipass import simulate_passes
from .models import Batch, BatchDetail, ElementSpec, Measurement

# 元素的「真實」參數。k0 越小越好除；delta_over_d 越大代表越怕快速凝固。
# 參數選定的依據：
#   * k0 由小到大排 Cu < Fe < Ni < Sn，對應「Cu 最好除、Sn 最難除」的實務觀察
#   * delta/D 隨 k0 增大而減小（k0 接近 1 的元素本來就對速率不敏感）
#   * C0 合計約 11.5 ppm，相當於 4N9 級進料，目標 6N（總雜質 < 1 ppm）
#   * 在 v = 1~6 mm/hr、6~12 passes 的條件下，得料率會落在約 4% ~ 67%，
#     既有明顯的參數敏感度可供最佳化，又不會出現「怎麼調都是 0」的死局
DEFAULT_TRUTH: dict[str, dict[str, float]] = {
    #        k0     delta/D [hr/mm]  C0 [ppm]  LOD(GDMS) [ppm]
    "Cu": {"k0": 0.045, "delta_over_d": 0.42, "c0": 5.0, "lod": 0.005},
    "Fe": {"k0": 0.150, "delta_over_d": 0.30, "c0": 3.0, "lod": 0.010},
    "Ni": {"k0": 0.250, "delta_over_d": 0.24, "c0": 1.5, "lod": 0.010},
    "Sn": {"k0": 0.420, "delta_over_d": 0.15, "c0": 2.0, "lod": 0.005},
}


@dataclass
class SyntheticConfig:
    n_batches: int = 20
    ingot_len_mm: float = 500.0
    zone_len_mm: float = 50.0
    speed_range: tuple[float, float] = (1.0, 6.0)      # mm/hr
    temp_range: tuple[float, float] = (165.0, 205.0)   # °C
    pass_choices: tuple[int, ...] = (4, 6, 8, 10, 12)
    n_sample_points: int = 8
    sample_max_frac: float = 0.92        # 尾端最後 8% 通常已切掉不送驗
    rel_noise: float = 0.12              # 乘法性量測誤差的對數標準差
    c0_batch_cv: float = 0.10            # 進料濃度的批間變異係數
    head_crop_frac: float = 0.03
    beta_t: float = -0.012               # 溫度主效應（越高 → z 越小 → k_eff 越好）
    t_ref: float = 185.0
    inject_anomalies: bool = True
    seed: int = 20250114
    truth: dict[str, dict[str, float]] = field(default_factory=lambda: dict(DEFAULT_TRUTH))
    n_cells: int = 300

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["speed_range"] = list(self.speed_range)
        d["temp_range"] = list(self.temp_range)
        d["pass_choices"] = list(self.pass_choices)
        return d


def true_keff(element: str, speed: float, temp_c: float,
              cfg: SyntheticConfig) -> float:
    """該元素在給定製程條件下的「真實」k_eff。反解驗證的標準答案。"""
    t = cfg.truth[element]
    return float(keff_from_bps(
        speed, t["k0"], t["delta_over_d"],
        temp_c=temp_c, t_ref=cfg.t_ref, beta_t=cfg.beta_t,
    ))


def generate_dataset(cfg: SyntheticConfig | None = None) -> tuple[list[BatchDetail], dict]:
    """產生一組合成批次資料。

    Returns:
        (details, truth_info)
        truth_info 含每批的真實 k_eff、注入的異常清單，供驗證與展示用。
    """
    cfg = cfg or SyntheticConfig()
    rng = np.random.default_rng(cfg.seed)
    elements = list(cfg.truth)

    # 速率用 Latin hypercube 式的分層抽樣，確保涵蓋整個範圍——
    # 純隨機抽樣在 20 批時很容易在某段速率完全沒有點，導致斜率擬不出來。
    edges = np.linspace(*cfg.speed_range, cfg.n_batches + 1)
    speeds = rng.uniform(edges[:-1], edges[1:])
    rng.shuffle(speeds)
    temps = rng.uniform(*cfg.temp_range, cfg.n_batches)
    passes = rng.choice(cfg.pass_choices, cfg.n_batches)

    anomalies: dict[str, str] = {}
    if cfg.inject_anomalies and cfg.n_batches >= 8:
        anomalies[f"IN-{25001 + 3}"] = "thermocouple_drift"
        anomalies[f"IN-{25001 + 7}"] = "position_reversed"

    details: list[BatchDetail] = []
    truth_rows: list[dict] = []

    for i in range(cfg.n_batches):
        bid = f"IN-{25001 + i}"
        speed = float(speeds[i])
        temp_recorded = float(temps[i])
        npass = int(passes[i])
        anomaly = anomalies.get(bid, "")

        # 熱電偶飄移：實際溫度與記錄值差 25°C，模型會看到系統性殘差
        temp_actual = temp_recorded - 25.0 if anomaly == "thermocouple_drift" else temp_recorded

        ks, c0s = [], []
        for el in elements:
            ks.append(true_keff(el, speed, temp_actual, cfg))
            base = cfg.truth[el]["c0"]
            c0s.append(float(base * np.exp(rng.normal(0.0, cfg.c0_batch_cv))))

        res = simulate_passes(
            np.array(ks), cfg.zone_len_mm / cfg.ingot_len_mm, npass,
            c0=np.array(c0s), n_cells=cfg.n_cells, keep_all=False,
        )
        final = res.final                       # (E, N)

        # 取樣位置：頭端較密（純度梯度大的地方資訊量高）
        u = np.linspace(0.0, 1.0, cfg.n_sample_points)
        x_samples = cfg.head_crop_frac + (cfg.sample_max_frac - cfg.head_crop_frac) * (u ** 1.35)

        batch = Batch(
            batch_id=bid,
            run_date=f"2025-{1 + i // 4:02d}-{3 + (i % 4) * 6:02d}",
            ingot_len_mm=cfg.ingot_len_mm, zone_len_mm=cfg.zone_len_mm,
            speed_mm_hr=round(speed, 2), temp_c=round(temp_recorded, 1),
            n_passes=npass, atmosphere="Ar",
            head_crop_frac=cfg.head_crop_frac, analysis_method="GDMS",
            operator="synthetic", notes="合成資料（demo 用，非實測）",
        )

        meas: list[Measurement] = []
        specs: list[ElementSpec] = []
        for e_i, el in enumerate(elements):
            lod = cfg.truth[el]["lod"]
            for x in x_samples:
                x_read = x
                if anomaly == "position_reversed":
                    x_read = cfg.sample_max_frac + cfg.head_crop_frac - x
                idx = min(cfg.n_cells - 1, int(x * cfg.n_cells))
                true_val = float(final[e_i, idx])
                obs = true_val * float(np.exp(rng.normal(0.0, cfg.rel_noise)))
                censored = obs < lod
                meas.append(Measurement(
                    batch_id=bid, element=el, x_norm=round(float(x_read), 4),
                    value_ppm=round(lod if censored else obs, 6),
                    lod_ppm=lod, censored=censored,
                    sample_id=f"{bid}-{el}-{x_read:.2f}",
                ))
            specs.append(ElementSpec(batch_id=bid, element=el,
                                     c0_ppm=round(c0s[e_i], 4), c0_measured=True))

        details.append(BatchDetail(batch=batch, measurements=meas, element_specs=specs))
        truth_rows.append({
            "batch_id": bid,
            "speed_mm_hr": round(speed, 3),
            "temp_recorded_c": round(temp_recorded, 1),
            "temp_actual_c": round(temp_actual, 1),
            "n_passes": npass,
            "anomaly": anomaly,
            "true_keff": {el: round(k, 5) for el, k in zip(elements, ks)},
            "c0_ppm": {el: round(c, 4) for el, c in zip(elements, c0s)},
        })

    truth_info = {
        "config": cfg.to_dict(),
        "elements": elements,
        "element_truth": {el: dict(cfg.truth[el]) for el in elements},
        "batches": truth_rows,
        "injected_anomalies": anomalies,
        "disclaimer": "本資料集為合成資料，用於方法驗證與 demo，非實際製程量測結果。",
    }
    return details, truth_info


def seed_database(repo, cfg: SyntheticConfig | None = None, clear: bool = True) -> dict:
    """產生合成資料並寫入資料庫。回傳 truth_info。"""
    cfg = cfg or SyntheticConfig()
    details, truth = generate_dataset(cfg)
    if clear:
        repo.clear_all()
    for d in details:
        repo.upsert_batch(d.batch)
        repo.replace_measurements(d.batch.batch_id, d.measurements)
        repo.replace_element_specs(d.batch.batch_id, d.element_specs)
    return truth
