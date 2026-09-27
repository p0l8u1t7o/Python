# 五站電控配置與 3D 檢視

更新日期：2026-09-27。依各專案既有製程、機構與選型規劃，將電盤內的功能元件、安裝位置及功能線路加入同一個 3D 場景。

## 操作

1. 點「電盤配線」或上方 **⚡ 電控規劃**。
2. 選擇「外殼／剖視／透視」觀察機櫃。透視會保留半透明櫃門、門鎖及側板。
3. 從清單選元件會切到特寫；也可以在剖視／透視中點選 3D 元件，再按「元件特寫」。黃色框與標籤指出選取項，相關功能線路會加亮。
4. 說明卡顯示用途、規劃型號、W × H × D 外形與功能連接。「電盤總覽」回到電盤配置視角；關閉或切回全景會還原機櫃材質。
5. 播放、暫停、跳站與時間滑桿仍由主時間軸控制；電控頁只讀取製程狀態。指示燈沒有獨立計時器，暫停會保留同一製程狀態。
6. 「匯出元件與連接清單」可下載目前站別的 JSON 配置。

## 各站配置

| 專案 | 可選電控元件 | 配置依據與差異 |
| --- | ---: | --- |
| AutomaticAcid-BaseTitration | 11 | 保留整合電腦主控架構；CRC9M、24 V、儀器 I/O、天平序列介面、移液 RS-485、Metrohm Remote 交握與安全控制。擴大桌下箱體以容納控制器及接線空間。 |
| MilitaryGradePC | 19 | 主控制櫃含 PLC、安全、F/T、光源及 RC8A；相鄰周邊驅動櫃規劃滑軌、兩端堆料升降、取像頭、翻轉及輸送共 6 個驅動位置，另有運動交握與視覺 IPC。兩櫃間有穿板線束。 |
| PCB-CopperAssembly | 40 | EtherCAT 主控、PLC、I/O、視覺 IPC、光源、供電與安全。雙頭各 XY＋4 組 Z/θ，合計 20 個驅動；另按 S1/S3 的 XY 與上下料 XZ 規劃 8 個位置。共 28 個獨立驅動外形，逐一列出用途。 |
| RobotArmPressSSD | 13 | RC8A、PLC、安全、F/T、視覺 IPC、光源、I/O 與動力／控制支路。 |
| shutter assembly | 14 | RC8A、PLC、安全、雙相機視覺、頻閃光源、真空／壓力介面與工具／治具電磁閥島。電磁閥安裝在背板上，控制線與氣管分開。 |

總計 97 個可選元件。數量代表本次可檢視的電控功能元件；每個端子、螺絲、線槽梳齒及既有現場相機並未各計為一項。

詳細清單位於每個專案的 `docs/electrical-plan.md`。既有規劃依據：滴定站 `system-plan.md`、PCB 站 `machine-plan.md`、SSD 與快門站 `automation-plan.md`，軍規站 `phase1-scope.md` 與既有成本選型摘要。

## 尺寸及來源

- COBOTTA PRO 900 的控制器採 CRC9M；標準型外形以 W420 × H200 × D360 mm 建模，控制器裝在有腳座的承板上。[DENSO CRC9 官方規格](https://www.denso-wave.com/ja/robot/product/controller/rc9.html)。
- RC8A 採標準型約 W357 × H94 × D320 mm 包絡；前面接口與散熱細節為可辨識的示意幾何。[DENSO Robotics 官方型錄](https://www.densorobotics-europe.com/fileadmin/Brochures/DENSO_Robotics_Europe_Brochure_2026.pdf)。
- GC-1000 使用 W60 × H90 × D95 mm 外形。安全功能與回路仍需依設備需求設計，元件額定能力不等於整機已完成安全驗證。[KEYENCE 官方規格](https://www.keyence.eu/products/safety/safety-controller/gc/models/gc-1000/)。
- KV-X 僅沿用專案的控制平台規劃；未指定 CPU 與擴充型號，3D 外形為配置估算。[KEYENCE KV-X 官方文件](https://www.keyence.com/support/user/controls/kv-x/manual/)。
- 背板、DIN 導軌、端子、線槽與固定方式參考常見盤內安裝方式。[Phoenix Contact 安裝與配線](https://www.phoenixcontact.com/en-us/industries/control-cabinet-building/mounting-and-wiring)。

其餘斷路器、電源、接觸器、IPC、驅動及介面外形在說明卡標註「配置估算，型號待選」。元件沒有為了塞入箱體而任意縮放；本次調整了箱體／背板布局及工業電腦規劃包絡，使所畫外形有實際安裝空間。

## 配線與驗證範圍

橙色表示動力／AC、藍色為 24 VDC、青綠為通訊、黃色為安全交握、紫色為感測／I/O。這些是展示分類色，不是施工線色規範。所畫線束表示功能連接；未展開 L/N/PE、每條訊號回路與全部芯線，也未據此決定線徑、斷路器容量、接觸器數量、STO 接法、EMC 或冷卻能力。

`tools/verify-electrical-plan.mjs` 檢查所有元件主體都在機櫃可用空間內、主體彼此不重疊、功能線路不穿過元件主體、孔洞實際貫穿、線材通過接頭，以及背板固定柱接觸櫃壁。軍規站的兩個櫃體另檢查對輸送線立柱與腳座的淨空。測試也檢查暫停不改變同一製程的電控指示狀態。

結果：[電控幾何檢查](../review/electrical-plan-checks.json)、[配線取樣檢查](../review/cable-checks.json)、[機構回歸檢查](../review/interference-checks.json)。各站 `review/electrical-plan.png` 為瀏覽器檢視截圖。

這是向用戶說明配置、空間及控制分工的工程模擬；完整採購 BOM、負載表、施工接線圖與實機安全／熱設計仍需依最終料號完成。
