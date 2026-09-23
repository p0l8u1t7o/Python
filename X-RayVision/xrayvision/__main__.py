import sys

from .cli import main

# Windows 多行程以 spawn 啟動子行程時會重新匯入主模組，必須加上保護，避免子行程再次執行主程式
if __name__ == "__main__":
    sys.exit(main())
