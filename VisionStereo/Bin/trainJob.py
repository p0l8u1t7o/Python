#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
YOLO 分割訓練工作（供 labelServer 的網頁介面使用）
==================================================
參數與流程對應 yoloTrackTraining.py：訓練 → 匯出 → 複製到輸出資料夾，
差別是改成背景執行緒 + 可查詢進度 + 可中止。

進度來源是 ultralytics 的 callback：
    on_train_start      取得總 epoch 數與每個 epoch 的 batch 數
    on_train_batch_end  batch 進度、即時 loss；也是中止的檢查點
    on_fit_epoch_end    每個 epoch 的驗證指標（mAP 等），累積成歷史曲線
    on_train_end        最佳／最後權重路徑

中止方式是把 trainer.stop 設為 True。ultralytics 在 on_train_batch_end 之後
緊接著就是 `if self.stop: break`，所以會在當前 batch 立刻跳出，然後照常做
驗證與存檔——中止不會讓已訓練的權重白費。

用法
    import trainJob
    trainJob.start_job(data=..., epochs=100, ...)
    trainJob.get_status()
    trainJob.stop_job()
"""

import json
import os
import shutil
import sys
import threading
import time
import traceback
from pathlib import Path

_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
    sys.path.insert(0, str(_BIN))


# ╔══════════════════════════════════════════════════════════════╗
# ║          ▼  預設參數（對應 yoloTrackTraining.py）  ▼          ║
# ╚══════════════════════════════════════════════════════════════╝

DEFAULTS = {
    # ── 資料集與模型 ──────────────────────────
    "data":    "",                                    # data.yaml；空字串 = 用網頁目前開啟的資料集
    "model":   r"D:\Working Space\Python\VisionStereo\weights\best.pt",

    # ── 訓練參數 ──────────────────────────────
    "epochs":      100,
    "imgsz":       640,
    "batch":       16,
    "device":      "0",        # "0"=GPU0；"cpu"；"0,1"=多 GPU
    "workers":     8,
    "patience":    50,
    "lr0":         0.001,
    "lrf":         0.01,
    "amp":         True,
    "cache":       False,
    "resume":      False,
    "savePeriod":  -1,
    "overlapMask": True,
    "maskRatio":   4,
    "retinaMasks": False,
    "project":     r"D:\Working Space\Python\VisionStereo\weights",
    "name":        "ATD3",

    # ── 資料增強 ──────────────────────────────
    "hsv_h": 0.015, "hsv_s": 0.7, "hsv_v": 0.5, "bgr": 0.0,
    "degrees": 15.0, "translate": 0.15, "scale": 0.5, "shear": 5.0,
    "perspective": 0.0005,
    "flipud": 0.3, "fliplr": 0.5,
    "mosaic": 1.0, "close_mosaic": 15, "mixup": 0.1,
    "copy_paste": 0.3, "copy_paste_mode": "flip",

    # ── 匯出與輸出 ────────────────────────────
    "doExport":      True,
    "exportFormat":  "onnx",     # onnx | torchscript | engine | tflite | coreml
    "exportHalf":    False,
    "exportDynamic": False,
    "outputDir":     r"D:\Working Space\Python\VisionStereo\weights\ATD3",
    "copyBest":      True,
    "copyLast":      True,
    "copyExport":    True,
}

# 會直接轉交給 model.train() 的增強參數
AUG_KEYS = ("hsv_h", "hsv_s", "hsv_v", "bgr", "degrees", "translate", "scale",
            "shear", "perspective", "flipud", "fliplr", "mosaic",
            "close_mosaic", "mixup", "copy_paste", "copy_paste_mode")


# ══════════════════════════════════════════════════════════════
# 工作狀態
# ══════════════════════════════════════════════════════════════

_lock = threading.RLock()
_thread = None
_stop_flag = threading.Event()
_LOG_KEEP = 400
_log_base = 0

_state = {
    "running": False,
    "done": False,
    "error": "",
    "phase": "idle",       # idle|loading|training|exporting|copying|finished|stopped|error
    "stopping": False,
    "epoch": 0,
    "epochs": 0,
    "batch": 0,
    "batches": 0,
    "losses": {},
    "metrics": {},
    "fitness": 0.0,
    "bestFitness": 0.0,
    "bestEpoch": 0,
    "history": [],         # 每個 epoch 一筆
    "saveDir": "",
    "best": "",
    "last": "",
    "exported": "",
    "copied": [],
    "startedAt": 0.0,
    "elapsed": 0.0,
    "eta": 0.0,
    "epochSec": 0.0,
    "device": "",
    "cfg": {},
    "log": [],
}

_batch_i = 0
_epoch_t0 = 0.0
_epoch_times = []
_last_epoch_started = 0        # 最後一個真的進到訓練迴圈的 epoch（用來識別 final_eval）


def _set(**kw):
    with _lock:
        _state.update(kw)


def _log(msg):
    global _log_base
    with _lock:
        _state["log"].append(f"{time.strftime('%H:%M:%S')}  {msg}")
        over = len(_state["log"]) - _LOG_KEEP
        if over > 0:
            del _state["log"][:over]
            _log_base += over


def get_status(log_from=None):
    """回傳訓練進度；log_from 給定時只回傳新的記錄行。"""
    with _lock:
        st = dict(_state)
        st["history"] = [dict(h) for h in _state["history"]]
        st["losses"] = dict(_state["losses"])
        st["metrics"] = dict(_state["metrics"])
        st["copied"] = list(_state["copied"])
        st["cfg"] = dict(_state["cfg"])
        total = _log_base + len(_state["log"])
        if log_from is None:
            st["log"] = list(_state["log"])
            st["logFrom"] = _log_base
        else:
            start = max(0, min(len(_state["log"]), int(log_from) - _log_base))
            st["log"] = _state["log"][start:]
            st["logFrom"] = _log_base + start
        st["logNext"] = total
        if st["running"] and st["startedAt"]:
            st["elapsed"] = round(time.time() - st["startedAt"], 1)
        return st


def is_running():
    with _lock:
        return bool(_state["running"])


def stop_job():
    """要求中止：當前 batch 就跳出，仍會走完驗證與存檔。立即返回。"""
    if not is_running():
        return {"ok": True, "running": False, "message": "目前沒有進行中的訓練"}
    _stop_flag.set()
    _set(stopping=True)
    _log("收到中止要求，將在目前 batch 結束後停止（會保留已訓練的權重）…")
    return {"ok": True, "running": True, "message": "已送出中止要求"}


# ══════════════════════════════════════════════════════════════
# ultralytics callbacks
# ══════════════════════════════════════════════════════════════

def _loss_dict(t):
    try:
        if t.tloss is None:
            return {}
        vals = t.tloss.detach().cpu().reshape(-1).tolist()
        names = list(t.loss_names) if isinstance(t.loss_names, (list, tuple)) \
            else [str(t.loss_names)]
        return {str(n): round(float(v), 4) for n, v in zip(names, vals)}
    except Exception:                                     # noqa: BLE001
        return {}


def _cb_train_start(t):
    try:
        nb = len(t.train_loader)
    except Exception:                                     # noqa: BLE001
        nb = 0
    _set(phase="training", epochs=int(t.epochs), batches=nb,
         saveDir=str(t.save_dir), best=str(t.best), last=str(t.last))
    _log(f"開始訓練：{t.epochs} epochs、每個 epoch {nb} batches")
    _log(f"輸出目錄：{t.save_dir}")


def _cb_epoch_start(t):
    global _batch_i, _epoch_t0, _last_epoch_started
    _batch_i = 0
    _epoch_t0 = time.time()
    _last_epoch_started = int(t.epoch) + 1
    _set(epoch=_last_epoch_started, batch=0)


def _cb_batch_end(t):
    global _batch_i
    _batch_i += 1
    # 中止檢查點：ultralytics 在這個 callback 之後就是 `if self.stop: break`
    if _stop_flag.is_set() and not getattr(t, "stop", False):
        t.stop = True
        _log(f"於 epoch {int(t.epoch) + 1} batch {_batch_i} 中止")
    if _batch_i == 1 or _batch_i % 5 == 0:
        _set(batch=_batch_i, losses=_loss_dict(t))


def _cb_fit_epoch_end(t):
    global _epoch_times
    ep = int(t.epoch) + 1
    metrics = {}
    # 訓練結束後 final_eval 會把 t.epoch 加一再觸發一次（驗證的是 best.pt，
    # 不是第 N+1 個 epoch）。只要 epoch 超過「最後一個真的開始過的 epoch」就是它，
    # 中途中止的情況也一樣成立。只更新指標，不能算成新的一輪。
    if ep > _last_epoch_started:
        final = {str(k).replace("metrics/", ""): round(float(v), 5)
                 for k, v in (t.metrics or {}).items()
                 if isinstance(v, (int, float))}
        _set(metrics=final)
        m = final.get("mAP50-95(M)", final.get("mAP50-95(B)", 0))
        _log(f"最終驗證（best.pt）：mAP50-95={m:.4f}")
        return

    for k, v in (t.metrics or {}).items():
        try:
            metrics[str(k).replace("metrics/", "")] = round(float(v), 5)
        except (TypeError, ValueError):
            pass
    fitness = float(t.fitness) if t.fitness is not None else 0.0
    losses = _loss_dict(t)

    if _epoch_t0:
        _epoch_times.append(time.time() - _epoch_t0)
        del _epoch_times[:-10]                 # 只用最近 10 個 epoch 估時間
    avg = sum(_epoch_times) / len(_epoch_times) if _epoch_times else 0.0

    with _lock:
        hist = _state["history"]
        row = {"epoch": ep, "fitness": round(fitness, 5), **metrics, **losses}
        if hist and hist[-1]["epoch"] == ep:   # final_eval 會再觸發一次，覆蓋即可
            hist[-1] = row
        else:
            hist.append(row)
        best_fit = _state["bestFitness"]
        best_ep = _state["bestEpoch"]
        if fitness >= best_fit:
            best_fit, best_ep = fitness, ep
        remain = max(0, int(_state["epochs"]) - ep)
        _state.update({
            "batch": _batch_i,                 # 收尾補齊最後幾個 batch 的顯示
            "metrics": metrics, "losses": losses, "fitness": round(fitness, 5),
            "bestFitness": round(best_fit, 5), "bestEpoch": best_ep,
            "epochSec": round(avg, 1), "eta": round(avg * remain, 1),
        })

    m50 = metrics.get("mAP50(M)", metrics.get("mAP50(B)", 0))
    m5095 = metrics.get("mAP50-95(M)", metrics.get("mAP50-95(B)", 0))
    _log(f"epoch {ep}/{_state['epochs']}  mAP50={m50:.4f}  mAP50-95={m5095:.4f}  "
         f"fitness={fitness:.4f}  ({avg:.1f}s/epoch)")


def _cb_train_end(t):
    _set(best=str(t.best), last=str(t.last), saveDir=str(t.save_dir))
    _log(f"訓練迴圈結束：best={t.best}")


_CALLBACKS = {
    "on_train_start": _cb_train_start,
    "on_train_epoch_start": _cb_epoch_start,
    "on_train_batch_end": _cb_batch_end,
    "on_fit_epoch_end": _cb_fit_epoch_end,
    "on_train_end": _cb_train_end,
}


# ══════════════════════════════════════════════════════════════
# 啟動 / 主流程
# ══════════════════════════════════════════════════════════════

def start_job(**opts):
    """啟動背景訓練，立即返回。"""
    global _thread, _batch_i, _epoch_t0, _epoch_times, _last_epoch_started
    with _lock:
        if _state["running"]:
            return {"ok": False, "error": "已有進行中的訓練"}

        cfg = dict(DEFAULTS)
        cfg.update({k: v for k, v in opts.items() if v is not None and v != ""})

        _stop_flag.clear()
        _batch_i, _epoch_t0, _epoch_times, _last_epoch_started = 0, 0.0, [], 0
        _state.update({
            "running": True, "done": False, "error": "", "phase": "loading",
            "stopping": False, "epoch": 0, "epochs": int(cfg["epochs"]),
            "batch": 0, "batches": 0, "losses": {}, "metrics": {},
            "fitness": 0.0, "bestFitness": 0.0, "bestEpoch": 0, "history": [],
            "saveDir": "", "best": "", "last": "", "exported": "", "copied": [],
            "startedAt": time.time(), "elapsed": 0.0, "eta": 0.0, "epochSec": 0.0,
            "device": str(cfg["device"]), "log": [],
            # 實際送進 train() 的設定，讓網頁能顯示「這次跑的是什麼」
            "cfg": {k: cfg[k] for k in
                    ("data", "model", "epochs", "imgsz", "batch", "device",
                     "workers", "patience", "lr0", "lrf", "project", "name")},
        })

    _thread = threading.Thread(target=_run, args=(cfg,), daemon=True, name="trainJob")
    _thread.start()
    return {"ok": True, "running": True}


def _run(cfg):
    try:
        _train(cfg)
    except Exception as e:                                # noqa: BLE001
        _log(f"[ERROR] {e}")
        _log(traceback.format_exc())
        _set(error=str(e), phase="error")
    finally:
        with _lock:
            _state["running"] = False
            _state["done"] = True
            _state["stopping"] = False
            _state["elapsed"] = round(time.time() - _state["startedAt"], 1)
            if _state["phase"] not in ("error",):
                _state["phase"] = "stopped" if _stop_flag.is_set() else "finished"


def _filter_supported(kwargs):
    """濾掉這個 ultralytics 版本不支援的參數，行為與 yoloTrackTraining.py 相同。"""
    try:
        from ultralytics.cfg import DEFAULT_CFG_DICT
    except ImportError:
        return dict(kwargs)
    ok = {k: v for k, v in kwargs.items() if k in DEFAULT_CFG_DICT}
    dropped = [k for k in kwargs if k not in DEFAULT_CFG_DICT]
    if dropped:
        _log(f"[WARN] 此 ultralytics 版本不支援下列參數，已略過：{', '.join(dropped)}")
    return ok


def _train(cfg):
    _log("載入 ultralytics / torch…")
    os.environ.setdefault("YOLO_OFFLINE", "1")
    import torch
    from ultralytics import YOLO

    data_yaml = str(cfg["data"])
    if not data_yaml or not os.path.exists(data_yaml):
        raise FileNotFoundError(f"找不到 data.yaml：{data_yaml}")
    if not os.path.exists(str(cfg["model"])):
        raise FileNotFoundError(f"找不到模型檔：{cfg['model']}")

    device = str(cfg["device"])
    if device != "cpu" and not torch.cuda.is_available():
        _log("[WARN] 偵測不到可用的 CUDA，改用 CPU 訓練（會很慢）")
        device = "cpu"
    _set(device=device)

    _log(f"資料：{data_yaml}")
    _log(f"模型：{cfg['model']}  device={device}  "
         f"epochs={cfg['epochs']}  imgsz={cfg['imgsz']}  batch={cfg['batch']}")

    aug = _filter_supported({k: cfg[k] for k in AUG_KEYS if k in cfg})

    model = YOLO(str(cfg["model"]), task="segment")
    for ev, fn in _CALLBACKS.items():
        model.add_callback(ev, fn)

    results = model.train(
        data=data_yaml,
        epochs=int(cfg["epochs"]),
        imgsz=int(cfg["imgsz"]),
        batch=int(cfg["batch"]),
        device=device,
        project=str(cfg["project"]),
        name=str(cfg["name"]),
        workers=int(cfg["workers"]),
        patience=int(cfg["patience"]),
        lr0=float(cfg["lr0"]),
        lrf=float(cfg["lrf"]),
        amp=bool(cfg["amp"]),
        cache=bool(cfg["cache"]),
        resume=bool(cfg["resume"]),
        save_period=int(cfg["savePeriod"]),
        overlap_mask=bool(cfg["overlapMask"]),
        mask_ratio=int(cfg["maskRatio"]),
        retina_masks=bool(cfg["retinaMasks"]),
        **aug,
    )

    save_dir = Path(getattr(results, "save_dir", _state["saveDir"] or "."))
    best_pt = save_dir / "weights" / "best.pt"
    last_pt = save_dir / "weights" / "last.pt"
    _set(saveDir=str(save_dir), best=str(best_pt), last=str(last_pt))
    _log(f"訓練結束：{save_dir}")

    stopped = _stop_flag.is_set()
    if stopped:
        _log("（已中止）已訓練的權重仍保留在上述目錄")

    # ── 匯出 ────────────────────────────────
    exported = ""
    if cfg["doExport"] and best_pt.exists():
        _set(phase="exporting")
        fmt = str(cfg["exportFormat"])
        _log(f"匯出 {fmt.upper()}…")
        try:
            exp = YOLO(str(best_pt)).export(
                format=fmt, imgsz=int(cfg["imgsz"]),
                half=bool(cfg["exportHalf"]), dynamic=bool(cfg["exportDynamic"]))
            exported = str(exp)
            _set(exported=exported)
            _log(f"匯出完成：{exported}")
        except Exception as e:                            # noqa: BLE001
            _log(f"[WARN] 匯出失敗（訓練結果不受影響）：{e}")
    elif cfg["doExport"]:
        _log("[WARN] 找不到 best.pt，略過匯出")

    # ── 複製到輸出資料夾 ─────────────────────
    out_dir = Path(str(cfg["outputDir"]))
    todo = []
    if cfg["copyBest"]:
        todo.append((best_pt, "best.pt"))
    if cfg["copyLast"]:
        todo.append((last_pt, "last.pt"))
    if cfg["copyExport"] and exported:
        todo.append((Path(exported), Path(exported).name))

    if todo:
        _set(phase="copying")
        out_dir.mkdir(parents=True, exist_ok=True)
        copied = []
        for src, label in todo:
            if not src.exists():
                _log(f"[WARN] {label} 不存在，略過：{src}")
                continue
            dst = out_dir / src.name
            shutil.copy2(src, dst)
            copied.append(str(dst))
            _log(f"複製 {label} → {dst}")
        _set(copied=copied)

    _log("全部完成" if not stopped else "已中止（匯出／複製仍已完成）")


# ══════════════════════════════════════════════════════════════
# 命令列
# ══════════════════════════════════════════════════════════════

def main():
    import argparse
    ap = argparse.ArgumentParser(description="YOLO 分割訓練（可查詢進度、可中止）")
    ap.add_argument("--data", default=DEFAULTS["data"], help="data.yaml 路徑")
    ap.add_argument("--model", default=DEFAULTS["model"])
    ap.add_argument("--epochs", type=int, default=DEFAULTS["epochs"])
    ap.add_argument("--imgsz", type=int, default=DEFAULTS["imgsz"])
    ap.add_argument("--batch", type=int, default=DEFAULTS["batch"])
    ap.add_argument("--device", default=DEFAULTS["device"])
    ap.add_argument("--name", default=DEFAULTS["name"])
    ap.add_argument("--project", default=DEFAULTS["project"])
    ap.add_argument("--no-export", action="store_true")
    args = ap.parse_args()

    start_job(data=args.data, model=args.model, epochs=args.epochs,
              imgsz=args.imgsz, batch=args.batch, device=args.device,
              name=args.name, project=args.project,
              doExport=not args.no_export)

    shown = 0
    while True:
        with _lock:
            new = _state["log"][shown:]
            shown = len(_state["log"])
            running = _state["running"]
        for line in new:
            print(line)
        if not running:
            break
        time.sleep(1.0)

    st = get_status()
    print(json.dumps({k: st[k] for k in
                      ("phase", "epoch", "epochs", "bestFitness", "bestEpoch",
                       "best", "exported", "error")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
