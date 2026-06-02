import cv2
import numpy as np
from utils import load_calibration_data, preprocess_image

class StereoEngine:
    def __init__(self, config_path, min_disparity=256, num_disparities=384, block_size=17, preprocess_mode="NORMAL", use_wls=True, scale=1.0):
        """
        初始化立體視覺引擎
        :param config_path: 校正 JSON 路徑
        :param min_disparity: 原始影像中的搜尋起點 (偏移量)
        :param num_disparities: 原始影像中的搜尋量程 (需為 16 倍數)
        :param block_size: 匹配窗大小 (建議 13~17)
        :param preprocess_mode: 預處理模式 (NORMAL, CLAHE, SOBEL, LAPLACIAN)
        :param use_wls: 是否開啟 WLS 濾波器
        :param scale: ROI 縮放比例 (例如 0.5 代表長寬各縮小一半，提速約 4~8 倍)
        """
        self.scale = scale
        self.min_disparity = min_disparity
        self.num_disparities = num_disparities
        self.block_size = block_size
        self.preprocess_mode = preprocess_mode
        self.use_wls = use_wls and hasattr(cv2, 'ximgproc')
        
        # 根據縮放比例調整內部 SGBM 參數
        # minDisparity 與 numDisparities 必須是縮放後的像素值，且 numDisparities 需為 16 倍數
        self._internal_min_disp = int(min_disparity * scale)
        self._internal_num_disp = int((num_disparities * scale + 15) // 16) * 16
        
        # 狀態快取
        self.calib = None
        self.config_path = config_path
        
        # 初始化 SGBM
        p1 = 8 * 3 * (block_size ** 2)
        p2 = 32 * 3 * (block_size ** 2)
        self.matcher = cv2.StereoSGBM_create(
            minDisparity=self._internal_min_disp,
            numDisparities=self._internal_num_disp,
            blockSize=block_size,
            P1=p1,
            P2=p2,
            disp12MaxDiff=1,
            uniquenessRatio=15,
            speckleWindowSize=200,
            speckleRange=2,
            mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY
        )
        
        # 初始化 WLS (選配)
        if self.use_wls:
            self.right_matcher = cv2.ximgproc.createRightMatcher(self.matcher)
            self.wls_filter = cv2.ximgproc.createDisparityWLSFilter(self.matcher)
            self.wls_filter.setLambda(8000)
            self.wls_filter.setSigmaColor(1.5)

    def _prepare_calibration(self, img_shape):
        """
        根據影像尺寸延遲初始化校正地圖
        """
        if self.calib is None or self.calib["map_l"][0].shape[:2] != img_shape:
            self.calib = load_calibration_data(self.config_path, img_shape)

    def compute_bboxes_depth(self, left_img, right_img, bboxes, debug=False):
        """
        計算多個 BBox 的深度統計值
        :param left_img: 左影像 (Gray or BGR)
        :param right_img: 右影像
        :param bboxes: [(x, y, w, h), ...]
        :param debug: 是否在回傳結果中包含視覺化影像 (debug_viz 欄位)
        :return: 統計結果列表 [dict, dict, ...]
        """
        if left_img is None or right_img is None:
            return []
            
        # 轉灰階
        l_gray = cv2.cvtColor(left_img, cv2.COLOR_BGR2GRAY) if len(left_img.shape) == 3 else left_img
        r_gray = cv2.cvtColor(right_img, cv2.COLOR_BGR2GRAY) if len(right_img.shape) == 3 else right_img
        
        height, width = l_gray.shape[:2]
        self._prepare_calibration((height, width))
        
        # 極線對齊
        rl = cv2.remap(l_gray, self.calib["map_l"][0], self.calib["map_l"][1], cv2.INTER_LINEAR)
        rr = cv2.remap(r_gray, self.calib["map_r"][0], self.calib["map_r"][1], cv2.INTER_LINEAR)
        
        # 預處理
        rlp = preprocess_image(rl, self.preprocess_mode)
        rrp = preprocess_image(rr, self.preprocess_mode)
        
        results = []
        f, b = self.calib["f"], self.calib["b"]
        
        # 如果是 debug 模式，先建立一張全圖視覺化底圖
        full_debug_viz = None
        if debug:
            full_debug_viz = cv2.cvtColor(rl, cv2.COLOR_GRAY2BGR)
            full_debug_viz = (full_debug_viz.astype(np.float32) * 0.3).astype(np.uint8)

        # 原始影像中的最大位移上限
        max_disp_orig = self.min_disparity + self.num_disparities

        for (x, y, w, h) in bboxes:
            # 安全邊界檢查
            x, y = max(0, x), max(0, y)
            w, h = min(w, width - x), min(h, height - y)
            if w <= 0 or h <= 0:
                results.append({"mean": -1, "median": -1, "min": -1, "max": -1})
                continue
                
            # ROI Padding (考慮原始影像中的視差搜尋範圍)
            xs = max(0, x - max_disp_orig)
            l_roi = rlp[y:y+h, xs:x+w]
            r_roi = rrp[y:y+h, xs:x+w]
            
            if l_roi.shape != r_roi.shape or l_roi.shape[1] <= 1:
                results.append({"mean": -1, "median": -1, "min": -1, "max": -1})
                continue
            
            # --- 實作縮放優化 ---
            if self.scale != 1.0:
                l_roi = cv2.resize(l_roi, None, fx=self.scale, fy=self.scale, interpolation=cv2.INTER_LINEAR)
                r_roi = cv2.resize(r_roi, None, fx=self.scale, fy=self.scale, interpolation=cv2.INTER_LINEAR)
                
            # 計算視差 (在縮放後的影像上)
            dl = self.matcher.compute(l_roi, r_roi)
            
            if self.use_wls:
                dr = self.right_matcher.compute(r_roi, l_roi)
                dl = self.wls_filter.filter(dl, l_roi, None, dr)
            
            # 取得有效視差區域 (扣除 Padding)
            # 注意：縮放後，x 與 xs 的位移也需縮放
            offset_scaled = int((x - xs) * self.scale)
            v_disp_scaled = dl[:, offset_scaled:].astype(np.float32) / 16.0
            
            # 還原視差值：除以 scale
            v_disp = v_disp_scaled / self.scale
            
            # 過濾無效點 (必須在原始搜尋區間內)
            mask = (v_disp > self.min_disparity + 0.1) & (v_disp < max_disp_orig)
            vp = v_disp[mask]
            
            res_dict = {"mean": -1, "median": -1, "min": -1, "max": -1}
            
            if len(vp) > 0:
                # 統計與轉換深度
                disp_median = float(np.median(vp))
                res_dict = {
                    "mean": round(float(np.mean(vp)), 2),
                    "median": round((b * f) / disp_median, 2),
                    "min": round((b * f) / float(np.max(vp)), 2),
                    "max": round((b * f) / float(np.min(vp)), 2)
                }

                # 渲染除錯圖
                if debug:
                    # 顏色映射需根據原始量程
                    v_scaled_color = np.clip((v_disp - self.min_disparity) * (255.0 / self.num_disparities), 0, 255).astype(np.uint8)
                    roi_color = cv2.applyColorMap(v_scaled_color, cv2.COLORMAP_JET)
                    
                    # 如果有縮放，熱度圖需放回原始 ROI 尺寸以便疊加
                    if self.scale != 1.0:
                        roi_color = cv2.resize(roi_color, (x+w-x, h), interpolation=cv2.INTER_NEAREST)
                        # 重新計算 mask 尺寸
                        mask_full = cv2.resize(mask.astype(np.uint8), (x+w-x, h), interpolation=cv2.INTER_NEAREST) > 0
                    else:
                        mask_full = mask
                        
                    full_debug_viz[y:y+h, x:x+w][mask_full] = roi_color[mask_full]
                    cv2.rectangle(full_debug_viz, (x, y), (x+w, y+h), (0, 255, 0), 2)

            # 將視覺化影像附加
            if debug:
                res_dict["debug_viz"] = full_debug_viz
                
            results.append(res_dict)
            
        return results
