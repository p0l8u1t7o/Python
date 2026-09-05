"""
列出這台電腦可用的相機，讓使用者選一台。

名稱來源 (依可用性擇一)：
    1. pygrabber (DirectShow)：裝置順序與 OpenCV CAP_DSHOW 的索引一致，最可靠。
    2. Windows PnP (PowerShell Get-PnpDevice Class=Camera)：只有名稱，順序不保證與索引相同。
實際能不能開、解析度多少，一律用 OpenCV 逐一索引試開 (probe) 確認。
"""
import platform
import subprocess

import cv2

BACKEND = cv2.CAP_DSHOW if platform.system() == "Windows" else cv2.CAP_ANY


def _names_pygrabber():
    try:
        from pygrabber.dshow_graph import FilterGraph
        return list(FilterGraph().get_input_devices()), "DirectShow"
    except Exception:  # noqa: BLE001  (未安裝或非 Windows)
        return None, None


def _names_pnp():
    if platform.system() != "Windows":
        return None, None
    cmd = ("Get-PnpDevice -PresentOnly | Where-Object { $_.Class -eq 'Camera' } | "
           "Select-Object -ExpandProperty FriendlyName")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=15)
        names = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
        return names, "PnP (順序未必對應索引)"
    except Exception:  # noqa: BLE001
        return None, None


def probe(index, timeout_frames=5):
    """試開一個索引：回傳 (ok, width, height, fps)"""
    cap = cv2.VideoCapture(index, BACKEND)
    if not cap.isOpened():
        cap.release()
        return False, 0, 0, 0.0
    ok = False
    for _ in range(timeout_frames):
        ok, frame = cap.read()
        if ok and frame is not None:
            break
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
    cap.release()
    return bool(ok), w, h, fps


def list_cameras(max_index=8, do_probe=True):
    """
    回傳 [dict(index, name, ok, width, height, fps)]。
    有 DirectShow 名稱時只列名稱數量內的索引；否則試開 0..max_index-1，能開的才列。
    """
    names, source = _names_pygrabber()
    if not names:
        names, source = _names_pnp()
    cams = []
    if names and source == "DirectShow":
        indices = range(len(names))
    else:
        indices = range(max_index)
    for i in indices:
        name = names[i] if (names and i < len(names)) else f"Camera {i}"
        ok, w, h, fps = probe(i) if do_probe else (True, 0, 0, 0.0)
        if source == "DirectShow" or ok:
            cams.append(dict(index=i, name=name, ok=ok, width=w, height=h, fps=fps))
    return cams, source or "unknown"


def format_table(cams, source):
    lines = [f"可用相機 (名稱來源: {source})：", f"  {'#':>2}  {'狀態':<6} {'解析度':<11} {'fps':>5}  名稱"]
    for c in cams:
        st = "可用" if c["ok"] else "打不開"
        res = f"{c['width']}x{c['height']}" if c["ok"] else "-"
        lines.append(f"  {c['index']:>2}  {st:<6} {res:<11} {(("%.0f" % c["fps"]) if c["fps"] > 0 else "-"):>5}  {c['name']}")
    if not cams:
        lines.append("  (沒有找到相機)")
    return "\n".join(lines)


def choose_camera(cams):
    """在終端讓使用者選一台；只有一台可用就直接用它。回傳 index 或 None"""
    usable = [c for c in cams if c["ok"]]
    if not usable:
        return None
    if len(usable) == 1:
        print(f"只有一台可用，使用 #{usable[0]['index']} {usable[0]['name']}")
        return usable[0]["index"]
    default = usable[0]["index"]
    while True:
        ans = input(f"請輸入要用的相機編號 (預設 {default}): ").strip()
        if not ans:
            return default
        if ans.isdigit() and any(c["index"] == int(ans) and c["ok"] for c in cams):
            return int(ans)
        print("無效的編號，請重新輸入。")


if __name__ == "__main__":
    cams_, src_ = list_cameras()
    print(format_table(cams_, src_))
