"""擷取端（capture client）伺服端：接受相機電腦上的擷取程式連入、登記通道、依需求要影像或接收串流。

- `hub.py`：監聽埠（VISION_CAPTURE_HOST/PORT）、每連線一條讀取執行緒、登錄表、影格請求／串流／共享記憶體。
- `grabber.py`：`CaptureGrabber(kind="capture")`，影像來源「擷取端相機」。
- `api.py`：`/vision/capture/*`（clients、preview、stream、download）。
協定定義共用 `vscapture/protocol.py`（擷取端程式也用同一份）。
"""
