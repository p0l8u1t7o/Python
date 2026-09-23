"""
原廠端工具 (不隨產品發布)：發行建置，產生安裝目錄樹、安裝程式 (setup.exe) 與更新檔 (.xrvupd)

  python tools/release/build_release.py [--skip-web] [--no-smoke] [--no-installer]
        [--update-key tools/keys/update_private_DEV.pem] [--update-with-runtime] [--min-from 0.1.0]
        [--notes-zh "…"] [--notes-en "…"] [--sign "signtool sign /fd sha256 /f cert.pfx /p … $f"]

輸出 build/release/<版本>/：
  stage/                               安裝目錄樹 (= 安裝後的 C:\\Program Files\\X-RayVision)
    launcher/launcher.py               啟動器 (只用標準函式庫)
    launcher/python/                   啟動器專用執行環境 (進版時不替換)
    service/XRayVisionService.exe,.xml Windows 服務包裝
    versions/<版本>/python/            產品執行環境 (embeddable Python＋固定版本依賴)
    versions/<版本>/app/               程式 (xrayvision/) 與前端 (web/dist/)
    versions/<版本>/version.json
    current.json
  X-RayVision-<版本>-setup.exe         安裝程式 (找得到 Inno Setup 時)
  X-RayVision-<版本>.xrvupd            更新檔 (指定 --update-key 時)
  build-info.json                      版本、外部元件來源與各產出檔的 SHA-256

下載的外部元件 (Python embeddable、服務包裝程式、繁中安裝語系檔) 快取在 build/cache/。
建置後預設執行冒煙測試：以 stage 內的啟動器實際啟動服務，確認內建標準影像自我檢查通過。
"""
import argparse
import glob
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "release"))

PRODUCT = "X-RayVision"
SERVICE_EXE = "XRayVisionService"
PY_VERSION = "3.12.10"                     # 必須與開發環境相同的次版本 (pip 依此下載二進位套件)
PY_TAG = "312"
EMBED_URL = f"https://www.python.org/ftp/python/{PY_VERSION}/python-{PY_VERSION}-embed-amd64.zip"
WINSW_URL = "https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe"
ISL_URL = "https://raw.githubusercontent.com/jrsoftware/issrc/is-6_7_1/Files/Languages/Unofficial/ChineseTraditional.isl"
ISCC_CANDIDATES = [
    os.environ.get("ISCC", ""),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe"),
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
]

SERVICE_XML = """<service>
  <id>XRayVision</id>
  <name>X-RayVision Inspection Service</name>
  <description>X-ray semiconductor inspection image analysis platform. Hosts the analysis service and performs software updates and rollbacks.</description>
  <executable>%BASE%\\..\\launcher\\python\\python.exe</executable>
  <arguments>-X utf8 "%BASE%\\..\\launcher\\launcher.py" run</arguments>
  <env name="XRAYVISION_HOME" value="%BASE%\\.." />
  <startmode>Automatic</startmode>
  <delayedAutoStart>true</delayedAutoStart>
  <stoptimeout>90 sec</stoptimeout>
  <onfailure action="restart" delay="10 sec" />
  <onfailure action="restart" delay="30 sec" />
  <onfailure action="restart" delay="60 sec" />
  <resetfailure>1 hour</resetfailure>
  <logpath>%ProgramData%\\X-RayVision\\logs</logpath>
  <log mode="roll-by-size">
    <sizeThreshold>5120</sizeThreshold>
    <keepFiles>5</keepFiles>
  </log>
</service>
"""


def step(msg):
    print(f"[build] {msg}", flush=True)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def fetch(url, cache):
    os.makedirs(cache, exist_ok=True)
    dst = os.path.join(cache, url.rsplit("/", 1)[1])
    if not os.path.isfile(dst):
        step(f"download {url}")
        tmp = dst + ".part"
        with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f)
        os.replace(tmp, dst)
    return dst


def make_python(embed_zip, dst, extra_paths=()):
    """展開 embeddable Python；._pth 決定完整 sys.path (此模式下 PYTHONPATH 無效)"""
    with zipfile.ZipFile(embed_zip) as z:
        z.extractall(dst)
    pth = glob.glob(os.path.join(dst, "python*._pth"))[0]
    lines = [f"python{PY_TAG}.zip", ".", "Lib\\site-packages", *extra_paths, "import site"]
    with open(pth, "w", encoding="ascii") as f:
        f.write("\n".join(lines) + "\n")
    os.makedirs(os.path.join(dst, "Lib", "site-packages"), exist_ok=True)


def install_deps(site):
    req = os.path.join(ROOT, "tools", "release", "runtime-requirements.txt")
    step("install runtime dependencies")
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                    "--target", site, "--platform", "win_amd64", "--python-version", PY_TAG,
                    "--implementation", "cp", "--only-binary=:all:", "--no-deps", "-r", req], check=True)
    shutil.rmtree(os.path.join(site, "bin"), ignore_errors=True)


def build_web(skip):
    web = os.path.join(ROOT, "web")
    if not skip:
        step("build web frontend")
        npm = shutil.which("npm.cmd") or shutil.which("npm") or "npm"
        subprocess.run([npm, "run", "build"], cwd=web, check=True)
    dist = os.path.join(web, "dist")
    if not os.path.isfile(os.path.join(dist, "index.html")):
        raise SystemExit("web/dist 不存在，請先建置前端")
    return dist


def clean_pycache(root):
    for base, dirs, _ in os.walk(root):
        for d in list(dirs):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(base, d), ignore_errors=True)
                dirs.remove(d)


def stage_tree(stage, version, cache, web_dist, notes):
    if os.path.isdir(stage):
        shutil.rmtree(stage)
    embed = fetch(EMBED_URL, cache)
    vdir = os.path.join(stage, "versions", version)
    # 產品版本：程式與前端
    step("stage app")
    app = os.path.join(vdir, "app")
    shutil.copytree(os.path.join(ROOT, "xrayvision"), os.path.join(app, "xrayvision"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
    shutil.copytree(web_dist, os.path.join(app, "web", "dist"))
    # 產品執行環境
    step("stage product runtime")
    py = os.path.join(vdir, "python")
    make_python(embed, py, extra_paths=("..\\app",))
    install_deps(os.path.join(py, "Lib", "site-packages"))
    with open(os.path.join(vdir, "version.json"), "w", encoding="utf-8") as f:
        json.dump(dict(version=version, released_at=time.strftime("%Y-%m-%dT%H:%M:%S"), notes=notes,
                       installed_by="setup"), f, ensure_ascii=False, indent=1)
    # 啟動器與其執行環境
    step("stage launcher")
    ldir = os.path.join(stage, "launcher")
    make_python(embed, os.path.join(ldir, "python"))
    shutil.copy2(os.path.join(ROOT, "launcher", "launcher.py"), ldir)
    # Windows 服務包裝
    step("stage service wrapper")
    sdir = os.path.join(stage, "service")
    os.makedirs(sdir)
    shutil.copy2(fetch(WINSW_URL, cache), os.path.join(sdir, SERVICE_EXE + ".exe"))
    with open(os.path.join(sdir, SERVICE_EXE + ".xml"), "w", encoding="utf-8") as f:
        f.write(SERVICE_XML)
    with open(os.path.join(stage, "current.json"), "w", encoding="utf-8") as f:
        json.dump(dict(version=version, switched_at=time.strftime("%Y-%m-%dT%H:%M:%S")), f, indent=1)


def smoke_test(stage, version, port=8699):
    """以 stage 內的啟動器實際啟動服務 (不設定 PYTHONPATH)，確認版本與內建標準影像自我檢查"""
    step("smoke test")
    data = tempfile.mkdtemp(prefix="xrv_smoke_")
    cfg = os.path.join(stage, "launcher", "launcher.json")
    with open(cfg, "w", encoding="utf-8") as f:
        json.dump(dict(data_dir=data, port=port), f)
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV")}
    env["XRAYVISION_HOME"] = stage
    proc = subprocess.Popen([os.path.join(stage, "launcher", "python", "python.exe"), "-X", "utf8",
                             os.path.join(stage, "launcher", "launcher.py"), "run"],
                            env=env, creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    result, last = None, ""
    try:
        deadline = time.time() + 300
        while time.time() < deadline and proc.poll() is None:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health?selftest=1", timeout=120) as r:
                    result = json.loads(r.read().decode("utf-8"))
                break
            except Exception as e:                                    # noqa: BLE001  服務尚未就緒
                last = repr(e)
                time.sleep(2)
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.CTRL_BREAK_EVENT)
            try:
                proc.wait(90)
            except subprocess.TimeoutExpired:
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        os.remove(cfg)
        clean_pycache(stage)
        shutil.rmtree(data, ignore_errors=True)
    if not result:
        raise SystemExit(f"smoke test failed: no response ({last})")
    if result.get("version") != version or result.get("selftest") != "pass":
        raise SystemExit(f"smoke test failed: {result}")
    step(f"smoke test passed: version {result['version']}, selftest {result['selftest']}")
    return result


def build_installer(stage, version, out_dir, cache, sign):
    iscc = next((p for p in ISCC_CANDIDATES if p and os.path.isfile(p)), None)
    if not iscc:
        step("Inno Setup not found; installer skipped")
        return None
    try:
        fetch(ISL_URL, cache)
    except OSError as e:
        step(f"Traditional Chinese installer messages unavailable ({e}); English only")
    args = [iscc, "/Q", f"/DAppVersion={version}", f"/DStageDir={stage}", f"/DOutputDir={out_dir}",
            f"/DLangDir={cache}"]
    if sign:
        args += [f"/Sxrvsign={sign}", "/DSign"]
    args.append(os.path.join(ROOT, "installer", "xrayvision.iss"))
    step("compile installer")
    subprocess.run(args, check=True)
    return os.path.join(out_dir, f"{PRODUCT}-{version}-setup.exe")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "build", "release"))
    ap.add_argument("--cache", default=os.path.join(ROOT, "build", "cache"))
    ap.add_argument("--skip-web", action="store_true")
    ap.add_argument("--no-smoke", action="store_true")
    ap.add_argument("--no-installer", action="store_true")
    ap.add_argument("--update-key", default=None, help="update signing private key; produces .xrvupd")
    ap.add_argument("--update-with-runtime", action="store_true", help="include python/ in the update package")
    ap.add_argument("--min-from", default=None)
    ap.add_argument("--notes-zh", default="")
    ap.add_argument("--notes-en", default="")
    ap.add_argument("--sign", default=None, help="signing command for Inno Setup, $f = file to sign")
    a = ap.parse_args()

    from xrayvision import __version__ as version
    notes = {"zh-TW": a.notes_zh, "en": a.notes_en}
    out_dir = os.path.join(a.out, version)
    stage = os.path.join(out_dir, "stage")
    os.makedirs(out_dir, exist_ok=True)
    step(f"{PRODUCT} {version} → {out_dir}")

    web_dist = build_web(a.skip_web)
    stage_tree(stage, version, a.cache, web_dist, notes)
    info = dict(product=PRODUCT, version=version, built_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                python=PY_VERSION, components={u: sha256(fetch(u, a.cache)) for u in (EMBED_URL, WINSW_URL)},
                outputs={})
    if not a.no_smoke:
        info["smoke_test"] = smoke_test(stage, version)
    if not a.no_installer:
        setup = build_installer(stage, version, out_dir, a.cache, a.sign)
        if setup:
            info["outputs"][os.path.basename(setup)] = sha256(setup)
    if a.update_key:
        from make_update import build_update
        upd = os.path.join(out_dir, f"{PRODUCT}-{version}.xrvupd")
        vdir = os.path.join(stage, "versions", version)
        step("build update package")
        build_update(os.path.join(vdir, "app"), version, upd, a.update_key,
                     os.path.join(vdir, "python") if a.update_with_runtime else None, a.min_from, notes)
        info["outputs"][os.path.basename(upd)] = sha256(upd)
    with open(os.path.join(out_dir, "build-info.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=1)
    for name, h in info["outputs"].items():
        step(f"{name}  sha256 {h}")
    step("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
