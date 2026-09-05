# Flip-Chip X 光量測：演算法結果 vs 人工分類基準

- 影像: RD-1.tif (2768x2160 px)，分析時間 2026-09-05T20:03:33
- 演算法參數: scale=1.0, pad_r=[13.0, 32.0], min_sep=4.0, lo/hi_frac=0.25/0.75, gauss_sigma=2.5
- 演算法輸出: 候選 753、位點 471 (two-level 103 / single 368)、晶片矩形 7、群 6
- two-level 偏移量 px: 中位 2.89、P95 4.16、最大 6.87，超過 5.0 px: 2 顆
- 全域相似變換 (焊點→凸塊): 平移 (0.801, -1.705) px, 旋轉 0.026 deg, 縮放 1.001

## 類別定義
- die (晶片): 背景灰階圖上比周圍暗、填滿率高的矩形區域 (可巢狀，parent 為包住它的外層矩形)
- pad (基板焊點): 位點斜坡 75% 等高線擬合的外圓
- bump (金屬凸塊): 位點斜坡 25% 等高線擬合的內圓；two-level 表示內外圓半徑差夠大、偏移量可信；single 表示分不出兩層

## 晶片矩形
| 矩形 | parent | 層 | bbox (x,y,w,h) | 填滿率 | 位點 | two-level | 平均 (dx,dy) | 一致性 R | t | 判定 | 人工 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| D1 | D2 | 0 | (57,60,1306,1034) | 0.84 | 265 | 0 | (-0.09,-0.16) | 0.24 | 3.4 | 無法判定(單一斜坡) | 刪除 |
| D2 | D5 | 1 | (0,0,1688,1266) | 0.91 | 328 | 0 | (-0.11,-0.11) | 0.19 | 2.8 | 無法判定(單一斜坡) | 同意 |
| D3 | D6 | 1 | (1935,48,800,2069) | 0.92 | 91 | 82 | (2.5,0.41) | 0.88 | 19.8 | 疑似整體晶片偏移 | 同意 |
| D4 | D7 | 1 | (69,1594,482,512) | 0.94 | 1 | 0 | - | - | - | 無法判定(單一斜坡) | 刪除 |
| D5 | - | 2 | (0,0,1750,1359) | 0.96 | 341 | 2 | (-0.13,-0.12) | 0.19 | 2.7 | 無法判定(單一斜坡) | 刪除 |
| D6 | - | 2 | (1861,0,907,2160) | 0.95 | 115 | 99 | (2.33,0.44) | 0.87 | 20.0 | 疑似整體晶片偏移 | 刪除 |
| D7 | - | 2 | (0,1424,660,736) | 0.92 | 3 | 0 | (3.06,2.48) | 0.76 | 1.8 | 無法判定(單一斜坡), 外形一致拉長 軸-74deg | 忽略 |

## 人工分類統計 (列 = 演算法類別，欄 = 人工最終類別)
| 演算法 \ 人工 | die | pad | bump | ignore | deleted | 同意率 |
|---|---|---|---|---|---|---|
| die | 2 | 0 | 0 | 1 | 4 | 2/7 (29%) |
| pad | 0 | 397 | 0 | 0 | 74 | 397/471 (84%) |
| bump | 0 | 0 | 397 | 0 | 69 | 397/466 (85%) |

- 人工動過的物件: 148，新增物件: 0，與演算法不同的: 148
- 使用者備註: 1. 有抓到金屬凸塊的圓並在基板焊點圓之上的才納入。
2. 晶片區域內如果都沒有金屬凸塊和基板焊點，則忽略。

## 與演算法不同的物件 (最多列 60 筆，完整清單在 JSON)
| 物件 | 演算法 | 人工 | 位置 | 半徑/尺寸 | 量測 (type, offset, edge_sep, depth, note) |
|---|---|---|---|---|---|
| D1 | die | deleted | (57,60) | 1306x1034 | 無法判定(單一斜坡) |
| D4 | die | deleted | (69,1594) | 482x512 | 無法判定(單一斜坡) |
| D5 | die | deleted | (0,0) | 1750x1359 | 無法判定(單一斜坡) |
| D6 | die | deleted | (1861,0) | 907x2160 | 疑似整體晶片偏移 |
| D7 | die | ignore | (0,1424) | 660x736 | 無法判定(單一斜坡), 外形一致拉長 軸-74deg |
| P1 | pad | deleted | (266.56,17.94) | r=19.8 | single, 4.4, 4.86, 81.1, edges not separable in this array (single ramp) |
| B1 | bump | deleted | (262.28,18.99) | r=14.94 | single, 4.4, 4.86, 81.1, edges not separable in this array (single ramp) |
| P3 | pad | deleted | (745.43,14.69) | r=14.64 | single, 4.41, 4.52, 85.0, edges not separable in this array (single ramp) |
| B3 | bump | deleted | (741.06,15.33) | r=10.12 | single, 4.41, 4.52, 85.0, edges not separable in this array (single ramp) |
| P4 | pad | deleted | (2622.8,6.6) | r=17.04 | single, None, None, 114.6, inner edge not found |
| P5 | pad | deleted | (32.54,24.34) | r=31.17 | two-level, 6.87, 8.26, 113.8,  |
| B5 | bump | deleted | (25.82,25.77) | r=22.91 | two-level, 6.87, 8.26, 113.8,  |
| P6 | pad | deleted | (62.26,21.27) | r=20.91 | single, 4.71, 9.49, 91.4, inner fit inconsistent with profile (11.4 vs 15.5) |
| B6 | bump | deleted | (62.58,16.56) | r=11.42 | single, 4.71, 9.49, 91.4, inner fit inconsistent with profile (11.4 vs 15.5) |
| P7 | pad | deleted | (110.82,24.7) | r=20.86 | two-level, 5.35, 5.25, 41.3,  |
| B7 | bump | deleted | (114.75,21.06) | r=15.62 | two-level, 5.35, 5.25, 41.3,  |
| P9 | pad | deleted | (387.52,34.65) | r=19.89 | single, 4.71, 6.22, 44.0, edges not separable in this array (single ramp) |
| B9 | bump | deleted | (391.94,33.0) | r=13.67 | single, 4.71, 6.22, 44.0, edges not separable in this array (single ramp) |
| P11 | pad | deleted | (507.45,56.19) | r=19.22 | single, 8.25, 8.5, 43.8, inner fit inconsistent with profile (10.7 vs 5.5) |
| B11 | bump | deleted | (501.3,61.71) | r=10.73 | single, 8.25, 8.5, 43.8, inner fit inconsistent with profile (10.7 vs 5.5) |
| P20 | pad | deleted | (1196.22,29.11) | r=20.65 | single, 7.98, 7.72, 54.1, edges not separable in this array (single ramp) |
| B20 | bump | deleted | (1204.12,28.01) | r=12.93 | single, 7.98, 7.72, 54.1, edges not separable in this array (single ramp) |
| P22 | pad | deleted | (1436.01,25.42) | r=19.82 | single, 8.2, 9.44, 43.0, inner fit inconsistent with profile (10.4 vs 16.0) |
| B22 | bump | deleted | (1428.85,21.41) | r=10.38 | single, 8.2, 9.44, 43.0, inner fit inconsistent with profile (10.4 vs 16.0) |
| P23 | pad | deleted | (2071.54,22.89) | r=17.89 | single, 3.13, 2.72, 66.6, edges not separable in this array (single ramp) |
| B23 | bump | deleted | (2073.48,25.35) | r=15.18 | single, 3.13, 2.72, 66.6, edges not separable in this array (single ramp) |
| P34 | pad | deleted | (2015.7,64.4) | r=16.28 | single, 1.38, 3.9, 54.6, edges not separable in this array (single ramp) |
| B34 | bump | deleted | (2015.33,63.08) | r=12.38 | single, 1.38, 3.9, 54.6, edges not separable in this array (single ramp) |
| P43 | pad | deleted | (876.45,119.04) | r=19.48 | single, 3.94, 5.78, 40.5, inner fit inconsistent with profile (13.7 vs 5.0) |
| B43 | bump | deleted | (879.94,117.22) | r=13.71 | single, 3.94, 5.78, 40.5, inner fit inconsistent with profile (13.7 vs 5.0) |
| P53 | pad | deleted | (641.31,171.86) | r=15.72 | single, 1.55, 3.77, 42.3, edges not separable in this array (single ramp) |
| B53 | bump | deleted | (640.74,170.42) | r=11.95 | single, 1.55, 3.77, 42.3, edges not separable in this array (single ramp) |
| P60 | pad | deleted | (1234.63,174.6) | r=19.72 | single, 5.41, 6.06, 43.6, inner fit inconsistent with profile (13.7 vs 10.0) |
| B60 | bump | deleted | (1231.04,178.64) | r=13.67 | single, 5.41, 6.06, 43.6, inner fit inconsistent with profile (13.7 vs 10.0) |
| P67 | pad | deleted | (751.05,180.75) | r=18.91 | single, None, None, 34.3, inner edge not found |
| P74 | pad | deleted | (1971.27,202.13) | r=23.29 | single, 6.05, 7.54, 33.8, inner fit inconsistent with profile (15.8 vs 11.0) |
| B74 | bump | deleted | (1972.05,196.14) | r=15.76 | single, 6.05, 7.54, 33.8, inner fit inconsistent with profile (15.8 vs 11.0) |
| P83 | pad | deleted | (799.67,254.42) | r=19.46 | single, 4.64, 5.77, 43.2, inner fit inconsistent with profile (13.7 vs 17.0) |
| B83 | bump | deleted | (804.3,254.75) | r=13.7 | single, 4.64, 5.77, 43.2, inner fit inconsistent with profile (13.7 vs 17.0) |
| P86 | pad | deleted | (1123.62,241.47) | r=15.0 | single, None, None, 37.4, inner edge not found |
| P110 | pad | deleted | (397.94,304.27) | r=17.41 | single, 2.45, 3.73, 44.9, edges not separable in this array (single ramp) |
| B110 | bump | deleted | (400.37,303.96) | r=13.68 | single, 2.45, 3.73, 44.9, edges not separable in this array (single ramp) |
| P115 | pad | deleted | (961.33,332.8) | r=17.63 | single, 4.54, 6.49, 41.7, edges not separable in this array (single ramp) |
| B115 | bump | deleted | (964.57,329.61) | r=11.14 | single, 4.54, 6.49, 41.7, edges not separable in this array (single ramp) |
| P121 | pad | deleted | (25.39,372.85) | r=18.65 | single, 6.05, 7.97, 48.5, edges not separable in this array (single ramp) |
| B121 | bump | deleted | (21.27,377.27) | r=10.68 | single, 6.05, 7.97, 48.5, edges not separable in this array (single ramp) |
| P131 | pad | deleted | (1370.54,369.47) | r=17.4 | single, 3.22, 4.01, 42.6, edges not separable in this array (single ramp) |
| B131 | bump | deleted | (1371.53,366.41) | r=13.39 | single, 3.22, 4.01, 42.6, edges not separable in this array (single ramp) |
| P138 | pad | deleted | (557.13,386.59) | r=17.93 | single, 3.19, 3.64, 46.9, edges not separable in this array (single ramp) |
| B138 | bump | deleted | (560.22,387.42) | r=14.29 | single, 3.19, 3.64, 46.9, edges not separable in this array (single ramp) |
| P141 | pad | deleted | (960.61,419.34) | r=20.04 | single, 6.58, 8.75, 42.7, inner fit inconsistent with profile (11.3 vs 7.0) |
| B141 | bump | deleted | (966.01,415.58) | r=11.29 | single, 6.58, 8.75, 42.7, inner fit inconsistent with profile (11.3 vs 7.0) |
| P161 | pad | deleted | (1131.2,422.97) | r=16.1 | single, 1.8, 3.65, 42.7, edges not separable in this array (single ramp) |
| B161 | bump | deleted | (1132.83,422.2) | r=12.46 | single, 1.8, 3.65, 42.7, edges not separable in this array (single ramp) |
| P182 | pad | deleted | (158.14,521.02) | r=17.83 | single, 2.77, 9.97, 50.6, edges not separable in this array (single ramp) |
| B182 | bump | deleted | (160.68,519.89) | r=7.86 | single, 2.77, 9.97, 50.6, edges not separable in this array (single ramp) |
| P185 | pad | deleted | (323.66,520.69) | r=15.01 | single, 0.81, 2.91, 49.0, edges not separable in this array (single ramp) |
| B185 | bump | deleted | (322.85,520.75) | r=12.1 | single, 0.81, 2.91, 49.0, edges not separable in this array (single ramp) |
| P192 | pad | deleted | (1130.5,503.6) | r=15.49 | single, 2.5, 4.44, 43.7, edges not separable in this array (single ramp) |
| B192 | bump | deleted | (1130.27,501.11) | r=11.05 | single, 2.5, 4.44, 43.7, edges not separable in this array (single ramp) |

## 請語言模型協助的方向
1. 根據不同意/漏檢/誤檢的分佈 (位置、半徑、深度、edge_sep、note)，指出演算法哪個階段 (偵測 / 圓擬合 / two-level 判定 / 晶片矩形) 最需要調整，並建議具體參數或方法。
2. 若某些物件人工歸為 bump 但演算法只給 single，說明可能的影像原因與可行的量測改法。
3. 評估晶片矩形分割是否符合實際晶片邊界，提出更穩健的邊緣特徵做法。