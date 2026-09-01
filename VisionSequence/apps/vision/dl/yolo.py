"""YOLO 實例分割 trainer（torch + ultralytics，可選依賴、延後 import）。

沒安裝 torch/ultralytics 時平台照常啟動、trainer 照常列在目錄；開始訓練／自動標記時
才 import，缺件回 TrainError 附安裝指令。做法對齊 Temp/WebTraining.md（trainJob.py）：
- 進度：ultralytics callbacks（on_train_start / on_train_batch_end / on_fit_epoch_end）。
- 中止：設 trainer.stop = True，當前 batch 跳出後照常驗證、存檔、匯出（已訓練的不白費）。
- final_eval 會多觸發一次 on_fit_epoch_end，用「最後真的開始的 epoch」擋掉。
- 指標去掉 metrics/ 前綴；分割任務優先 (M)（mask）、退回 (B)（box）。
- 設 YOLO_OFFLINE=1 避免無網路環境卡住（基底權重 .pt 第一次仍需可取得）。
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
import threading
from typing import Any

import numpy as np

from apps.vision.dl.base import ProgressFn, SampleRef, Suggestion, TrainCancelled, Trainer, TrainError, TrainResult
from apps.vision.tools.base import Param

log = logging.getLogger(__name__)

_INSTALL_HINT = "需要安裝訓練依賴：.venv\\Scripts\\pip install ultralytics（含 torch；GPU 版 torch 請照 pytorch.org 指示安裝）"


def _import_ultralytics():
    try:
        os.environ.setdefault("YOLO_OFFLINE", "1")
        from ultralytics import YOLO  # noqa: PLC0415

        return YOLO
    except ImportError:
        raise TrainError(f"未安裝 ultralytics／torch。{_INSTALL_HINT}") from None


#: ultralytics 官方資產（yolov8n-seg.pt、yolo11s-seg.pt…）的下載位置。
_ASSET_URL = "https://github.com/ultralytics/assets/releases/download/v8.3.0/{name}"
_ASSET_NAME = re.compile(r"^yolo(v?\d+)[a-z]?(-seg)?\.pt$")


def _weights_dir() -> str:
    from django.conf import settings

    folder = os.path.join(str(settings.VISION["ASSET_DIR"]), "dl", "weights")
    os.makedirs(folder, exist_ok=True)
    return folder


def resolve_model(name: str, log_fn=None) -> str:
    """把模型參數解析成本地檔案路徑；官方底模名稱（yolov8n-seg.pt 等）不存在時自動下載。

    YOLO_OFFLINE=1 讓 ultralytics 不自己連網，所以底模由我們下載到 ASSET_DIR/dl/weights/，
    第一次自動教導／訓練不用手動準備 .pt。下載失敗（無網路）回 TrainError 說明。
    """
    name = str(name or "").strip() or "yolov8n-seg.pt"
    if os.path.isfile(name):
        return name
    base = os.path.basename(name)
    if base != name or not _ASSET_NAME.match(base):
        return name  # 非官方資產名稱（自訂路徑等）交給 ultralytics 處理
    target = os.path.join(_weights_dir(), base)
    if os.path.isfile(target):
        return target
    url = _ASSET_URL.format(name=base)
    # 序列化下載：訓練執行緒與 auto-label 請求可能同時發現快取不存在（共用 .part 會互踩、
    # Windows 下還會把交錯寫入的損毀檔升級成永久快取），取得鎖後重查一次直接省掉重複下載。
    with _download_lock:
        if os.path.isfile(target):
            return target
        if log_fn:
            log_fn(f"下載底模 {base}（第一次使用；{url}）…")
        log.info("下載 YOLO 底模 %s ← %s", base, url)
        import http.client
        import urllib.error
        import urllib.request

        fd, tmp = tempfile.mkstemp(dir=_weights_dir(), suffix=".part")
        try:
            # fdopen 放前面：urlopen 失敗時 with 會先把 fd 關掉，Windows 才刪得掉 .part
            with os.fdopen(fd, "wb") as f, urllib.request.urlopen(url, timeout=120) as resp:
                shutil.copyfileobj(resp, f)
            os.replace(tmp, target)
        except urllib.error.HTTPError as exc:
            _cleanup(tmp)
            if exc.code == 404:
                raise TrainError(f"模型名稱 {base} 不存在（官方資產沒有這個檔）。請確認「基底模型」參數，例如 yolov8n-seg.pt。") from None
            raise TrainError(f"底模 {base} 下載失敗（HTTP {exc.code}）。{url}") from None
        except (urllib.error.URLError, http.client.HTTPException, OSError, TimeoutError) as exc:
            _cleanup(tmp)
            raise TrainError(f"底模 {base} 下載失敗（{exc}）。請確認伺服器可連網，或手動下載後把路徑填進「基底模型」參數：{url}") from None
    if log_fn:
        log_fn(f"底模 {base} 已下載到 {target}")
    return target


_download_lock = threading.Lock()


def _cleanup(path: str) -> None:
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


def _clean_metrics(raw: dict[str, Any]) -> dict[str, Any]:
    """去 metrics/ 前綴；同名 (M) 蓋過 (B)（分割任務優先 mask 指標）。"""
    out: dict[str, Any] = {}
    for key, value in (raw or {}).items():
        name = str(key)
        if name.startswith("metrics/"):
            name = name[8:]
        try:
            value = round(float(value), 4)
        except (TypeError, ValueError):
            continue
        base = name.replace("(B)", "").replace("(M)", "")
        if name.endswith("(B)") and (base + "(M)") in raw or (("metrics/" + base + "(M)") in raw):
            continue
        out[base] = value
    return out


class YoloSegTrainer(Trainer):
    kind = "yolo_seg"
    label = "實例分割（YOLO-seg）"
    description = "用 polygon 標記訓練 YOLO segmentation 模型（找出每個物件的輪廓與類別）；需要另裝 ultralytics（torch），建議有 NVIDIA GPU。官方底模第一次使用會自動下載；還沒訓練過也能自動標記（用底模提案輪廓、掛到第一個類別）。匯出 ONNX 給「DL 實例分割」工具。"
    label_mode = "shapes"
    tool_key = "dl_instance"
    devices = ("cuda", "cpu")
    min_per_class = 1
    params = [
        Param("model", "基底模型", kind="text", default="yolov8n-seg.pt", help_text="ultralytics 模型名稱或 .pt 路徑；也可填上次訓練的 best.pt 續訓。"),
        Param("epochs", "訓練回合", kind="number", default=100, minimum=1, maximum=2000),
        Param("imgsz", "影像尺寸", kind="select", default=640, options=[{"value": 320, "label": "320"}, {"value": 480, "label": "480"}, {"value": 640, "label": "640（建議）"}, {"value": 960, "label": "960"}]),
        Param("batch", "Batch", kind="number", default=8, minimum=1, maximum=128, group="進階"),
        Param("patience", "Early stop 耐心值", kind="number", default=50, minimum=0, maximum=500, group="進階"),
        Param("lr0", "初始學習率", kind="number", default=0.001, minimum=0.00001, maximum=0.1, step=0.0001, group="進階"),
        Param("val_ratio", "驗證比例", kind="number", default=0.2, minimum=0.05, maximum=0.5, step=0.05, group="進階"),
        Param("workers", "DataLoader workers", kind="number", default=0, minimum=0, maximum=16, group="進階", help_text="Windows 建議 0（在背景執行緒跑訓練時最穩）。"),
        Param("suggest_conf", "自動標記信心門檻", kind="range", default=0.4, minimum=0.05, maximum=0.95, step=0.05, group="進階", help_text="還沒訓練過時用官方底模提案（輪廓掛到第一個類別，請確認後改類）；訓練過後自動改用 best.pt。"),
    ]

    def train(self, samples: list[SampleRef], classes: list[str], params: dict[str, Any], device: str, progress: ProgressFn) -> TrainResult:
        from apps.vision.dl.shapes import export_dataset

        if not classes:
            raise TrainError("至少要定義 1 個類別")
        YOLO = _import_ultralytics()
        import torch

        if device == "cuda" and not torch.cuda.is_available():
            _plog(progress, "[WARN] 找不到 CUDA，退回 CPU 訓練（會很慢）")
            device = "cpu"

        progress(0.01, "整理 YOLO 資料集", None)
        work = tempfile.mkdtemp(prefix="vs-yolo-")
        stopping = False

        def report(frac: float, stage: str, metrics: dict[str, Any] | None) -> None:
            nonlocal stopping
            try:
                progress(frac, stage, metrics)
            except TrainCancelled:
                stopping = True

        try:
            stats = export_dataset(
                ((s.id, s.path, s.shapes) for s in samples), classes, work,
                val_ratio=float(params.get("val_ratio") or 0.2))
            _plog(progress, f"資料集：train {stats['train']}、val {stats['val']}（{work}）")
            if stats["train"] < 1 or stats["val"] < 1:
                raise TrainError("已標記樣本太少：train 與 val 至少各要 1 張（建議每類 10 張以上）")

            model = YOLO(resolve_model(str(params.get("model") or "yolov8n-seg.pt"), lambda m: _plog(progress, m)))
            epochs = int(params.get("epochs") or 100)
            imgsz = int(params.get("imgsz") or 640)
            state: dict[str, Any] = {"epochs": epochs, "batches": 1, "batch": 0, "epoch": 0, "last_started": -1}
            history: list[dict[str, Any]] = []

            def on_train_start(t):
                state["epochs"] = int(getattr(t, "epochs", epochs))
                _plog(progress, f"開始訓練：{state['epochs']} epochs、imgsz {imgsz}、device {device}")

            def on_train_epoch_start(t):
                state["epoch"] = int(t.epoch)
                state["last_started"] = int(t.epoch)
                state["batches"] = max(1, len(t.train_loader) if getattr(t, "train_loader", None) is not None else 1)
                state["batch"] = 0

            def on_train_batch_end(t):
                state["batch"] += 1
                frac = (state["epoch"] + state["batch"] / state["batches"]) / max(1, state["epochs"])
                loss = None
                try:
                    loss = round(float(t.loss.item()), 4)
                except Exception:  # noqa: BLE001
                    pass
                report(0.05 + 0.85 * frac, f"訓練中（epoch {state['epoch'] + 1}/{state['epochs']}）",
                       {"epoch": state["epoch"] + 1, "epochs": state["epochs"], "loss": loss})
                if stopping:
                    t.stop = True  # ultralytics 會在本 batch 後跳出，照常驗證與存檔

            def on_fit_epoch_end(t):
                if int(t.epoch) > state["last_started"]:
                    return  # final_eval 的多餘觸發（WebTraining.md §6）
                point = {"epoch": int(t.epoch) + 1, **_clean_metrics(getattr(t, "metrics", {}) or {})}
                history.append(point)
                if hasattr(progress, "history"):
                    progress.history(point)
                _plog(progress, f"epoch {point['epoch']}：" + "、".join(f"{k}={v}" for k, v in point.items() if k != "epoch"))

            for event, fn in (("on_train_start", on_train_start), ("on_train_epoch_start", on_train_epoch_start),
                              ("on_train_batch_end", on_train_batch_end), ("on_fit_epoch_end", on_fit_epoch_end)):
                model.add_callback(event, fn)

            model.train(
                data=os.path.join(work, "data.yaml"), epochs=epochs, imgsz=imgsz,
                batch=int(params.get("batch") or 8), patience=int(params.get("patience") or 50),
                lr0=float(params.get("lr0") or 0.001), workers=int(params.get("workers") or 0),
                device=device, project=os.path.join(work, "runs"), name="train", verbose=False, plots=False,
            )

            trainer = model.trainer
            best = str(getattr(trainer, "best", "") or "")
            report(0.93, "匯出 ONNX", None)
            export_model = YOLO(best) if best and os.path.isfile(best) else model
            onnx_path = export_model.export(format="onnx", imgsz=imgsz, dynamic=False, verbose=False)
            with open(str(onnx_path), "rb") as f:
                onnx_bytes = f.read()

            # 保留 best.pt（自動標記與續訓用）
            from django.conf import settings

            weights_dir = os.path.join(str(settings.VISION["ASSET_DIR"]), "dl", "weights")
            os.makedirs(weights_dir, exist_ok=True)
            weights_path = ""
            if best and os.path.isfile(best):
                weights_path = os.path.join(weights_dir, f"{os.path.basename(work)}-best.pt")
                shutil.copyfile(best, weights_path)

            last_point = history[-1] if history else {}
            metrics = {**last_point, "stopped_early": stopping, "weights_path": weights_path, "device": device}
            return TrainResult(
                onnx_bytes=onnx_bytes, metrics=metrics, tool_key=self.tool_key,
                tool_params={"labels": "\n".join(classes), "input_size": imgsz, "conf": 0.25, "iou": 0.45},
            )
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def suggest(self, labeled: list[SampleRef], unlabeled: list[SampleRef], classes: list[str], params: dict[str, Any]) -> list[Suggestion]:
        """自動標記：優先用上次訓練的 best.pt（或 params.weights 指定的 .pt）；
        第一次教導還沒有權重時，改用官方底模（COCO 預訓練，缺檔自動下載）產生物件輪廓提案——
        底模不認得你的類別，名稱對不上的提案一律掛到第一個類別，交給使用者確認／改類。"""
        if not unlabeled:
            return []
        if not classes:
            raise TrainError("先在「編輯類別」新增至少一個類別")
        weights = str(params.get("weights") or "")
        using_base = False
        if weights and not os.path.isfile(weights):
            raise TrainError(f"上次訓練的權重已遺失（{weights}）。重新訓練一次，或清掉專案參數 weights。")
        if not weights:
            weights = resolve_model(str(params.get("model") or "yolov8n-seg.pt"))
            if not os.path.isfile(weights):
                raise TrainError(f"找不到模型檔 {weights}。填官方底模名稱（會自動下載）或既有 .pt 路徑。")
            using_base = True
        YOLO = _import_ultralytics()
        import cv2

        model = YOLO(weights)
        names = {int(k): str(v) for k, v in (getattr(model, "names", {}) or {}).items()}
        conf = float(params.get("suggest_conf") or 0.4)
        imgsz = int(params.get("imgsz") or 640)
        out: list[Suggestion] = []
        for s in unlabeled:
            image = s.load()
            if image is None:
                continue
            h, w = image.shape[:2]
            # 底模提案限制數量：COCO 場景（人群/車流）會一口氣提案幾十個，全掛第一類會灌爆樣本
            results = model.predict(image, conf=conf, imgsz=imgsz, max_det=20 if using_base else 100, verbose=False)
            if not results:
                continue
            r = results[0]
            if r.masks is None:
                continue
            shapes_out, scores = [], []
            boxes = r.boxes
            for i, poly in enumerate(r.masks.xy):
                cls_id = int(boxes.cls[i].item())
                label = names.get(cls_id, str(cls_id))
                if label not in classes:
                    if not using_base:
                        continue
                    label = classes[0]  # 底模提案：名稱對不上就掛第一個類別，交給使用者改
                points = np.asarray(poly, dtype=np.float64)
                if len(points) < 3:
                    continue
                eps = 0.005 * cv2.arcLength(points.astype(np.float32).reshape(-1, 1, 2), True)
                approx = cv2.approxPolyDP(points.astype(np.float32).reshape(-1, 1, 2), eps, True).reshape(-1, 2)
                if len(approx) < 3:
                    continue
                shapes_out.append({"label": label, "kind": "polygon",
                                   "points": [[float(px) / w, float(py) / h] for px, py in approx]})
                scores.append(float(boxes.conf[i].item()))
            if shapes_out:
                out.append(Suggestion(sample_id=s.id, label="", score=round(float(np.mean(scores)), 4), shapes=shapes_out))
        return out


def _plog(progress: Any, message: str) -> None:
    if hasattr(progress, "log"):
        progress.log(message)
    log.info(message)


TRAINERS = [YoloSegTrainer]
