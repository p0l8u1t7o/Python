"""資料夾外掛：把 .py 檔丟進這個資料夾，重啟後端就會自動掛載，不用改 .env。

繼承下面任一基底類別即可（同一個檔案可以放多個、混著放）：
    apps.vision.tools.base.Tool          自訂工具 → 出現在畫布調色盤
    apps.vision.sources.grabbers.Grabber 自訂影像來源 → 出現在「影像來源」kind 下拉
    apps.comm.writers.Writer             自訂整合輸出 → 出現在「連線」kind 下拉

每個外掛檔內可用變數控制顯示與掛載（慣例寫在檔案最上面，方便現場修改）：
    ENABLED = False        整個檔案不掛載
    class X(...):
        enabled = False    只停用這個類別
        label = "顯示名稱"
        description = "說明文字"

兩種形態：
    plugins/my_tool.py               單檔外掛
    plugins/my_project/__init__.py   資料夾型外掛（整個外掛專案丟進來；__init__.py 匯出要掛載的類別）

外掛有自己的依賴時附 requirements.txt（資料夾型放在資料夾內、單檔用 <name>.requirements.txt），
`.\scripts\dev.ps1 -Setup` 會自動安裝；同行程載入，依賴必須裝進平台的 .venv。
Python 版本與平台不一致的外掛不能同行程載入，改跑 sidecar（見 docs/plugins.html「整合考量」）。

規則與範例見 docs/plugins.html；本資料夾的 example_*.py 都是可直接執行的範例。
檔名底線開頭（_xxx.py／_xxx/）不會被掃描。
"""
