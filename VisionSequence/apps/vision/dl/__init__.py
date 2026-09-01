"""平台內深度學習教導：標記資料集、訓練、匯出 ONNX 到資產。

模組分工：
    base.py      Trainer 基底與 registry（外掛可加新模型種類，見 docs/plugins.html）
    builtin.py   內建 trainer（MLP 影像分類）
    onnx_io.py   手刻 ONNX protobuf（含權重 initializer；不依賴 onnx 套件）
    devices.py   伺服端運算資源資訊（onnxruntime providers／GPU）與推論 provider 設定
    jobs.py      訓練工作（背景執行緒、單一訓練槽、進度回報）
    api.py       /api/vision/dl/*
"""
