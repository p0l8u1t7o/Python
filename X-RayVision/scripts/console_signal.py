"""附加到指定行程的主控台並送出 Ctrl+Break，讓服務正常關閉 (與啟動器停止應用程式的方式相同)。

用法：python console_signal.py <pid>；結束代碼 0＝已送出，1＝無法附加 (行程不存在或沒有主控台)。
"""
import ctypes
import sys
import time
from ctypes import wintypes

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
CTRL_BREAK_EVENT = 1
HANDLER = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)


@HANDLER
def _ignore(_event):
    # 本程式也附加在同一個主控台上，攔下訊號以免自己被中斷
    return True


def main():
    pid = int(sys.argv[1])
    kernel32.FreeConsole()
    if not kernel32.AttachConsole(pid):
        return 1
    kernel32.SetConsoleCtrlHandler(_ignore, True)
    ok = kernel32.GenerateConsoleCtrlEvent(CTRL_BREAK_EVENT, 0)
    # 訊號由另一個執行緒非同步處理，等處理完才能卸離，否則會套用預設處理而結束本程式
    time.sleep(0.5)
    kernel32.FreeConsole()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
