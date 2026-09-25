"""開發用：資料目錄沒有有效授權時，以開發用私鑰簽發一份長期授權並匯入。

產品程式不變，授權流程照常運作；私鑰 tools/keys/license_private_DEV.pem 只在開發機，不隨產品出貨。
用法：python scripts/dev_license.py <資料目錄> [--days 3650] [--force]
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from cryptography.hazmat.primitives import serialization  # noqa: E402

from xrayvision.config import Settings  # noqa: E402
from xrayvision.service import license as lic  # noqa: E402
from xrayvision.store.db import Database  # noqa: E402

KEY = os.path.join(ROOT, "tools", "keys", "license_private_DEV.pem")
RENEW_DAYS = 30          # 剩餘天數低於此值就重新簽發


def main():
    ap = argparse.ArgumentParser(description="issue and import a development license")
    ap.add_argument("data")
    ap.add_argument("--days", type=int, default=3650)
    ap.add_argument("--force", action="store_true", help="即使目前授權有效也重新簽發")
    a = ap.parse_args()

    settings = Settings.load(a.data)
    settings.ensure_dirs()
    db = Database(settings.db_path)
    mgr = lic.LicenseManager(settings.data_dir, db)
    st = mgr.status()
    if not a.force and st["analysis_allowed"] and st.get("days_left", 0) >= RENEW_DAYS:
        print(f"授權有效：{st.get('customer')}，到期 {st.get('expires')}")
        return 0
    if not os.path.isfile(KEY):
        print(f"找不到開發用私鑰 {KEY}，無法簽發開發授權；請改由網頁「系統管理 > 軟體授權」匯入授權檔。")
        return 1
    key = serialization.load_pem_private_key(open(KEY, "rb").read(), password=None)
    doc = lic.issue(mgr.request(), key, "Development", days=a.days, modules=("*",))
    try:
        st = mgr.import_license(doc, actor="dev-script")
    except lic.LicenseError as e:
        # 產品公鑰 (xrayvision/keys) 已換成正式金鑰時，開發私鑰簽的授權會驗證失敗
        print(f"開發授權匯入失敗 ({e.code})：產品公鑰與開發用私鑰不成對？")
        return 1
    print(f"已簽發並匯入開發授權：到期 {st.get('expires')}，機器碼 {st['machine_code']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
