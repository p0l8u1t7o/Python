"""manage.py dl_check：檢查深度學習依賴與裝置（torch／CUDA、ultralytics、onnxruntime providers、SAM／YOLO 權重快取），
每項附「怎麼修」。setup_dl.ps1 最後一步會跑；安裝出問題先看這個。

  manage.py dl_check            只檢查
  manage.py dl_check --predict  另外用 yolo11n.pt 在合成影像上實跑一次（會下載 5MB 底模）
"""

from __future__ import annotations

import importlib
import os
import time

from django.conf import settings
from django.core.management.base import BaseCommand


def _ver(name: str) -> str | None:
    try:
        return str(getattr(importlib.import_module(name), "__version__", "?"))
    except Exception:  # noqa: BLE001
        return None


class Command(BaseCommand):
    help = "檢查深度學習依賴與裝置（torch/CUDA、ultralytics、onnxruntime、權重快取）"

    def add_arguments(self, parser):
        parser.add_argument("--predict", action="store_true", help="用 yolo11n.pt 實跑一次推論")

    def handle(self, *args, **opts):
        ok_all = True

        def row(ok: bool, name: str, detail: str, fix: str = ""):
            nonlocal ok_all
            ok_all = ok_all and ok
            mark = "OK " if ok else "!! "
            self.stdout.write(f"{mark}{name:<18}{detail}" + (f"\n    → {fix}" if fix and not ok else ""))

        # torch / CUDA
        torch_v = _ver("torch")
        cuda = False
        if torch_v:
            import torch

            cuda = bool(torch.cuda.is_available())
            gpu = torch.cuda.get_device_name(0) if cuda else "無"
            cap = ""
            if cuda:
                major, minor = torch.cuda.get_device_capability(0)
                cap = f"、sm_{major}{minor}"
                arch_ok = any(f"sm_{major}{minor}" in a for a in torch.cuda.get_arch_list())
                row(arch_ok, "torch kernels", f"arch list 含 sm_{major}{minor}：{arch_ok}",
                    "此 torch wheel 沒有你 GPU 的 kernel（RTX 50 系列要 cu128 以上）：.\\scripts\\setup_dl.ps1 -Cuda cu128")
            row(True, "torch", f"{torch_v}（CUDA {torch.version.cuda or '無'}、cuDNN {torch.backends.cudnn.version() or '無'}）；GPU：{gpu}{cap}")
            if "+cpu" in torch_v:
                row(False, "torch build", "CPU 版 torch", "有 NVIDIA GPU 的機器請用 setup_dl.ps1 重裝（先裝 torch 再裝 ultralytics）")
        else:
            row(False, "torch", "未安裝", ".\\scripts\\setup_dl.ps1（或 pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128）")

        # ultralytics
        ul = _ver("ultralytics")
        row(bool(ul), "ultralytics", ul or "未安裝", "pip install -r requirements-dl.txt")

        # onnxruntime
        ort_v = _ver("onnxruntime")
        if ort_v:
            import onnxruntime as ort

            providers = ort.get_available_providers()
            gpu_pkg = importlib.util.find_spec("onnxruntime") is not None and any("gpu" in d.metadata["Name"].lower() for d in _dists("onnxruntime"))
            row(True, "onnxruntime", f"{ort_v}（{'onnxruntime-gpu' if gpu_pkg else 'onnxruntime'}）providers：{', '.join(providers)}")
            both = len(_dists("onnxruntime")) > 1
            row(not both, "ort packages", "onnxruntime 與 onnxruntime-gpu 同時安裝" if both else "只有一個 onnxruntime 套件",
                "pip uninstall -y onnxruntime onnxruntime-gpu 後只裝其中一個")
            if "CUDAExecutionProvider" in providers:
                try:
                    from apps.vision.tools.builtin.dl import preload_gpu_dlls

                    preload_gpu_dlls()
                    sess = _tiny_session(["CUDAExecutionProvider", "CPUExecutionProvider"])
                    row("CUDAExecutionProvider" in sess.get_providers(), "ort CUDA session", f"實際 providers：{sess.get_providers()}",
                        "CUDA/cuDNN DLL 載入失敗：確認 torch 為 cu12x 版（DLL 隨 torch 附上），或安裝 nvidia-cudnn-cu12 並加入 PATH")
                except Exception as exc:  # noqa: BLE001
                    row(False, "ort CUDA session", str(exc)[:160], "先 import torch 再建 session（程式已處理）；或重裝 onnxruntime-gpu")
        else:
            row(False, "onnxruntime", "未安裝", "pip install onnxruntime-gpu（有 GPU）或 onnxruntime")

        # 權重快取
        weights = os.path.join(str(settings.VISION["ASSET_DIR"]), "dl", "weights")
        cached = sorted(f for f in os.listdir(weights)) if os.path.isdir(weights) else []
        row(True, "weights cache", f"{weights}：{', '.join(cached) if cached else '（空，第一次使用時自動下載）'}")
        row(True, "SAM model", f"預設 {settings.VISION.get('SAM_MODEL', 'sam2.1_t.pt')}（VISION_SAM_MODEL）")

        from apps.vision.dl import devices

        info = devices.info()
        row(True, "dl settings", f"train_device={info.get('train_device')}、preferred providers={info.get('preferred')}")

        if opts.get("predict"):
            try:
                import numpy as np

                from apps.vision.dl import yolo_runtime

                dev, note = yolo_runtime.pick_device("auto")
                model = yolo_runtime.load("yolo11n.pt", log_fn=lambda m: self.stdout.write("   " + m))
                img = np.full((320, 320, 3), 128, np.uint8)
                yolo_runtime.predict(model, img, device=dev, imgsz=320)
                t0 = time.perf_counter()
                for _ in range(5):
                    yolo_runtime.predict(model, img, device=dev, imgsz=320)
                row(True, "yolo predict", f"yolo11n.pt on {dev}{'（' + note + '）' if note else ''}：平均 {(time.perf_counter() - t0) * 200:.1f} ms @320")
            except Exception as exc:  # noqa: BLE001
                row(False, "yolo predict", str(exc)[:200], "見上面各項；離線環境請手動下載 yolo11n.pt 到權重快取目錄")

        self.stdout.write("結果：" + ("全部通過" if ok_all else "有項目需要處理（見 → 提示）"))
        if not ok_all:
            raise SystemExit(1)


def _dists(prefix: str):
    from importlib import metadata

    return [d for d in metadata.distributions() if (d.metadata["Name"] or "").lower().startswith(prefix)]


def _tiny_session(providers):
    """用 onnx.helper 建最小的 Identity 模型開 session（onnx 套件在 requirements-dl.txt 內）。"""
    import onnx
    import onnxruntime as ort
    from onnx import TensorProto, helper

    node = helper.make_node("Identity", ["x"], ["y"])
    graph = helper.make_graph([node], "tiny", [helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, 4])], [helper.make_tensor_value_info("y", TensorProto.FLOAT, [1, 4])])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    return ort.InferenceSession(onnx._serialize(model) if hasattr(onnx, "_serialize") else model.SerializeToString(), providers=providers)
