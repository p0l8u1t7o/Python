# 第三方元件與格式參考

- [Three.js](https://github.com/mrdoob/three.js)：MIT；WebGL、glTF、幾何、環境光與控制器。完整授權見 `node_modules/three/LICENSE`。
- [three-mesh-bvh](https://github.com/gkjohnson/three-mesh-bvh)：MIT；組裝順序推論的射線與最近點查詢。完整授權見 `node_modules/three-mesh-bvh/LICENSE`。
- [occt-import-js](https://github.com/kovacsv/occt-import-js)：MIT 包裝器及其 OpenCascade / Emscripten 依賴；瀏覽器 CAD 解析。套件附帶的授權條款仍適用。
- [Open CASCADE Technology](https://github.com/Open-Cascade-SAS/OCCT)：LGPL-2.1 與 OCCT exception；精細 STEP 轉換與 glTF 匯出。
- [CadQuery OCP](https://github.com/CadQuery/OCP)：Python 綁定，本機安装的 `cadquery-ocp 8.0.1.0.0` 套件 metadata 標示 Apache-2.0；其內含 OpenCascade 與 VTK 依各自授權。僅供離線建庫，沒有將 Python 執行環境嵌入網頁。
- [olefile](https://github.com/decalage2/olefile)：BSD；讀取舊版原生檔 OLE 容器。

原生顯示快取讀取器由本專案實作，容器與面三角帶語法參考 [cadmpeg 的 SLDPRT 格式規格](https://github.com/cadmpeg/cadmpeg/blob/main/docs/formats/sldprt.md)（作者 cadmpeg 專案贡献者，CC BY 4.0）。本專案修改用途為有界解壓與 CRC 驗證、三角帶驗證、XML 引用定位及 GLB 輸出；不是原格式規格的完整實作或 SolidWorks 官方 SDK。來源檔的著作權與授權不因轉換而改變。

Vite、Prettier 及其他套件的授權保留於各自安裝目錄。發佈軟體前應一併保留所散布套件的完整授權文字。本專案沒有引用商用 CAD SDK 或非商業限定的解析套件。
