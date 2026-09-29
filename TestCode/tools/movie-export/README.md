# 3D 專案 MP4 展示輸出（2026-09-29 運鏡與穩定性修正版）

先在 TestCode 執行 `python tools/movie-export/prepare.py`，再執行 `python tools/movie-export/server.py`。
開啟 `http://127.0.0.1:8782/RobotArmPressSSD/?pause&movie&queue`，點選「輸出完整影片」會依序完成五站。

- 原始網站不變；錄製副本在 `TEMP/movie-site/`，成品與抽查影格在 `TEMP/videos/`，均由 `.gitignore` 排除。
- GPU WebGL 以 3840×2160 取樣後縮至 1920×1080、30 fps，改善細線與金屬邊緣閃爍。接收器實際試編碼後優先使用 NVENC H.264；不可用時回退 libx264。使用軍規專案既有的 `tools/bin/ffmpeg.exe`。
- 每一步依絕對時間渲染、確認影格順序後送入編碼器，不依賴螢幕更新率。保留完整製程順序，長製程展示加速，短動作延長供觀察。
- 開場 12 秒：依設備外廓自動框入整機，先停留 3 秒，再以 9 秒緩慢拉近。拉遠製程追焦距離，以絕對時間預算並平滑焦點，避免取放對象切換時跳鏡頭。
- 錄製副本使用對數深度及合理 near plane，固定繪圖緩衝區大小，提高陰影解析度並抑制過尖的金屬高光。取像頻閃的製程事件／LED 保留，影片不使用頻閃聚光燈照亮整個場景。
- 資訊約 2 秒後淡出。後段保留電盤剖視、元件與周圍配置、整線、穿板接頭，以短疊化銜接，避免鏡頭穿越桌板。接頭鏡位另檢查中心及周邊遮擋。
- PCB 原始模型是五站並行節拍，先保留完整節拍，再依上／下料軌道、供料震動及植入事件選取細節重播，以原速或更慢展示，不再將完整節拍擠進幾秒造成龍門閃過；不宣稱追蹤同一片基板經過原模型未建立的多節拍排程。
- 可拖曳預覽時間軸抽查鏡頭。錄製時保持瀏覽器及本機服務運行；中斷後同一服務可從已接收的下一影格接續。
- 點選「檢查鏡頭與固定影格」輸出全景、推近、製程及細節抽查圖，並在固定時間重畫 10 次；`python tools/movie-export/audit.py --output TEMP/videos/revised-20260929` 產生 contact sheet 與量化差異。
- `python tools/movie-export/verify.py --output TEMP/videos/revised-20260929` 以 FFprobe 比對總影格與時間、檢查完整製程連續性、解碼全片、檢查黑影格與單影格大面積閃光候選。另在 TEMP 產生抽查圖與驗證 JSON；這些數值不能取代目視檢查運動與局部反光。
- 接收器不直接覆寫成品。重錄使用 `--port 8783 --output-subdir revised-20260929`，於該 port 的頁面錄製；新版通過驗證後才替換舊影片。全部影片、稽核圖與中間檔保持在忽略的 TEMP 中。
- `node --test tools/movie-export/test-camera-path.mjs` 驗證追焦交接不瞬移、不過衝，以及開場停留和推近的連續性。

## WorkpieceMeasurement 單獨輸出

1. `python tools/movie-export/prepare.py --project WorkpieceMeasurement`（只更新此站的 TEMP 錄製副本）。
2. `python tools/movie-export/server.py --port 8786 --output-subdir workpiece-20260929`。
3. 開啟 `http://127.0.0.1:8786/WorkpieceMeasurement/?pause&movie&pip=0`，先按「檢查鏡頭與固定影格」，再按「輸出完整影片」。重新輸出需選擇尚無成品的新資料夾。
4. `python tools/movie-export/audit.py --output TEMP/videos/workpiece-20260929`。
5. `python tools/movie-export/verify.py --output TEMP/videos/workpiece-20260929 --project WorkpieceMeasurement`。

此站保留上方護罩與立柱，開場完整框入機台後緩慢推近，製程以較寬的產品跟隨視角呈現。完整 B 規格合格流程依序播放後，另重播 ST1 夾持取像、ST2 共焦量測、X／Z 拖鏈全行程與光纖補償環，最後展示桌板穿線護口、電盤剖視、PLC／電源與整線配置。所有製程影格使用同一個絕對時間取樣器；重播段在標題註明，不能當作另一件工件或實際節拍。

影片只擷取 3D 畫布與約 2 秒的階段文字，不擷取網頁資訊側欄。輸出使用 4K 超取樣縮至 1080p／30 fps，JSON 保留實際 GPU、編碼器、每段製程時間與影片影格對照。固定時間重畫、全片解碼及時間閃光檢查仍需搭配全尺寸目視抽查，不能據單一指標保證所有細部反光完全不閃。
