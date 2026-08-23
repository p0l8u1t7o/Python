"""AI 層（L1~L4）。

設計原則：**物理模型負責算數字，AI 負責補物理沒說到的、選下一步、跟人溝通。**

    L1 residual  殘差學習    有風險，四道護欄 + 交叉驗證通過才上線（選配）
    L2 gp_map    高斯過程    取代線性回歸，純升級、無代價
    L3 anomaly   異常偵測    不參與預測，只保護準確度，零風險
    L4 bayesopt  貝氏最佳化  只建議做什麼實驗，準確度仍來自真實資料，零風險

每一層都可以獨立關閉並退回下一層；關閉後系統仍然完整可用。
"""

from .gp_map import KeffMapping, GPKeffModel, fit_keff_mapping
from .anomaly import AnomalyFinding, detect_anomalies
from .bayesopt import BOSuggestion, suggest_next_batches, doe_comparison
from .residual import ResidualCorrector, DualTrackPrediction
from .validation import LOBOResult, leave_one_batch_out

__all__ = [
    "KeffMapping", "GPKeffModel", "fit_keff_mapping",
    "AnomalyFinding", "detect_anomalies",
    "BOSuggestion", "suggest_next_batches", "doe_comparison",
    "ResidualCorrector", "DualTrackPrediction",
    "LOBOResult", "leave_one_batch_out",
]
