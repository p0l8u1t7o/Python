import cv2
import numpy as np
import json
import os
import sys
from engine import StereoEngine
import sharedMemory as shm

# =========================
# 全域資源 (Persistent)
# =========================
_engine = None
_shm_ctx_l = None
_shm_ctx_r = None

# =========================================================
# INIT: 由 LabVIEW Python Node 在程式開始時呼叫一次
# =========================================================
def init(config_path, l_tag, r_tag, img_size_bytes):
    """
    初始化引擎與共享記憶體
    :param config_path: 校正 JSON 路徑
    :param l_tag: 左影像 SHM 標籤
    :param r_tag: 右影像 SHM 標籤
    :param img_size_bytes: 影像緩衝區大小
    """
    global _engine, _shm_ctx_l, _shm_ctx_r
    
    try:
        # 1. 實體化高效能引擎
        # 預設使用優化後的「黃金參數」
        _engine = StereoEngine(
            config_path=config_path,
            min_disparity=288,   # 鎖定有效區間提速
            num_disparities=352, # 窄窗搜尋
            block_size=17,       # 針對無紋理表面
            scale=0.5,           # 0.5x 縮放優化 (極速模式)
            use_wls=True         # 開啟平滑濾波器
        )
        
        # 2. 初始化共享記憶體讀取器
        _shm_ctx_l = shm.initialize(l_tag, img_size_bytes)
        _shm_ctx_r = shm.initialize(r_tag, img_size_bytes)
        
        return True
    except Exception as e:
        print(f"Python Init Error: {str(e)}")
        return False

# =========================================================
# RUN: 由 LabVIEW Python Node 在迴圈中連續呼叫
# =========================================================
def run(bbox_list_json):
    """
    執行深度計算
    :param bbox_list_json: BBox 列表 (JSON 字串或 List)
           格式: [[x, y, w, h], [x2, y2, w2, h2], ...]
    :return: 統計結果 JSON 字串
    """
    global _engine, _shm_ctx_l, _shm_ctx_r
    
    if _engine is None:
        return json.dumps({"error": "Engine not initialized"})
    
    try:
        # 1. 從共享記憶體獲取最新影像 (Zero-copy)
        img_l = shm.get_image(_shm_ctx_l)
        img_r = shm.get_image(_shm_ctx_r)
        
        if img_l is None or img_r is None:
            return json.dumps({"error": "Failed to read images from SHM"})
        
        # 2. 解析 BBox (處理 LabVIEW 傳入的 JSON 字串)
        if isinstance(bbox_list_json, str):
            bboxes = json.loads(bbox_list_json)
        else:
            bboxes = bbox_list_json
            
        # 3. 呼叫引擎計算
        # 這裡不開啟 debug 模式以維持最高速回傳
        results = _engine.compute_bboxes_depth(img_l, img_r, bboxes, debug=False)
        
        # 4. 回傳結果
        return json.dumps(results)
        
    except Exception as e:
        return json.dumps({"error": str(e)})

# =========================================================
# RELEASE: 程式結束時釋放資源
# =========================================================
def release():
    global _engine, _shm_ctx_l, _shm_ctx_r
    
    if _shm_ctx_l: shm.cleanup(_shm_ctx_l)
    if _shm_ctx_r: shm.cleanup(_shm_ctx_r)
    
    _engine = None
    _shm_ctx_l = _shm_ctx_r = None
    
    return True
