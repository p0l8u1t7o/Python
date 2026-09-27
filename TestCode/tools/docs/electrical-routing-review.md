# 五站穿板孔與桌下電盤配線

更新日期：2026-09-27。

五個網頁新增「電盤配線」視角，暫時隱藏櫃門及側板，保留台面、孔洞與接頭，方便查看線材如何進入電盤。切回「全景」或其他視角、啟用產品焦點，會恢復櫃門。動畫仍使用原本時間軸。

## 實際補上的幾何

- 桌板與機櫃頂板以帶孔網格製作；孔洞貫穿板厚，並非黑色貼圖。
- 穿板接頭包含中空套筒、上方六角壓帽、下方鎖帽及護線膠圈，線路從中心連續通過。
- 實心櫃體改為有厚度的外殼，內部繪製安裝背板、DIN 導軌、端子排、控制器外形、開槽線槽及接地線。
- 背板有連至櫃壁的固定柱與螺栓；導軌、線槽及接地端子也有安裝零件。
- 線路延伸至桌下電盤端子；快門站氣管另接電磁閥島，閥島以安裝座固定在背板上。

| 專案 | 進線位置與走向 | 穿板接頭數 |
| --- | --- | ---: |
| AutomaticAcid-BaseTitration | 手臂、天平及電腦線穿過上下兩層桌板，再接桌下控制器與 I/O 箱 | 6 |
| MilitaryGradePC | 相機與軌道供電線從櫃頂接入輸送線下方電盤 | 2 |
| PCB-CopperAssembly | 供料區與上視相機的訊號線穿過底座櫃頂，接至控制背板 | 4 |
| RobotArmPressSSD | 手臂、輸送感測器及全局相機線穿過機台底櫃頂板 | 4 |
| shutter assembly | 手臂線束、照明線及氣管穿過桌板；上視相機在桌下接電盤 | 3 |

## 檢查與修正

`node tools/verify-cable-routing.mjs` 同時檢查五站共用程式一致性、外露線路取樣碰撞與拖鏈運動。新增的 `check-feedthroughs.mjs` 使用實際網格射線檢查孔中心及邊側暢通、孔旁仍有板材，並確認每個接頭上、中、下三個高度都有線材穿過，包含線徑淨空。另以射線檢查背板固定柱的末端確實接觸櫃壁。

本次修正滴定站兩條線在桌板下方太早彎曲、碰到下鎖帽的情況。軍規站新增電盤亦移至相鄰立柱之間，縮為 460 mm 寬並落地；其機構檢查新增對 24 個輸送線立柱及腳座的淨空檢查，最小間距為 10 mm。

配線總表：[review/cable-checks.json](../review/cable-checks.json)。各站 `review/cables.json` 列出每個情境的接頭、射線、穿線與固定柱檢查數。四站既有機構回歸結果：[review/interference-checks.json](../review/interference-checks.json)。快門站另執行 `verify.mjs`、`verify-physics.mjs` 及 `verify-product-detail.mjs`。

本次屬動畫幾何與安裝方式示意；機構與配線檢查採有限時間取樣。孔徑、接頭、端子及控制器外形尚未對應最終採購料號，也未完成全線材互撞、柔性下垂、熱設計或實機配電設計。

## 檢視截圖

- [滴定站](../../AutomaticAcid-BaseTitration/review/electrical-routing.png)
- [軍規站](../../MilitaryGradePC/review/electrical-routing.png)
- [PCB 站](../../PCB-CopperAssembly/review/electrical-routing.png)
- [SSD 站](../../RobotArmPressSSD/review/electrical-routing.png)
- [快門站](../../shutter%20assembly/review/electrical-routing.png)
