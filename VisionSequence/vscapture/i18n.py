"""擷取端介面的多語系：與網頁相同的三種語言（繁體中文、简体中文、English）。

用法：`from vscapture.i18n import tr` → `tr("connection.title")`、`tr("update.found", version="0.2.0")`。
切換語言用 `set_language()`，介面各面板再呼叫自己的 `retranslate()` 重寫文字（不必重開程式）。
文案規範與網頁一致（商用語氣：「點選」「試執行」「您」）；三種語言的 key 必須齊全，由測試把關。
"""

from __future__ import annotations

from typing import Any

#: (代碼, 顯示名稱)；代碼與網頁的 i18n 一致
LANGUAGES: list[tuple[str, str]] = [("zh-Hant", "繁體中文"), ("zh-Hans", "简体中文"), ("en", "English")]
LANGUAGE_CODES = tuple(code for code, _ in LANGUAGES)
DEFAULT_LANGUAGE = "zh-Hant"

_current = DEFAULT_LANGUAGE

TEXTS: dict[str, dict[str, str]] = {
    # ---- 一般 ----
    "app.title": {"zh-Hant": "VisionSequence 擷取端", "zh-Hans": "VisionSequence 采集端", "en": "VisionSequence Capture"},
    "common.ok": {"zh-Hant": "確定", "zh-Hans": "确定", "en": "OK"},
    "common.cancel": {"zh-Hant": "取消", "zh-Hans": "取消", "en": "Cancel"},
    "common.refresh": {"zh-Hant": "重新整理", "zh-Hans": "刷新", "en": "Refresh"},
    "common.close": {"zh-Hant": "關閉", "zh-Hans": "关闭", "en": "Close"},
    "common.none": {"zh-Hant": "—", "zh-Hans": "—", "en": "—"},
    "common.language": {"zh-Hant": "語言", "zh-Hans": "语言", "en": "Language"},
    "common.theme": {"zh-Hant": "外觀", "zh-Hans": "外观", "en": "Theme"},
    "common.themeDark": {"zh-Hant": "深色", "zh-Hans": "深色", "en": "Dark"},
    "common.themeLight": {"zh-Hant": "淺色", "zh-Hans": "浅色", "en": "Light"},
    # ---- 選單 ----
    "menu.file": {"zh-Hant": "檔案", "zh-Hans": "文件", "en": "File"},
    "menu.save": {"zh-Hant": "儲存設定", "zh-Hans": "保存设置", "en": "Save settings"},
    "menu.reload": {"zh-Hant": "重新載入設定", "zh-Hans": "重新载入设置", "en": "Reload settings"},
    "menu.openFolder": {"zh-Hant": "開啟設定資料夾", "zh-Hans": "打开设置文件夹", "en": "Open settings folder"},
    "menu.quit": {"zh-Hant": "結束", "zh-Hans": "退出", "en": "Quit"},
    "menu.settings": {"zh-Hant": "設定", "zh-Hans": "设置", "en": "Settings"},
    "menu.connectionSettings": {"zh-Hant": "連線設定…", "zh-Hans": "连接设置…", "en": "Connection…"},
    "menu.channelSettings": {"zh-Hant": "相機通道…", "zh-Hans": "相机通道…", "en": "Camera channels…"},
    "menu.deliverySettings": {"zh-Hant": "傳送設定…", "zh-Hans": "传送设置…", "en": "Delivery…"},
    "menu.view": {"zh-Hant": "檢視", "zh-Hans": "视图", "en": "View"},
    "menu.log": {"zh-Hant": "記錄", "zh-Hans": "日志", "en": "Log"},
    "menu.help": {"zh-Hant": "說明", "zh-Hans": "帮助", "en": "Help"},
    "menu.about": {"zh-Hant": "關於", "zh-Hans": "关于", "en": "About"},
    "menu.checkUpdate": {"zh-Hant": "檢查更新", "zh-Hans": "检查更新", "en": "Check for updates"},
    # ---- 連線 ----
    "connection.title": {"zh-Hant": "連線", "zh-Hans": "连接", "en": "Connection"},
    "connection.server": {"zh-Hant": "伺服端", "zh-Hans": "服务端", "en": "Server"},
    "connection.serverHint": {"zh-Hant": "伺服端主機名稱或 IP", "zh-Hans": "服务端主机名或 IP", "en": "Server host name or IP"},
    "connection.port": {"zh-Hant": "埠", "zh-Hans": "端口", "en": "Port"},
    "connection.name": {"zh-Hant": "名稱", "zh-Hans": "名称", "en": "Name"},
    "connection.nameHint": {"zh-Hant": "在網頁上顯示的擷取端名稱", "zh-Hans": "在网页上显示的采集端名称", "en": "Name shown on the web page"},
    "connection.key": {"zh-Hant": "金鑰", "zh-Hans": "密钥", "en": "Key"},
    "connection.keyHint": {"zh-Hant": "伺服端有設定金鑰時才需要", "zh-Hans": "服务端有设置密钥时才需要", "en": "Only needed if the server requires one"},
    "connection.localMode": {"zh-Hant": "本機模式", "zh-Hans": "本机模式", "en": "Local mode"},
    "connection.idleStop": {"zh-Hant": "閒置停止取像", "zh-Hans": "闲置停止取像", "en": "Idle stop"},
    "connection.idleStopHint": {"zh-Hant": "視窗縮到系統匣、且伺服端超過這段時間沒有要求取像，就停止相機取像以節省 CPU；下次要影像時自動恢復。0＝不停止。", "zh-Hans": "窗口缩到系统托盘、且服务端超过这段时间没有要求取像，就停止相机取像以节省 CPU；下次要图像时自动恢复。0＝不停止。", "en": "When the window is in the tray and the server has not asked for a frame for this long, acquisition stops to save CPU and resumes automatically on the next request. 0 = never stop."},
    "connection.idleSuffix": {"zh-Hant": " 秒", "zh-Hans": " 秒", "en": " s"},
    "connection.autoConnect": {"zh-Hant": "啟動時自動連線", "zh-Hans": "启动时自动连接", "en": "Connect on start"},
    "connection.connect": {"zh-Hant": "連線", "zh-Hans": "连接", "en": "Connect"},
    "connection.disconnect": {"zh-Hant": "中斷", "zh-Hans": "断开", "en": "Disconnect"},
    "connection.settings": {"zh-Hant": "設定", "zh-Hans": "设置", "en": "Settings"},
    "connection.target": {"zh-Hant": "伺服端 {server}・本機名稱 {name}", "zh-Hans": "服务端 {server}・本机名称 {name}", "en": "Server {server} · this client {name}"},
    "connection.rtt": {"zh-Hant": "往返延遲", "zh-Hans": "往返延迟", "en": "Round trip"},
    "connection.sent": {"zh-Hant": "已送影格", "zh-Hans": "已发送帧", "en": "Frames sent"},
    "connection.rate": {"zh-Hant": "速率", "zh-Hans": "速率", "en": "Rate"},
    "connection.transport": {"zh-Hant": "傳送方式", "zh-Hans": "传送方式", "en": "Transport"},
    "connection.sentValue": {"zh-Hant": "{frames} 張（{bytes}）", "zh-Hans": "{frames} 张（{bytes}）", "en": "{frames} frames ({bytes})"},
    "connection.viaShm": {"zh-Hant": "共享記憶體（同一台電腦）", "zh-Hans": "共享内存（同一台电脑）", "en": "Shared memory (same PC)"},
    "connection.viaTcp": {"zh-Hant": "TCP", "zh-Hans": "TCP", "en": "TCP"},
    "state.disconnected": {"zh-Hant": "未連線", "zh-Hans": "未连接", "en": "Disconnected"},
    "state.connecting": {"zh-Hant": "連線中", "zh-Hans": "连接中", "en": "Connecting"},
    "state.connected": {"zh-Hant": "已連線", "zh-Hans": "已连接", "en": "Connected"},
    "state.reconnecting": {"zh-Hant": "重新連線中", "zh-Hans": "重新连接中", "en": "Reconnecting"},
    "state.auth_failed": {"zh-Hant": "驗證失敗", "zh-Hans": "验证失败", "en": "Authentication failed"},
    "detail.local": {"zh-Hant": "本機模式（共享記憶體）", "zh-Hans": "本机模式（共享内存）", "en": "Local mode (shared memory)"},
    "detail.attempt": {"zh-Hant": "第 {n} 次嘗試", "zh-Hans": "第 {n} 次尝试", "en": "Attempt {n}"},
    "localMode.auto": {"zh-Hant": "自動（同一台電腦用共享記憶體）", "zh-Hans": "自动（同一台电脑用共享内存）", "en": "Auto (shared memory on the same PC)"},
    "localMode.force": {"zh-Hant": "強制共享記憶體", "zh-Hans": "强制共享内存", "en": "Force shared memory"},
    "localMode.off": {"zh-Hant": "一律走 TCP", "zh-Hans": "一律走 TCP", "en": "Always use TCP"},
    # ---- 通道 ----
    "channels.title": {"zh-Hant": "通道", "zh-Hans": "通道", "en": "Channels"},
    "channels.editTitle": {"zh-Hant": "相機通道", "zh-Hans": "相机通道", "en": "Camera channels"},
    "channels.add": {"zh-Hant": "新增", "zh-Hans": "新增", "en": "Add"},
    "channels.remove": {"zh-Hant": "移除", "zh-Hans": "移除", "en": "Remove"},
    "channels.name": {"zh-Hant": "名稱", "zh-Hans": "名称", "en": "Name"},
    "channels.backend": {"zh-Hant": "相機種類", "zh-Hans": "相机种类", "en": "Camera type"},
    "channels.device": {"zh-Hant": "裝置", "zh-Hans": "设备", "en": "Device"},
    "channels.scan": {"zh-Hant": "掃描", "zh-Hans": "扫描", "en": "Scan"},
    "channels.scanning": {"zh-Hant": "掃描中…", "zh-Hans": "扫描中…", "en": "Scanning…"},
    "channels.enabled": {"zh-Hant": "啟用（伺服端可取像）", "zh-Hans": "启用（服务端可取像）", "en": "Enabled (server may grab)"},
    "channels.preview": {"zh-Hant": "即時預覽", "zh-Hans": "实时预览", "en": "Live preview"},
    "channels.open": {"zh-Hant": "開啟", "zh-Hans": "打开", "en": "Open"},
    "channels.closeCam": {"zh-Hant": "關閉", "zh-Hans": "关闭", "en": "Close"},
    "channels.start": {"zh-Hant": "開始取像", "zh-Hans": "开始取像", "en": "Start"},
    "channels.stop": {"zh-Hant": "停止", "zh-Hans": "停止", "en": "Stop"},
    "channels.state": {"zh-Hant": "狀態：{state}", "zh-Hans": "状态：{state}", "en": "State: {state}"},
    "channels.newName": {"zh-Hant": "相機 {n}", "zh-Hans": "相机 {n}", "en": "Camera {n}"},
    "channels.disabledSuffix": {"zh-Hant": "（停用）", "zh-Hans": "（停用）", "en": " (disabled)"},
    "channels.idlePaused": {"zh-Hant": "（省電暫停）", "zh-Hans": "（省电暂停）", "en": " (paused)"},
    "channels.idleHint": {"zh-Hant": "閒置省電中，伺服端要影像時會自動恢復", "zh-Hans": "闲置省电中，服务端要图像时会自动恢复", "en": "Paused to save CPU; resumes automatically when a frame is requested"},
    "channels.removeTitle": {"zh-Hant": "移除通道", "zh-Hans": "移除通道", "en": "Remove channel"},
    "channels.removeBody": {"zh-Hant": "要移除通道「{name}」嗎？使用此通道的網頁影像來源將無法取像。", "zh-Hans": "要移除通道「{name}」吗？使用此通道的网页图像来源将无法取像。", "en": "Remove channel '{name}'? Image sources using it will stop working."},
    "channels.noDevices": {"zh-Hant": "沒有找到裝置；可直接輸入裝置識別（例如網路攝影機的索引 0）。", "zh-Hans": "没有找到设备；可直接输入设备标识（例如网络摄像头的索引 0）。", "en": "No device found; you can type an id directly (for example 0 for a webcam)."},
    "channels.scanFailed": {"zh-Hant": "掃描失敗：{error}", "zh-Hans": "扫描失败：{error}", "en": "Scan failed: {error}"},
    "channels.sdkMissing": {"zh-Hant": "（SDK 尚未安裝）", "zh-Hans": "（SDK 尚未安装）", "en": " (SDK not installed)"},
    "channels.sdkTip": {"zh-Hant": "SDK 尚未安裝：{reason}", "zh-Hans": "SDK 尚未安装：{reason}", "en": "SDK not installed: {reason}"},
    "chstate.closed": {"zh-Hant": "已關閉", "zh-Hans": "已关闭", "en": "Closed"},
    "chstate.opening": {"zh-Hant": "開啟中", "zh-Hans": "打开中", "en": "Opening"},
    "chstate.open": {"zh-Hant": "已開啟", "zh-Hans": "已打开", "en": "Open"},
    "chstate.running": {"zh-Hant": "取像中", "zh-Hans": "取像中", "en": "Grabbing"},
    "chstate.error": {"zh-Hant": "錯誤", "zh-Hans": "错误", "en": "Error"},
    # ---- 預覽與 ROI ----
    "live.pickChannel": {"zh-Hant": "請選擇通道", "zh-Hans": "请选择通道", "en": "Select a channel"},
    "live.noImage": {"zh-Hant": "尚無影像", "zh-Hans": "尚无图像", "en": "No image yet"},
    "live.notRunning": {"zh-Hant": "尚無影像（相機尚未開始取像）", "zh-Hans": "尚无图像（相机尚未开始取像）", "en": "No image yet (camera is not grabbing)"},
    "live.waiting": {"zh-Hant": "等待影格…", "zh-Hans": "等待帧…", "en": "Waiting for a frame…"},
    "live.previewOff": {"zh-Hant": "預覽已關閉", "zh-Hans": "预览已关闭", "en": "Preview is off"},
    "live.roi": {"zh-Hant": "ROI", "zh-Hans": "ROI", "en": "ROI"},
    "live.roiX": {"zh-Hant": "X", "zh-Hans": "X", "en": "X"},
    "live.roiY": {"zh-Hant": "Y", "zh-Hans": "Y", "en": "Y"},
    "live.roiW": {"zh-Hant": "寬", "zh-Hans": "宽", "en": "W"},
    "live.roiH": {"zh-Hant": "高", "zh-Hans": "高", "en": "H"},
    "live.clearRoi": {"zh-Hant": "清除 ROI", "zh-Hans": "清除 ROI", "en": "Clear ROI"},
    "live.hwRoi": {"zh-Hant": "使用相機硬體 ROI", "zh-Hans": "使用相机硬件 ROI", "en": "Use camera hardware ROI"},
    "live.hwRoiTip": {"zh-Hant": "相機支援時只讀出 ROI 範圍（更高的影格率）；不支援時以軟體裁切後傳送。", "zh-Hans": "相机支持时只读出 ROI 范围（更高的帧率）；不支持时以软件裁切后传送。", "en": "Reads out only the ROI when the camera supports it (higher frame rate); otherwise crops in software."},
    "live.applyRoi": {"zh-Hant": "套用 ROI", "zh-Hans": "应用 ROI", "en": "Apply ROI"},
    "live.snap": {"zh-Hant": "拍攝一張", "zh-Hans": "拍摄一张", "en": "Snap"},
    "live.snapTip": {"zh-Hant": "軟體觸發模式：觸發相機拍一張", "zh-Hans": "软件触发模式：触发相机拍一张", "en": "Software trigger: grab a single frame"},
    "live.hint": {"zh-Hant": "在影像上拖曳圈選 ROI；只有 ROI 範圍會傳給伺服端。", "zh-Hans": "在图像上拖拽圈选 ROI；只有 ROI 范围会传给服务端。", "en": "Drag on the image to set an ROI; only that region is sent to the server."},
    "live.roiChanged": {"zh-Hant": "ROI 已更新，點選「套用 ROI」才會生效。", "zh-Hans": "ROI 已更新，点选「应用 ROI」才会生效。", "en": "ROI changed — click 'Apply ROI' to take effect."},
    "live.roiCleared": {"zh-Hant": "ROI 已清除（全幅），點選「套用 ROI」生效。", "zh-Hans": "ROI 已清除（全幅），点选「应用 ROI」生效。", "en": "ROI cleared (full frame) — click 'Apply ROI' to take effect."},
    "live.applying": {"zh-Hant": "套用中…", "zh-Hans": "应用中…", "en": "Applying…"},
    "live.fullRestored": {"zh-Hant": "已恢復全幅。", "zh-Hans": "已恢复全幅。", "en": "Full frame restored."},
    "live.hwApplied": {"zh-Hant": "硬體 ROI 已生效：{w}×{h} @ {x},{y}（依相機對齊）。預覽即 ROI 範圍。", "zh-Hans": "硬件 ROI 已生效：{w}×{h} @ {x},{y}（依相机对齐）。预览即 ROI 范围。", "en": "Hardware ROI active: {w}×{h} @ {x},{y} (aligned by the camera). The preview is the ROI."},
    "live.swApplied": {"zh-Hant": "ROI 已套用（軟體裁切）：{w}×{h} @ {x},{y}。", "zh-Hans": "ROI 已应用（软件裁切）：{w}×{h} @ {x},{y}。", "en": "ROI applied (software crop): {w}×{h} @ {x},{y}."},
    "live.noHwRoi": {"zh-Hant": "此相機不支援硬體 ROI。", "zh-Hans": "此相机不支持硬件 ROI。", "en": "This camera has no hardware ROI."},
    "live.applyFailed": {"zh-Hant": "套用失敗：{error}", "zh-Hans": "应用失败：{error}", "en": "Apply failed: {error}"},
    "live.snapped": {"zh-Hant": "已拍攝一張。", "zh-Hans": "已拍摄一张。", "en": "Frame captured."},
    "live.snapTimeout": {"zh-Hant": "拍攝逾時。", "zh-Hans": "拍摄超时。", "en": "Capture timed out."},
    "live.snapFailed": {"zh-Hant": "拍攝失敗：{error}", "zh-Hans": "拍摄失败：{error}", "en": "Capture failed: {error}"},
    "live.hwRoiBadge": {"zh-Hant": "硬體 ROI @ {x},{y}", "zh-Hans": "硬件 ROI @ {x},{y}", "en": "HW ROI @ {x},{y}"},
    # ---- 相機參數 ----
    "params.tab": {"zh-Hant": "相機參數", "zh-Hans": "相机参数", "en": "Camera"},
    "params.reload": {"zh-Hant": "重新讀取", "zh-Hans": "重新读取", "en": "Reload"},
    "params.save": {"zh-Hant": "儲存到設定檔", "zh-Hans": "保存到设置文件", "en": "Save to settings"},
    "params.saveTip": {"zh-Hant": "把目前的相機參數、ROI 與傳送設定寫進設定檔，下次啟動自動套用", "zh-Hans": "把当前的相机参数、ROI 与传送设置写进设置文件，下次启动自动应用", "en": "Write the current camera, ROI and delivery settings to the config so they apply on the next start"},
    "params.pickChannel": {"zh-Hant": "請選擇通道", "zh-Hans": "请选择通道", "en": "Select a channel"},
    "params.notOpen": {"zh-Hant": "相機尚未開啟（先在「通道」開啟相機）", "zh-Hans": "相机尚未打开（先在「通道」打开相机）", "en": "Camera is not open (open it under 'Channels')"},
    "params.loading": {"zh-Hant": "讀取中…", "zh-Hans": "读取中…", "en": "Loading…"},
    "params.loadFailed": {"zh-Hant": "讀取失敗：{error}", "zh-Hans": "读取失败：{error}", "en": "Load failed: {error}"},
    "params.count": {"zh-Hant": "{n} 個參數；改動後自動套用", "zh-Hans": "{n} 个参数；改动后自动应用", "en": "{n} parameters; changes apply automatically"},
    "params.none": {"zh-Hant": "此相機沒有可設定的參數", "zh-Hans": "此相机没有可设置的参数", "en": "This camera has no adjustable parameters"},
    "params.closed": {"zh-Hant": "相機已關閉", "zh-Hans": "相机已关闭", "en": "Camera closed"},
    "params.applying": {"zh-Hant": "套用中…", "zh-Hans": "应用中…", "en": "Applying…"},
    "params.applied": {"zh-Hant": "已套用：{items}", "zh-Hans": "已应用：{items}", "en": "Applied: {items}"},
    "params.noChange": {"zh-Hant": "沒有變更", "zh-Hans": "没有变更", "en": "No change"},
    "params.applyFailed": {"zh-Hant": "套用失敗：{error}", "zh-Hans": "应用失败：{error}", "en": "Apply failed: {error}"},
    "params.restartTitle": {"zh-Hant": "套用參數", "zh-Hans": "应用参数", "en": "Apply parameter"},
    "params.restartBody": {"zh-Hant": "此參數需要暫停取像才能套用，套用後會自動恢復取像。要繼續嗎？", "zh-Hans": "此参数需要暂停取像才能应用，应用后会自动恢复取像。要继续吗？", "en": "This parameter requires pausing acquisition; it resumes automatically afterwards. Continue?"},
    "params.apply": {"zh-Hant": "套用", "zh-Hans": "应用", "en": "Apply"},
    "params.search": {"zh-Hant": "搜尋參數…", "zh-Hans": "搜索参数…", "en": "Search parameters…"},
    "params.colName": {"zh-Hant": "參數", "zh-Hans": "参数", "en": "Parameter"},
    "params.colValue": {"zh-Hant": "設定值", "zh-Hans": "设置值", "en": "Value"},
    "params.groupBasic": {"zh-Hant": "基本", "zh-Hans": "基本", "en": "Basic"},
    "params.groupAdvanced": {"zh-Hant": "進階", "zh-Hans": "高级", "en": "Advanced"},
    "params.range": {"zh-Hant": "範圍 {min}～{max}", "zh-Hans": "范围 {min}～{max}", "en": "Range {min}–{max}"},
    "param.exposure_us": {"zh-Hant": "曝光時間", "zh-Hans": "曝光时间", "en": "Exposure"},
    "param.gain_db": {"zh-Hant": "增益", "zh-Hans": "增益", "en": "Gain"},
    "param.fps": {"zh-Hant": "影格率", "zh-Hans": "帧率", "en": "Frame rate"},
    "param.pixel_format": {"zh-Hant": "像素格式", "zh-Hans": "像素格式", "en": "Pixel format"},
    "param.width": {"zh-Hant": "寬", "zh-Hans": "宽", "en": "Width"},
    "param.height": {"zh-Hant": "高", "zh-Hans": "高", "en": "Height"},
    "param.offset_x": {"zh-Hant": "X 位移", "zh-Hans": "X 位移", "en": "Offset X"},
    "param.offset_y": {"zh-Hant": "Y 位移", "zh-Hans": "Y 位移", "en": "Offset Y"},
    "param.trigger_mode": {"zh-Hant": "觸發模式", "zh-Hans": "触发模式", "en": "Trigger mode"},
    "trigger.freerun": {"zh-Hant": "自由取像", "zh-Hans": "自由取像", "en": "Free run"},
    "trigger.software": {"zh-Hant": "軟體觸發", "zh-Hans": "软件触发", "en": "Software trigger"},
    "trigger.hardware": {"zh-Hant": "硬體觸發", "zh-Hans": "硬件触发", "en": "Hardware trigger"},
    # ---- 傳送設定 ----
    "delivery.tab": {"zh-Hant": "傳送設定", "zh-Hans": "传送设置", "en": "Delivery"},
    "delivery.group": {"zh-Hant": "傳送", "zh-Hans": "传送", "en": "Delivery"},
    "delivery.encoding": {"zh-Hant": "編碼", "zh-Hans": "编码", "en": "Encoding"},
    "delivery.encodingTip": {"zh-Hant": "同一台電腦一律走共享記憶體（不壓縮）；跨電腦建議 LZ4（無損、約 1.5～3 倍）；JPEG 有損，只在頻寬很緊時使用。", "zh-Hans": "同一台电脑一律走共享内存（不压缩）；跨电脑建议 LZ4（无损、约 1.5～3 倍）；JPEG 有损，只在带宽很紧时使用。", "en": "Same PC always uses shared memory (uncompressed); across PCs prefer LZ4 (lossless, 1.5–3×); JPEG is lossy — only when bandwidth is tight."},
    "delivery.jpegQuality": {"zh-Hant": "JPEG 品質", "zh-Hans": "JPEG 质量", "en": "JPEG quality"},
    "delivery.mono": {"zh-Hant": "轉成單色後傳送（頻寬 ÷3）", "zh-Hans": "转成单色后传送（带宽 ÷3）", "en": "Send as mono (⅓ the bandwidth)"},
    "delivery.downscale": {"zh-Hant": "縮小", "zh-Hans": "缩小", "en": "Downscale"},
    "delivery.noDownscale": {"zh-Hant": "不縮小", "zh-Hans": "不缩小", "en": "None"},
    "delivery.mode": {"zh-Hant": "模式", "zh-Hans": "模式", "en": "Mode"},
    "delivery.modeTip": {"zh-Hant": "依需求取像：伺服端每次執行才向相機要一張新影格（延遲最低、頻寬最省）。連續串流：持續把最新影格推給伺服端，執行時直接取用。", "zh-Hans": "按需取像：服务端每次执行才向相机要一张新帧（延迟最低、带宽最省）。连续串流：持续把最新帧推给服务端，执行时直接取用。", "en": "On demand: the server asks for a fresh frame per run (lowest latency and bandwidth). Stream: the client keeps pushing the latest frame."},
    "delivery.streamFps": {"zh-Hant": "串流上限", "zh-Hans": "串流上限", "en": "Stream limit"},
    "delivery.testGroup": {"zh-Hant": "測試", "zh-Hans": "测试", "en": "Test"},
    "delivery.test": {"zh-Hant": "測試傳送", "zh-Hans": "测试传送", "en": "Test send"},
    "delivery.testTip": {"zh-Hant": "把目前影格依上述設定送到伺服端一次，量往返時間與大小", "zh-Hans": "把当前帧依上述设置送到服务端一次，量往返时间与大小", "en": "Send the current frame once and measure round trip and size"},
    "delivery.testing": {"zh-Hant": "傳送中…", "zh-Hans": "传送中…", "en": "Sending…"},
    "delivery.testResult": {"zh-Hant": "往返 {rtt} ms · {bytes} · 編碼 {encode} ms", "zh-Hans": "往返 {rtt} ms · {bytes} · 编码 {encode} ms", "en": "Round trip {rtt} ms · {bytes} · encode {encode} ms"},
    "delivery.testDecode": {"zh-Hant": " · 伺服端解碼 {decode} ms", "zh-Hans": " · 服务端解码 {decode} ms", "en": " · server decode {decode} ms"},
    "delivery.testFailed": {"zh-Hant": "失敗：{error}", "zh-Hans": "失败：{error}", "en": "Failed: {error}"},
    "delivery.estimate": {"zh-Hant": "送出尺寸 {w}×{h}×{c}，每張 {size}；{note}{per}", "zh-Hans": "送出尺寸 {w}×{h}×{c}，每张 {size}；{note}{per}", "en": "Sending {w}×{h}×{c}, {size} per frame; {note}{per}"},
    "delivery.noteRaw": {"zh-Hant": "不壓縮", "zh-Hans": "不压缩", "en": "uncompressed"},
    "delivery.noteLz4": {"zh-Hant": "LZ4 典型 {lo}～{hi}（無損；同一台電腦走共享記憶體時不壓縮）", "zh-Hans": "LZ4 典型 {lo}～{hi}（无损；同一台电脑走共享内存时不压缩）", "en": "LZ4 typically {lo}–{hi} (lossless; uncompressed over shared memory)"},
    "delivery.noteJpeg": {"zh-Hant": "JPEG 約 {lo}～{hi}（有損）", "zh-Hans": "JPEG 约 {lo}～{hi}（有损）", "en": "JPEG about {lo}–{hi} (lossy)"},
    "delivery.perSecond": {"zh-Hant": "；連續串流 {fps} fps 最多 {rate}/s（未壓縮）", "zh-Hans": "；连续串流 {fps} fps 最多 {rate}/s（未压缩）", "en": "; streaming at {fps} fps is up to {rate}/s uncompressed"},
    "encoding.raw": {"zh-Hant": "不壓縮（raw）", "zh-Hans": "不压缩（raw）", "en": "Uncompressed (raw)"},
    "encoding.lz4": {"zh-Hant": "無損壓縮（LZ4）", "zh-Hans": "无损压缩（LZ4）", "en": "Lossless (LZ4)"},
    "encoding.jpeg": {"zh-Hant": "有損壓縮（JPEG）", "zh-Hans": "有损压缩（JPEG）", "en": "Lossy (JPEG)"},
    "encoding.lz4Missing": {"zh-Hant": "（此版本未內含）", "zh-Hans": "（此版本未内含）", "en": " (not bundled)"},
    "mode.on_demand": {"zh-Hant": "依需求取像", "zh-Hans": "按需取像", "en": "On demand"},
    "mode.stream": {"zh-Hant": "連續串流", "zh-Hans": "连续串流", "en": "Stream"},
    # ---- 記錄 ----
    "log.title": {"zh-Hant": "記錄", "zh-Hans": "日志", "en": "Log"},
    "log.level": {"zh-Hant": "等級", "zh-Hans": "级别", "en": "Level"},
    "log.all": {"zh-Hant": "全部", "zh-Hans": "全部", "en": "All"},
    "log.info": {"zh-Hant": "一般", "zh-Hans": "一般", "en": "Info"},
    "log.warning": {"zh-Hant": "警告", "zh-Hans": "警告", "en": "Warning"},
    "log.error": {"zh-Hant": "錯誤", "zh-Hans": "错误", "en": "Error"},
    "log.clear": {"zh-Hant": "清除", "zh-Hans": "清除", "en": "Clear"},
    # ---- 系統匣 ----
    "tray.show": {"zh-Hant": "顯示視窗", "zh-Hans": "显示窗口", "en": "Show window"},
    "tray.tip": {"zh-Hant": "程式仍在系統匣執行；右鍵可連線、中斷或結束。", "zh-Hans": "程序仍在系统托盘运行；右键可连接、断开或退出。", "en": "Still running in the tray; right-click to connect, disconnect or quit."},
    "tray.state": {"zh-Hant": "VisionSequence 擷取端 — {state}", "zh-Hans": "VisionSequence 采集端 — {state}", "en": "VisionSequence Capture — {state}"},
    # ---- 更新 ----
    "update.found": {"zh-Hant": "有新版擷取端 {version}（{size}）", "zh-Hans": "有新版采集端 {version}（{size}）", "en": "Capture client {version} is available ({size})"},
    "update.install": {"zh-Hant": "下載並更新", "zh-Hans": "下载并更新", "en": "Download and update"},
    "update.later": {"zh-Hant": "稍後", "zh-Hans": "稍后", "en": "Later"},
    "update.cancel": {"zh-Hant": "取消更新", "zh-Hans": "取消更新", "en": "Cancel update"},
    "update.downloading": {"zh-Hant": "下載中 {percent}%（{got} / {total}）", "zh-Hans": "下载中 {percent}%（{got} / {total}）", "en": "Downloading {percent}% ({got} / {total})"},
    "update.staging": {"zh-Hant": "解壓縮中…", "zh-Hans": "解压中…", "en": "Extracting…"},
    "update.applying": {"zh-Hant": "即將關閉並更新…", "zh-Hans": "即将关闭并更新…", "en": "Closing to install…"},
    "update.ready": {"zh-Hant": "新版已下載完成（{path}）", "zh-Hans": "新版已下载完成（{path}）", "en": "Update downloaded ({path})"},
    "update.error": {"zh-Hant": "更新失敗：{error}", "zh-Hans": "更新失败：{error}", "en": "Update failed: {error}"},
    "update.upToDate": {"zh-Hant": "目前已是最新版 {version}", "zh-Hans": "当前已是最新版 {version}", "en": "Already up to date ({version})"},
    "update.noServer": {"zh-Hant": "尚未連線，無法檢查更新", "zh-Hans": "尚未连接，无法检查更新", "en": "Not connected — cannot check for updates"},
    "update.sourceMode": {"zh-Hant": "以原始碼執行時不會自動覆寫，請手動更新", "zh-Hans": "以源码运行时不会自动覆盖，请手动更新", "en": "Running from source — install the update manually"},
    "update.auto": {"zh-Hant": "自動更新", "zh-Hans": "自动更新", "en": "Auto update"},
    "autoUpdate.off": {"zh-Hant": "不檢查", "zh-Hans": "不检查", "en": "Off"},
    "autoUpdate.notify": {"zh-Hant": "通知我", "zh-Hans": "通知我", "en": "Notify me"},
    "autoUpdate.auto": {"zh-Hant": "自動下載並安裝", "zh-Hans": "自动下载并安装", "en": "Download and install"},
    # ---- 對話框 ----
    "dialog.reloadTitle": {"zh-Hant": "重新載入設定", "zh-Hans": "重新载入设置", "en": "Reload settings"},
    "dialog.reloadBody": {"zh-Hant": "會關閉所有相機並依設定檔重新建立通道與連線。要繼續嗎？", "zh-Hans": "会关闭所有相机并依设置文件重新建立通道与连接。要继续吗？", "en": "This closes every camera and rebuilds channels and the connection from the config file. Continue?"},
    "dialog.reload": {"zh-Hant": "重新載入", "zh-Hans": "重新载入", "en": "Reload"},
    "dialog.reloaded": {"zh-Hant": "設定已重新載入", "zh-Hans": "设置已重新载入", "en": "Settings reloaded"},
    "dialog.badConfig": {"zh-Hant": "設定檔有誤：{error}", "zh-Hans": "设置文件有误：{error}", "en": "Invalid config: {error}"},
    "dialog.badConfigTitle": {"zh-Hant": "設定檔有誤", "zh-Hans": "设置文件有误", "en": "Invalid config"},
    "dialog.badConfigBody": {"zh-Hant": "{error}\n\n已改用預設值；儲存設定會覆寫原檔。", "zh-Hans": "{error}\n\n已改用默认值；保存设置会覆盖原文件。", "en": "{error}\n\nDefaults are in use; saving will overwrite the file."},
    "dialog.saveTitle": {"zh-Hant": "儲存設定", "zh-Hans": "保存设置", "en": "Save settings"},
    "dialog.saveFailed": {"zh-Hant": "無法寫入設定檔：{error}", "zh-Hans": "无法写入设置文件：{error}", "en": "Cannot write the config file: {error}"},
    "dialog.saved": {"zh-Hant": "設定已儲存：{path}", "zh-Hans": "设置已保存：{path}", "en": "Settings saved: {path}"},
    "dialog.quitTitle": {"zh-Hant": "結束", "zh-Hans": "退出", "en": "Quit"},
    "dialog.quitBody": {"zh-Hant": "設定尚未儲存，要儲存嗎？", "zh-Hans": "设置尚未保存，要保存吗？", "en": "Settings are not saved. Save them?"},
    "dialog.saveQuit": {"zh-Hant": "儲存並結束", "zh-Hans": "保存并退出", "en": "Save and quit"},
    "dialog.discardQuit": {"zh-Hant": "不儲存", "zh-Hans": "不保存", "en": "Don't save"},
    "about.body": {"zh-Hant": "在相機所在的電腦直接驅動相機，把影像送到 VisionSequence 伺服端。", "zh-Hans": "在相机所在的电脑直接驱动相机，把图像送到 VisionSequence 服务端。", "en": "Drives cameras on this PC and sends the images to a VisionSequence server."},
    "about.config": {"zh-Hant": "設定檔", "zh-Hans": "设置文件", "en": "Config"},
    "about.logs": {"zh-Hant": "記錄檔", "zh-Hans": "日志文件", "en": "Logs"},
    "status.streamOn": {"zh-Hant": "通道 {id} 串流開啟", "zh-Hans": "通道 {id} 串流开启", "en": "Channel {id} streaming on"},
    "status.streamOff": {"zh-Hant": "通道 {id} 串流關閉", "zh-Hans": "通道 {id} 串流关闭", "en": "Channel {id} streaming off"},
}


def language() -> str:
    return _current


def set_language(code: str) -> str:
    """設定語言（不認得的代碼回退到繁體中文）；回實際採用的代碼。"""
    global _current
    _current = code if code in LANGUAGE_CODES else DEFAULT_LANGUAGE
    return _current


def tr(key: str, **kw: Any) -> str:
    """翻譯；缺字時回退到繁體中文，再缺就回 key 本身（不讓介面變空白）。"""
    entry = TEXTS.get(key)
    if entry is None:
        return key
    text = entry.get(_current) or entry.get(DEFAULT_LANGUAGE) or key
    if kw:
        try:
            return text.format(**kw)
        except (KeyError, IndexError, ValueError):
            return text
    return text


def language_name(code: str) -> str:
    return dict(LANGUAGES).get(code, code)
