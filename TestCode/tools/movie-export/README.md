# 五站 MP4 展示輸出

先在 TestCode 執行 `python tools/movie-export/prepare.py`，再執行 `python tools/movie-export/server.py`。
開啟 `http://127.0.0.1:8782/RobotArmPressSSD/?pause&movie&queue`，點選「輸出完整影片」會依序完成五站。

- 原始網站不變；錄製副本在 `TEMP/movie-site/`，成品與抽查影格在 `TEMP/videos/`，均由 `.gitignore` 排除。
- NVIDIA GPU WebGL 渲染與 NVENC H.264 編碼，1920×1080、30 fps。使用軍規專案既有的 `tools/bin/ffmpeg.exe`。
- 每一步依絕對時間渲染、確認影格順序後送入編碼器，不依賴螢幕更新率。保留完整製程順序，長製程展示加速，短動作延長供觀察。
- 追隨當前產品／正在取放的料件；資訊約 2 秒後淡出。後段包括電盤剖視、元件特寫、整線與穿板接頭。
- PCB 原始模型是五站並行節拍，完整節拍後增加各工位的同時間軸重播；不宣稱追蹤同一片基板經過原模型未建立的多節拍排程。
- 可拖曳預覽時間軸抽查鏡頭。錄製時保持瀏覽器及本機服務運行；中斷後同一服務可從已接收的下一影格接續。
- `python tools/movie-export/verify.py` 以 FFprobe 比對總影格與時間、檢查製程區間完整連續並解碼全片。另在 TEMP 產生抽查圖與驗證 JSON。
- 不覆寫已存在的成品；重新輸出前將舊成品與同名紀錄移至另一個 TEMP 子資料夾，並重新啟動接收器。
