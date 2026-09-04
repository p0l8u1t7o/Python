"""YOLO trainers（torch + ultralytics，可選依賴、延後 import）：實例分割、物件偵測、影像分類、旋轉框（OBB）。

沒安裝 torch/ultralytics 時平台照常啟動、trainer 照常列在目錄；開始訓練／自動標記時
才 import，缺件回 TrainError 附安裝指令。做法對齊 Temp/WebTraining.md（trainJob.py）：
- 進度：ultralytics callbacks（on_train_start / on_train_batch_end / on_fit_epoch_end）。
- 中止：設 trainer.stop = True，當前 batch 跳出後照常驗證、存檔、匯出（已訓練的不白費）。
- final_eval 會多觸發一次 on_fit_epoch_end，用「最後真的開始的 epoch」擋掉。
- 指標去掉 metrics/ 前綴；分割任務優先 (M)（mask）、退回 (B)（box）。
- 設 YOLO_OFFLINE=1 避免無網路環境卡住（基底權重 .pt 第一次仍需可取得）。

產物：best.pt（主產物，給原生 yolo_* 工具，GPU 推論、後處理與訓練一致）＋ ONNX（副產物，給 dl_* ONNX 工具或
外部執行環境）；兩者都存成 model 資產（jobs._train），專案的 last_asset 指向 .pt。
姿態（pose）訓練需要關鍵點標記介面，目前只提供推論工具（yolo_pose 用官方或自備權重）。
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
import threading
from typing import Any

import cv2
import numpy as np

from apps.vision.dl.base import ProgressFn, SampleRef, Suggestion, TrainCancelled, Trainer, TrainError, TrainResult
from apps.vision.tools.base import Param

log = logging.getLogger(__name__)

_INSTALL_HINT = "The training dependencies are needed: run .\\scripts\\setup_dl.ps1 (torch cu128 first, then ultralytics, onnx, onnxslim and onnxruntime-gpu; see requirements-dl.txt and the installation section of the deep-learning documentation)"


def _import_ultralytics():
    try:
        os.environ.setdefault("YOLO_OFFLINE", "1")
        from ultralytics import YOLO  # noqa: PLC0415

        return YOLO
    except ImportError:
        raise TrainError(f"ultralytics and torch are not installed.{_INSTALL_HINT}") from None


#: ultralytics 官方資產的下載位置：新模型（yolo26…）在 v8.4.0，舊的（yolov8／yolo11／SAM）在 v8.3.0；依序嘗試。
_ASSET_RELEASES = ("v8.4.0", "v8.3.0")
_ASSET_URL = "https://github.com/ultralytics/assets/releases/download/{release}/{name}"
#: 允許自動下載的官方檔名：YOLO 底模（任務後綴 -seg／-cls／-pose／-obb 等）＋SAM 系列（智慧選取用 mobile_sam／sam2）。
_ASSET_NAME = re.compile(r"^(yolo(v?\d+)[a-z]?(-[a-z0-9]+)*|mobile_sam|sam_[bl]|sam2(\.1)?_[tsbl]|FastSAM-[sx])\.pt$")


def _weights_dir() -> str:
    from django.conf import settings

    folder = os.path.join(str(settings.VISION["ASSET_DIR"]), "dl", "weights")
    os.makedirs(folder, exist_ok=True)
    return folder


def resolve_model(name: str, log_fn=None) -> str:
    """把模型參數解析成本地檔案路徑；官方底模名稱（yolo11n.pt、yolo11n-seg.pt、sam2.1_t.pt 等）不存在時自動下載。

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
    # 序列化下載：訓練執行緒與 auto-label 請求可能同時發現快取不存在（共用 .part 會互踩、
    # Windows 下還會把交錯寫入的損毀檔升級成永久快取），取得鎖後重查一次直接省掉重複下載。
    with _download_lock:
        if os.path.isfile(target):
            return target
        _download(base, target, log_fn)
    if log_fn:
        log_fn(f"The stock model {base} has been downloaded to {target}")
    return target


def _download(base: str, target: str, log_fn=None) -> None:
    import http.client
    import urllib.error
    import urllib.request

    last_error = ""
    for release in _ASSET_RELEASES:
        url = _ASSET_URL.format(release=release, name=base)
        if log_fn:
            log_fn(f"Downloading the stock model {base} (first use; {url}）…")
        log.info("下載 YOLO 底模 %s ← %s", base, url)
        fd, tmp = tempfile.mkstemp(dir=_weights_dir(), suffix=".part")
        try:
            # fdopen 放前面：urlopen 失敗時 with 會先把 fd 關掉，Windows 才刪得掉 .part
            with os.fdopen(fd, "wb") as f, urllib.request.urlopen(url, timeout=120) as resp:
                shutil.copyfileobj(resp, f)
            os.replace(tmp, target)
            return
        except urllib.error.HTTPError as exc:
            _cleanup(tmp)
            if exc.code == 404:
                last_error = f"HTTP 404 ({url})"
                continue  # 下一個 release
            raise TrainError(f"The stock model {base} could not be downloaded (HTTP {exc.code}). {url}") from None
        except (urllib.error.URLError, http.client.HTTPException, OSError, TimeoutError) as exc:
            _cleanup(tmp)
            raise TrainError(f"The stock model {base} could not be downloaded ({exc}). Check that the server has network access, or download it by hand and put the path in the base model parameter: {url}") from None
    raise TrainError(f"The model name {base} does not exist (there is no such file in the official assets; {last_error}). Check the name, for example yolo11n.pt, yolo11n-seg.pt, yolo11n-cls.pt or yolo11n-obb.pt.")


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
        # 只有「同名 (M) 指標存在」時才略過 (B)（分割任務優先 mask 指標）。
        # 注意括號：寫成 `A and B or C` 會讓 (M) 鍵自己命中 C 而全部被丟掉（mAP 曲線就消失了）。
        if name.endswith("(B)") and (base + "(M)" in raw or "metrics/" + base + "(M)" in raw):
            continue
        out[base] = value
    return out


def _params(base_model: str, task: str) -> list[Param]:
    imgsz = ([{"value": 224, "label": "224 (recommended)"}, {"value": 320, "label": "320"}] if task == "classify"
             else [{"value": 320, "label": "320"}, {"value": 480, "label": "480"}, {"value": 640, "label": "640 (recommended)"}, {"value": 960, "label": "960"}])
    out = [
        Param("model", "Base model", kind="text", default=base_model, help_text="An ultralytics model name (downloaded on first use) or a path to a .pt file; the best.pt of a previous run continues training from it."),
        Param("epochs", "Epochs", kind="number", default=100, minimum=1, maximum=2000),
        Param("imgsz", "Image size", kind="select", default=224 if task == "classify" else 640, options=imgsz),
        Param("batch", "Batch", kind="number", default=8, minimum=1, maximum=128, group="Advanced"),
        Param("patience", "Early stop patience", kind="number", default=50, minimum=0, maximum=500, group="Advanced"),
        Param("lr0", "Initial learning rate", kind="number", default=0.001, minimum=0.00001, maximum=0.1, step=0.0001, group="Advanced"),
        Param("val_ratio", "Validation ratio", kind="number", default=0.2, minimum=0.05, maximum=0.5, step=0.05, group="Advanced"),
        Param("workers", "DataLoader workers", kind="number", default=0, minimum=0, maximum=16, group="Advanced", help_text="0 is recommended on Windows, which is the most reliable when training on a background thread."),
        Param("suggest_conf", "Automatic labelling confidence threshold", kind="range", default=0.4, minimum=0.05, maximum=0.95, step=0.05, group="Advanced",
              help_text="Before any training the stock model proposes (anything whose name does not match is attached to the first class, for you to correct); afterwards best.pt is used."),
        Param("degrees", "Rotation angle (+/-)", kind="number", default=0, minimum=0, maximum=180, group="Augment", help_text="The maximum random rotation; 0 is recommended on a line where the object's orientation is fixed."),
        Param("fliplr", "Horizontal flip probability", kind="range", default=0.5, minimum=0, maximum=1, step=0.1, group="Augment"),
    ]
    if task != "classify":
        out.append(Param("mosaic", "Mosaic augmentation", kind="range", default=1.0, minimum=0, maximum=1, step=0.1, group="Augment", help_text="Tiles four samples into one training image; lower it when there are few samples."))
    return out


class _YoloTrainer(Trainer):
    """四個 YOLO trainer 的共同流程：資料集匯出 → 訓練（callbacks）→ best.pt ＋ ONNX；suggest 依任務轉 shapes／label。"""

    task = "segment"  # segment | detect | classify | obb
    base_model = "yolov8n-seg.pt"
    label_mode = "shapes"
    tool_key = "yolo_segment"  # 主產物 best.pt 給的原生工具
    onnx_tool_key = "dl_instance"  # 副產物 ONNX 給的工具（"" = 沒有對應的 ONNX 工具）
    devices = ("cuda", "cpu")
    min_per_class = 1

    def train(self, samples: list[SampleRef], classes: list[str], params: dict[str, Any], device: str, progress: ProgressFn) -> TrainResult:
        from apps.vision.dl.shapes import export_classify_dataset, export_dataset

        if not classes:
            raise TrainError("At least one class must be defined")
        if self.task == "classify" and len(classes) < 2:
            raise TrainError("Classification needs at least two classes")
        YOLO = _import_ultralytics()
        import torch

        if device == "cuda" and not torch.cuda.is_available():
            _plog(progress, "[WARN] CUDA was not found; falling back to CPU training, which is slow")
            device = "cpu"

        progress(0.01, "Staging the YOLO dataset", None)
        work = tempfile.mkdtemp(prefix="vs-yolo-")
        stopping = False

        def report(frac: float, stage: str, metrics: dict[str, Any] | None) -> None:
            nonlocal stopping
            try:
                progress(frac, stage, metrics)
            except TrainCancelled:
                stopping = True

        try:
            val_ratio = float(params.get("val_ratio") or 0.2)
            if self.task == "classify":
                stats = export_classify_dataset(((s.id, s.path, s.label, s.split) for s in samples), classes, work, val_ratio=val_ratio)
                data = work
            else:
                stats = export_dataset(((s.id, s.path, s.shapes, s.split) for s in samples), classes, work, val_ratio=val_ratio, task=self.task)
                data = os.path.join(work, "data.yaml")
            _plog(progress, f"Dataset ({self.task}): train {stats['train']}, val {stats['val']}"
                  + (f", test {stats['test']}" if stats.get("test") else "") + f" ({work})")
            if stats["train"] < 1 or stats["val"] < 1:
                raise TrainError("Too few labelled samples: train and val need at least one each (ten or more per class is recommended)")

            model = YOLO(resolve_model(str(params.get("model") or self.base_model), lambda m: _plog(progress, m)))
            if str(getattr(model, "task", "") or self.task) != self.task:
                raise TrainError(f"The base model's task is {model.task}, while this trainer needs {self.task} (for example {self.base_model}）")
            epochs = int(params.get("epochs") or 100)
            imgsz = int(params.get("imgsz") or (224 if self.task == "classify" else 640))
            state: dict[str, Any] = {"epochs": epochs, "batches": 1, "batch": 0, "epoch": 0, "last_started": -1}
            history: list[dict[str, Any]] = []

            def on_train_start(t):
                state["epochs"] = int(getattr(t, "epochs", epochs))
                _plog(progress, f"Training started: {state['epochs']} epochs, imgsz {imgsz}, device {device}")

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
                report(0.05 + 0.85 * frac, f"Training (epoch {state['epoch'] + 1}/{state['epochs']}）",
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

            train_kw: dict[str, Any] = dict(
                data=data, epochs=epochs, imgsz=imgsz,
                batch=int(params.get("batch") or 8), patience=int(params.get("patience") or 50),
                lr0=float(params.get("lr0") or 0.001), workers=int(params.get("workers") or 0),
                degrees=float(params.get("degrees") or 0.0),
                fliplr=float(params.get("fliplr")) if params.get("fliplr") is not None else 0.5,
                device=device, project=os.path.join(work, "runs"), name="train", verbose=False, plots=False,
            )
            if self.task != "classify":
                train_kw["mosaic"] = float(params.get("mosaic")) if params.get("mosaic") is not None else 1.0
            model.train(**train_kw)

            trainer = model.trainer
            best = str(getattr(trainer, "best", "") or "")
            if not (best and os.path.isfile(best)):
                last = str(getattr(trainer, "last", "") or "")
                best = last if last and os.path.isfile(last) else ""
            report(0.93, "Exporting ONNX", None)
            export_model = YOLO(best) if best else model
            onnx_path = export_model.export(format="onnx", imgsz=imgsz, dynamic=False, verbose=False)
            with open(str(onnx_path), "rb") as f:
                onnx_bytes = f.read()
            weights_bytes = b""
            if best:
                with open(best, "rb") as f:
                    weights_bytes = f.read()

            # 保留 best.pt（自動標記與續訓用）
            from django.conf import settings

            weights_dir = os.path.join(str(settings.VISION["ASSET_DIR"]), "dl", "weights")
            os.makedirs(weights_dir, exist_ok=True)
            weights_path = ""
            if best:
                weights_path = os.path.join(weights_dir, f"{os.path.basename(work)}-best.pt")
                shutil.copyfile(best, weights_path)

            names = getattr(export_model, "names", None) or {}
            ordered = [str(names[k]) for k in sorted(names)] if isinstance(names, dict) else [str(v) for v in names]
            last_point = history[-1] if history else {}
            metrics = {**last_point, "stopped_early": stopping, "weights_path": weights_path, "device": device, "task": self.task, "classes": ordered or classes}
            native = {"model_name": "", "imgsz": imgsz, "conf": 0.25, "iou": 0.45} if self.task != "classify" else {"model_name": "", "imgsz": imgsz, "threshold": 0.5}
            onnx_params = self._onnx_params(ordered or classes, imgsz)
            return TrainResult(
                onnx_bytes=onnx_bytes, metrics=metrics, tool_key=self.onnx_tool_key, tool_params=onnx_params,
                weights_bytes=weights_bytes, weights_ext=".pt", weights_tool_key=self.tool_key, weights_tool_params=native,
            )
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _onnx_params(self, classes: list[str], imgsz: int) -> dict[str, Any]:
        if self.task == "classify":
            # YOLO-cls 匯出的 ONNX 已含 softmax；前處理只除以 255（RGB）
            return {"labels": "\n".join(classes), "input_size": imgsz, "mean": "0", "std": "1", "color_order": "rgb", "apply_softmax": False}
        if self.task == "obb":
            return {"labels": "\n".join(classes), "input_size": imgsz}
        return {"labels": "\n".join(classes), "input_size": imgsz, "conf": 0.25, "iou": 0.45}

    # ------------------------------------------------------------------ 自動標記
    def suggest(self, labeled: list[SampleRef], unlabeled: list[SampleRef], classes: list[str], params: dict[str, Any]) -> list[Suggestion]:
        """自動標記：優先用上次訓練的 best.pt（或 params.weights 指定的 .pt）；
        第一次教導還沒有權重時，改用官方底模（COCO／ImageNet 預訓練，缺檔自動下載）產生提案——
        底模不認得你的類別：shapes 任務名稱對不上的提案一律掛到第一個類別交給使用者確認；分類任務底模的類別名
        對不上就沒有提案（分類的提案只有訓練過才有意義）。"""
        if not unlabeled:
            return []
        if not classes:
            raise TrainError("Add at least one class under Edit classes first")
        weights = str(params.get("weights") or "")
        using_base = False
        if weights and not os.path.isfile(weights):
            raise TrainError(f"The weights from the last training run have gone ({weights}). Train again, or clear the project's weights parameter.")
        if not weights:
            weights = resolve_model(str(params.get("model") or self.base_model))
            if not os.path.isfile(weights):
                raise TrainError(f"Model file not found: {weights}. Give a stock model name (which downloads automatically) or the path to an existing .pt file.")
            using_base = True
        YOLO = _import_ultralytics()
        model = YOLO(weights)
        names = {int(k): str(v) for k, v in (getattr(model, "names", {}) or {}).items()}
        conf = float(params.get("suggest_conf") or 0.4)
        imgsz = int(params.get("imgsz") or 0)
        if not imgsz:
            # 用權重檔記錄的訓練 imgsz：推論尺寸與訓練不一致時（例如訓練 320、預設 640）會整批漏檢
            try:
                ckpt = getattr(model, "ckpt", None) or {}
                imgsz = int((ckpt.get("train_args") or {}).get("imgsz") or 0) if isinstance(ckpt, dict) else 0
            except (TypeError, ValueError):
                imgsz = 0
        imgsz = imgsz or (224 if self.task == "classify" else 640)
        out: list[Suggestion] = []
        for s in unlabeled:
            image = s.load()
            if image is None:
                continue
            h, w = image.shape[:2]
            # 底模提案限制數量：COCO 場景（人群/車流）會一口氣提案幾十個，全掛第一類會灌爆樣本
            results = model.predict(image, conf=conf if self.task != "classify" else 0.0, imgsz=imgsz, max_det=20 if using_base else 100, verbose=False)
            if not results:
                continue
            r = results[0]
            if self.task == "classify":
                probs = getattr(r, "probs", None)
                if probs is None:
                    continue
                label = names.get(int(probs.top1), "")
                score = float(probs.top1conf)
                if label in classes and score >= conf:
                    out.append(Suggestion(sample_id=s.id, label=label, score=round(score, 4)))
                continue
            shapes_out, scores = self._shapes_from_result(r, names, classes, using_base, w, h)
            if shapes_out:
                out.append(Suggestion(sample_id=s.id, label="", score=round(float(np.mean(scores)), 4), shapes=shapes_out))
        return out

    def _shapes_from_result(self, r: Any, names: dict[int, str], classes: list[str], using_base: bool, w: int, h: int) -> tuple[list[dict[str, Any]], list[float]]:
        shapes_out: list[dict[str, Any]] = []
        scores: list[float] = []

        def pick_label(cls_id: int) -> str | None:
            label = names.get(cls_id, str(cls_id))
            if label in classes:
                return label
            return classes[0] if using_base else None  # 底模提案：名稱對不上就掛第一個類別，交給使用者改

        cl = lambda v: float(min(1.0, max(0.0, v)))  # noqa: E731
        if self.task == "segment":
            if r.masks is None:
                return shapes_out, scores
            boxes = r.boxes
            for i, poly in enumerate(r.masks.xy):
                label = pick_label(int(boxes.cls[i].item()))
                if label is None:
                    continue
                points = np.asarray(poly, dtype=np.float32)
                if len(points) < 3:
                    continue
                eps = 0.005 * cv2.arcLength(points.reshape(-1, 1, 2), True)
                approx = cv2.approxPolyDP(points.reshape(-1, 1, 2), eps, True).reshape(-1, 2)
                if len(approx) < 3:
                    continue
                shapes_out.append({"label": label, "kind": "polygon", "points": [[cl(px / w), cl(py / h)] for px, py in approx]})
                scores.append(float(boxes.conf[i].item()))
        elif self.task == "detect":
            boxes = r.boxes
            if boxes is None:
                return shapes_out, scores
            xyxy = boxes.xyxy.cpu().numpy()
            for i in range(len(xyxy)):
                label = pick_label(int(boxes.cls[i].item()))
                if label is None:
                    continue
                x0, y0, x1, y1 = (float(v) for v in xyxy[i])
                shapes_out.append({"label": label, "kind": "bbox", "points": [[cl(x0 / w), cl(y0 / h)], [cl(x1 / w), cl(y1 / h)]]})
                scores.append(float(boxes.conf[i].item()))
        elif self.task == "obb":
            obb = getattr(r, "obb", None)
            if obb is None:
                return shapes_out, scores
            corners = obb.xyxyxyxy.cpu().numpy()
            for i in range(len(corners)):
                label = pick_label(int(obb.cls[i].item()))
                if label is None:
                    continue
                shapes_out.append({"label": label, "kind": "polygon", "points": [[cl(float(x) / w), cl(float(y) / h)] for x, y in corners[i]]})
                scores.append(float(obb.conf[i].item()))
        return shapes_out, scores


class YoloSegTrainer(_YoloTrainer):
    kind = "yolo_seg"
    label = "Instance segmentation (YOLO-seg)"
    description = "Trains a YOLO segmentation model from polygon labels, finding each object's outline and class. It needs ultralytics (torch) and an NVIDIA GPU is recommended. The stock model downloads on first use, and automatic labelling works even before training (the stock model proposes outlines, attached to the first class). Products: best.pt for the YOLO instance segmentation tool and ONNX for the DL instance segmentation tool."
    task = "segment"
    base_model = "yolov8n-seg.pt"
    tool_key = "yolo_segment"
    onnx_tool_key = "dl_instance"
    params = _params("yolov8n-seg.pt", "segment")


class YoloDetectTrainer(_YoloTrainer):
    kind = "yolo_detect"
    label = "Object detection (YOLO)"
    description = "Trains a YOLO detection model from bounding boxes (a polygon becomes its bounding box), finding each object's box and class. The fastest to train and the cheapest to label. Products: best.pt for the YOLO object detection tool and ONNX for the DL object detection tool."
    task = "detect"
    base_model = "yolo11n.pt"
    tool_key = "yolo_detect"
    onnx_tool_key = "dl_detect"
    params = _params("yolo11n.pt", "detect")


class YoloClassifyTrainer(_YoloTrainer):
    kind = "yolo_cls"
    label = "Image classification (YOLO-cls)"
    description = "One class per image, fine-tuning a YOLO classification model from an ImageNet-pretrained base. More accurate than the built-in MLP classifier, and it needs ultralytics (torch). Products: best.pt for the YOLO classification tool and ONNX for the DL classification tool."
    task = "classify"
    base_model = "yolo11n-cls.pt"
    label_mode = "classes"
    tool_key = "yolo_classify"
    onnx_tool_key = "dl_classify"
    min_per_class = 2
    params = _params("yolo11n-cls.pt", "classify")


class YoloObbTrainer(_YoloTrainer):
    kind = "yolo_obb"
    label = "Oriented box detection (YOLO-obb)"
    description = "Trains a YOLO OBB model from polygons (reduced to their minimum-area rotated rectangle) or boxes, returning each object's rotated rectangle (centre, size and angle), which suits parts that sit at an angle. Product: best.pt for the YOLO oriented box tool (the ONNX is for external use only)."
    task = "obb"
    base_model = "yolo11n-obb.pt"
    tool_key = "yolo_obb"
    onnx_tool_key = ""
    params = _params("yolo11n-obb.pt", "obb")


def _plog(progress: Any, message: str) -> None:
    if hasattr(progress, "log"):
        progress.log(message)
    log.info(message)


TRAINERS = [YoloSegTrainer, YoloDetectTrainer, YoloClassifyTrainer, YoloObbTrainer]
