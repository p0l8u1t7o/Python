"""批次測試：影像集（BatchSet）＋批次執行（BatchRun）——把每次批量檢測的逐張資料暫存下來，供人員與 AI 助手依資料調參。

- store.py    檔案（ASSET_DIR/batch/<set_id>/NNN.png）、序列化、summary／命中、淘汰、graph 參數差異
- jobs.py     背景執行（engine.execute 直呼、獨立影像快取桶、每張跑完即釋放；自動調參模式）
- insights.py 資料洞察（命中率／混淆矩陣／出錯節點／判定門檻建議／與上一次比較）
- api.py      /vision/batch/... 端點
"""
