"""AI 教導助手：上傳影像＋圈選 ROI＋自然語言提示 → 自動合成可執行的檢測流程。

產物就是標準 graph JSON（validate_graph 把關），跑在既有引擎上；
本模組只是「會寫流程的助手」，不是另一套執行路徑。

- analysis.py：ROI 影像特徵量測（供規則引擎自動調參、也給 LLM 當摘要）
- intents.py：提示詞＋ROI 形狀＋特徵 → 意圖（規則引擎）
- synth.py：意圖 → graph 合成（自動掛 ROI、自動參數）
- llm.py：Claude 供應器（可選安裝 anthropic、設定 API 金鑰才啟用）
- service.py：編排（分析 → 生成 → 驗證 → 試跑 → 迭代微調）
- api.py：/vision/agent/* 端點
"""
