"""擬合層：把一整條實測曲線壓縮成 1 個有物理意義的數字 k_eff。

這是全專案的降維關鍵。原本一批實驗是 8 個測點 × 4 個元素 = 32 個數字，
擬合後變成 4 個 k_eff。40 批就變成「每個元素 40 個 k_eff」，是個
40 筆資料、2 個自變數的小問題——用高斯過程或線性回歸都綽綽有餘。
"""

from .censored import tobit_nll, TobitData
from .fit_keff import KeffFit, fit_keff, fit_batch, fit_all
from .bootstrap import bootstrap_keff, BootstrapResult

__all__ = [
    "tobit_nll", "TobitData",
    "KeffFit", "fit_keff", "fit_batch", "fit_all",
    "bootstrap_keff", "BootstrapResult",
]
