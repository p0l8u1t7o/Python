"""ExpAnalysis — 高純銦金屬偏析純化製程分析平台。

架構分層（由下而上，上層永遠可關閉並退回下層）：

    L0  physics/    Pfann + BPS 物理模型            不可被取代的骨架
    L1  ml.residual 殘差學習（選配、四道護欄）
    L2  ml.gp_map   高斯過程 k_eff = f(T, v, n)
    L3  ml.anomaly  殘差異常偵測
    L4  ml.bayesopt 貝氏最佳化序列實驗設計
    L5  assistant/  LLM 自然語言查詢與報告生成（不參與任何計算）
"""

__version__ = "0.1.0"
