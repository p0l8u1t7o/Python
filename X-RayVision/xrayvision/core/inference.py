"""
深度學習推論 (規劃書 PLAN-002 第 5 節)

- ONNX Runtime：DirectML 版同一套件支援 CPU 與 Windows 上的 GPU (NVIDIA、AMD、Intel)，不需安裝 CUDA
- GPU 預設關閉，由系統管理員啟用 (設備可能用 GPU 做 3D 重建)；不可用時自動使用 CPU
- 每個分析子行程對同一模型只建立一次工作階段 (快取)，執行緒數限制為 1，避免影響設備操作
"""
import os
import threading

_LOCK = threading.Lock()
_SESSIONS = {}


class InferenceError(RuntimeError):
    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def available():
    """回傳 dict(installed, providers)；未安裝推論執行環境時 installed=False"""
    try:
        import onnxruntime as ort
    except ImportError:
        return dict(installed=False, providers=[], version=None)
    return dict(installed=True, providers=list(ort.get_available_providers()), version=ort.__version__)


def providers(gpu):
    info = available()
    if not info["installed"]:
        raise InferenceError("inference_unavailable")
    out = []
    if gpu and "DmlExecutionProvider" in info["providers"]:
        out.append("DmlExecutionProvider")
    out.append("CPUExecutionProvider")
    return out


def session(path, gpu=False):
    """取得 (快取的) 推論工作階段；path 為 model.onnx"""
    key = (os.path.abspath(path), bool(gpu))
    with _LOCK:
        s = _SESSIONS.get(key)
        if s is not None:
            return s
        import onnxruntime as ort
        opt = ort.SessionOptions()
        opt.intra_op_num_threads = 1
        opt.inter_op_num_threads = 1
        opt.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        if gpu:
            # DirectML 不支援記憶體樣式最佳化與平行執行
            opt.enable_mem_pattern = False
            opt.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        try:
            s = ort.InferenceSession(path, sess_options=opt, providers=providers(gpu))
        except Exception as e:                                    # noqa: BLE001
            if gpu:                                               # GPU 無法建立時退回 CPU
                return session(path, gpu=False)
            raise InferenceError("model_load_failed", repr(e))
        _SESSIONS[key] = s
        return s


def run(path, batch, gpu=False):
    """batch：float32 陣列 (N, 1, H, W)；回傳第一個輸出"""
    s = session(path, gpu)
    name = s.get_inputs()[0].name
    return s.run(None, {name: batch})[0]


def clear():
    with _LOCK:
        _SESSIONS.clear()
