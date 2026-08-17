"""名片管理伺服器。

功能對應：
    1. Flask 開發伺服器監聽 0.0.0.0，同網域內手機瀏覽器可直接開啟；
       前端頁面 (templates/index.html) 為單頁下拉式響應式設計，自動適應
       手機/平板/桌機寬度，不需要左右切換頁籤。
    2. 手機瀏覽器用 <input type="file" capture="environment"> 叫出相機拍照，
       拍完立即呼叫 /api/ocr 做名片文字辨識並預先帶入表單欄位；辨識前會先把名片
       從整張照片裡裁切拉正再辨識（見 cardimage.py），辨識不到或辨識引擎未安裝時
       欄位維持空白，交由使用者手動輸入（見 ocr.py）。
       確認無誤後以 multipart/form-data 上傳到 /api/cards，存檔後寫入 SQLite。
       每筆資料存檔時一併寫入建立時間（本機時區），列表與詳情頁都會顯示。
    3. SQLite 資料庫檔案位置可由命令列參數 --db 或環境變數 CARD_DB_PATH 指定。
    4. 名片 (cards) 與需求 (requirements) 兩張表以外鍵關聯，一張名片可對應
       多筆需求紀錄（例如多次追蹤紀錄）。
    5. 提供查詢 API 與對應頁面，可用姓名/公司/電話/需求內容關鍵字搜尋，
       並列出、點開檢視名片影像與需求歷程；查詢到的名片也能直接補上/
       修正公司、姓名等欄位 (PUT /api/cards/<id>)。列表 API 一併回傳目前
       已儲存的總筆數與符合搜尋條件的筆數，供頁面顯示統計。
    6. 可將目前清單（可套用搜尋條件）匯出成 CSV (/api/export)，供 Excel 開啟。

啟動方式：
    python app.py --db D:/data/cards.db --uploads D:/data/uploads --port 8001
"""

import argparse
import csv
import io
import os
import sqlite3
import uuid
from datetime import datetime, timezone

from flask import Flask, Response, g, jsonify, request, send_from_directory, render_template
from PIL import Image, ImageOps, UnidentifiedImageError

import cardimage
import ocr

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 允許的圖片格式：副檔名與實際圖片格式都會檢查，避免有人把可執行檔
# 偽裝成 .jpg 上傳（只看副檔名或 Content-Type 都不可靠，必須真的用
# Pillow 開檔驗證是不是圖片）。
ALLOWED_IMAGE_FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 單張名片照片上限 15MB，避免手機原圖拖垮伺服器

# 列表分頁：預設只給最新的一頁，其餘由使用者按「載入更多」再取。
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
# 列表縮圖的長邊像素。手機原圖動輒 3MB，一次列 20 筆就要下載數十 MB，
# 縮圖後單張只有幾十 KB，這是列表順不順的關鍵。
THUMBNAIL_MAX_SIDE = 320


def _clamp_int(raw, default, low, high):
    """把查詢字串參數轉成限定範圍內的整數；格式錯誤就用預設值。"""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


def create_app(db_path, upload_dir):
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path
    app.config["UPLOAD_DIR"] = upload_dir
    # 縮圖放在照片資料夾底下的子目錄，跟著照片一起備份/搬移，刪掉也能自動重建。
    app.config["THUMB_DIR"] = os.path.join(upload_dir, "thumbs")
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES

    os.makedirs(upload_dir, exist_ok=True)
    os.makedirs(app.config["THUMB_DIR"], exist_ok=True)

    # 在這裡（而非只在 __main__）設定 OCR 引擎路徑，讓透過 waitress 等 WSGI 伺服器
    # 直接載入 create_app 的部署方式也能正常自動辨識。
    ocr.configure()

    # ---------------------------------------------------- 資料庫連線
    def get_db():
        """每個 request 共用一條連線（存在 flask.g），request 結束自動關閉。"""
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DB_PATH"])
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON")
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    def init_db():
        """啟動時建表（若不存在）。cards / requirements 為一對多關聯，
        requirements.card_id 設 ON DELETE CASCADE，刪除名片時自動清掉底下需求。"""
        conn = sqlite3.connect(app.config["DB_PATH"])
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS cards (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL DEFAULT '',
                company     TEXT NOT NULL DEFAULT '',
                title       TEXT NOT NULL DEFAULT '',
                phone       TEXT NOT NULL DEFAULT '',
                email       TEXT NOT NULL DEFAULT '',
                address     TEXT NOT NULL DEFAULT '',
                note        TEXT NOT NULL DEFAULT '',
                image_file  TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                rotation    INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS requirements (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id     INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
                content     TEXT NOT NULL,
                created_at  TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_requirements_card_id
                ON requirements(card_id);
            """
        )

        # 舊資料庫沒有 rotation 欄位，補上（CREATE TABLE IF NOT EXISTS 不會改既有資料表）。
        columns = {row[1] for row in conn.execute("PRAGMA table_info(cards)")}
        if "rotation" not in columns:
            conn.execute("ALTER TABLE cards ADD COLUMN rotation INTEGER NOT NULL DEFAULT 0")

        conn.commit()
        conn.close()

    init_db()

    # ---------------------------------------------------- 工具
    def now_iso():
        """建立資料的時間戳，取本機時間並附上時區位移（例如 2026-08-17T14:05:30+08:00）。

        帶時區的格式讓前端 new Date() 能正確還原成使用者當地時間顯示，
        也保留了「這筆資料是幾點建立的」這個對使用者有意義的資訊；
        舊資料以 UTC (+00:00) 寫入，同樣能被正確解析，不需要轉檔。
        """
        return datetime.now().astimezone().isoformat(timespec="seconds")

    def open_and_validate_image(raw):
        """把上傳的原始位元組解碼成可用的 PIL 圖片。

        用 Pillow 實際解碼一次，確認內容真的是圖片而非偽裝的其他檔案；
        同時依 EXIF Orientation 自動轉正（手機直拍常見的橫躺問題）並丟棄
        其餘 EXIF（如 GPS 座標等隱私資訊）。存檔 (save_image) 與辨識
        (/api/ocr) 都需要先做這一步，因此拆成共用函式。
        """
        try:
            img = Image.open(io.BytesIO(raw))
            img.verify()  # 檢查檔案結構是否完整、是否真的是圖片
            img = Image.open(io.BytesIO(raw))  # verify() 後需重新開啟才能再讀取像素
        except (UnidentifiedImageError, OSError):
            raise ValueError("上傳的檔案不是有效的圖片")

        if img.format not in ALLOWED_IMAGE_FORMATS:
            raise ValueError(f"不支援的圖片格式：{img.format}")

        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        return img

    def save_image(file_storage):
        """驗證並存檔上傳的圖片，回傳存檔後的檔名（不含路徑）。

        檔名以 uuid4 產生，不使用使用者提供的檔名，杜絕路徑穿越風險；
        統一轉存成 JPEG，避免保留原始檔名/來源資訊或不可預期的格式。
        """
        img = open_and_validate_image(file_storage.read())
        filename = f"{uuid.uuid4().hex}.jpg"
        dest = os.path.join(app.config["UPLOAD_DIR"], filename)
        img.save(dest, format="JPEG", quality=88)
        return filename

    def card_to_dict(row):
        # 旋轉後檔名不變，瀏覽器會沿用快取裡的舊圖，因此把累計旋轉角度當版本號掛在
        # 網址後面；角度一變網址就變，圖片自然重新載入。
        version = row["rotation"] if "rotation" in row.keys() else 0
        return {
            "id": row["id"],
            "name": row["name"],
            "company": row["company"],
            "title": row["title"],
            "phone": row["phone"],
            "email": row["email"],
            "address": row["address"],
            "note": row["note"],
            "image_url": f"/uploads/{row['image_file']}?v={version}",
            # 列表只需要 66px 的小圖，改抓縮圖而不是動輒數 MB 的原圖
            "thumb_url": f"/thumbs/{row['image_file']}?v={version}",
            "rotation": version,
            "created_at": row["created_at"],
        }

    # ---------------------------------------------------- 頁面
    @app.get("/")
    def index():
        return render_template("index.html")

    # ---------------------------------------------------- API：新增名片（含拍照上傳）
    @app.post("/api/cards")
    def create_card():
        if "image" not in request.files or request.files["image"].filename == "":
            return jsonify(error="缺少名片照片"), 400

        try:
            image_file = save_image(request.files["image"])
        except ValueError as e:
            return jsonify(error=str(e)), 400

        form = request.form
        created_at = now_iso()
        db = get_db()
        cur = db.execute(
            """INSERT INTO cards
               (name, company, title, phone, email, address, note, image_file, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                form.get("name", "").strip(),
                form.get("company", "").strip(),
                form.get("title", "").strip(),
                form.get("phone", "").strip(),
                form.get("email", "").strip(),
                form.get("address", "").strip(),
                form.get("note", "").strip(),
                image_file,
                created_at,
            ),
        )
        card_id = cur.lastrowid

        # 建立當下若已填需求內容，一併存入 requirements，作為第一筆需求紀錄。
        requirement = form.get("requirement", "").strip()
        if requirement:
            db.execute(
                "INSERT INTO requirements (card_id, content, created_at) VALUES (?, ?, ?)",
                (card_id, requirement, created_at),
            )
        db.commit()
        # 回傳 created_at，讓前端存檔後能立刻顯示「建立時間」給使用者確認。
        return jsonify(id=card_id, image_url=f"/uploads/{image_file}",
                       created_at=created_at), 201

    def fetch_cards(db, q, limit=None, offset=0):
        """依關鍵字查詢名片（比對姓名/公司/職稱/電話/Email/備註/需求內容）。

        一律以 id 由大到小排序，也就是最新建立的排最前面。
        limit 為 None 時取全部（匯出 CSV 用）；列表頁則會帶 limit/offset 分頁，
        避免資料累積後一次回傳上千筆拖慢頁面。
        """
        where, params = "", []
        if q:
            like = f"%{q}%"
            where = """WHERE c.name LIKE ? OR c.company LIKE ? OR c.title LIKE ?
                          OR c.phone LIKE ? OR c.email LIKE ? OR c.note LIKE ?
                          OR r.content LIKE ?"""
            params = [like] * 7

        sql = f"""SELECT DISTINCT c.* FROM cards c
                  LEFT JOIN requirements r ON r.card_id = c.id
                  {where}
                  ORDER BY c.id DESC"""
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params += [limit, offset]
        return db.execute(sql, params).fetchall()

    def count_cards(db, q):
        """符合搜尋條件的名片總數（分頁時前端需要知道還有多少筆沒載入）。"""
        if not q:
            return db.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        like = f"%{q}%"
        return db.execute(
            """SELECT COUNT(DISTINCT c.id) FROM cards c
               LEFT JOIN requirements r ON r.card_id = c.id
               WHERE c.name LIKE ? OR c.company LIKE ? OR c.title LIKE ?
                  OR c.phone LIKE ? OR c.email LIKE ? OR c.note LIKE ?
                  OR r.content LIKE ?""",
            [like] * 7,
        ).fetchone()[0]

    # ---------------------------------------------------- API：查詢名片列表
    @app.get("/api/cards")
    def list_cards():
        """回傳名片清單（分頁）與筆數統計。

        預設只回傳最新的 DEFAULT_PAGE_SIZE 筆，前端再依需要按「載入更多」往下取，
        以免資料變多之後一次載入全部名片與縮圖造成畫面延遲。
        matched 是套用搜尋條件後的總筆數，total 是資料庫裡的總筆數；兩個都給，
        前端才能同時顯示「目前已儲存 N 筆」與「符合條件 M 筆」並判斷是否還有下一頁。
        """
        q = request.args.get("q", "").strip()
        limit = _clamp_int(request.args.get("limit"), DEFAULT_PAGE_SIZE, 1, MAX_PAGE_SIZE)
        offset = max(0, _clamp_int(request.args.get("offset"), 0, 0, 10 ** 9))

        db = get_db()
        rows = fetch_cards(db, q, limit=limit, offset=offset)
        matched = count_cards(db, q)
        total = matched if not q else db.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        return jsonify(
            cards=[card_to_dict(r) for r in rows],
            matched=matched,
            total=total,
            limit=limit,
            offset=offset,
            has_more=offset + len(rows) < matched,
        )

    # ---------------------------------------------------- API：單張名片詳情（含需求歷程）
    @app.get("/api/cards/<int:card_id>")
    def get_card(card_id):
        db = get_db()
        row = db.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        if row is None:
            return jsonify(error="找不到名片"), 404
        reqs = db.execute(
            "SELECT id, content, created_at FROM requirements WHERE card_id = ? ORDER BY id",
            (card_id,),
        ).fetchall()
        data = card_to_dict(row)
        data["requirements"] = [dict(r) for r in reqs]
        return jsonify(data)

    # ---------------------------------------------------- API：名片文字自動辨識
    @app.post("/api/ocr")
    def ocr_card():
        """拍照當下（尚未送出表單）呼叫，回傳猜測的欄位供前端預先帶入。

        辨識引擎未安裝或辨識失敗都回傳 200 + available=false，而不是
        400/500 錯誤，因為這是「錦上添花」的輔助功能：失敗時前端應該
        靜靜地讓使用者照常手動輸入，不該跳錯誤訊息打斷操作流程。
        """
        if "image" not in request.files or request.files["image"].filename == "":
            return jsonify(error="缺少圖片"), 400
        try:
            img = open_and_validate_image(request.files["image"].read())
        except ValueError as e:
            return jsonify(error=str(e)), 400

        fields, _raw_text, error = ocr.recognize(img)
        if error:
            return jsonify(available=False, error=error, fields={})
        # filled 讓前端能分辨「引擎沒跑起來」與「引擎跑了但這張沒讀到東西」，
        # 兩者要給使用者的提示不一樣（前者要裝 Tesseract，後者是重拍就好）。
        return jsonify(available=True, fields=fields,
                       filled=sum(1 for value in fields.values() if value))

    # ---------------------------------------------------- API：重新辨識既有名片
    @app.post("/api/cards/<int:card_id>/reocr")
    def reocr_card(card_id):
        """對已存檔的名片照片重跑一次辨識，回傳結果供使用者比對後決定要不要套用。

        刻意「不」直接寫回資料庫：使用者可能已經手動修正過欄位，辨識結果只是建議，
        由前端顯示出來讓使用者確認、必要時再按儲存，才不會把人工修正好的資料蓋掉。
        """
        db = get_db()
        row = db.execute("SELECT image_file FROM cards WHERE id = ?", (card_id,)).fetchone()
        if row is None:
            return jsonify(error="找不到名片"), 404

        source = os.path.join(app.config["UPLOAD_DIR"], os.path.basename(row["image_file"]))
        if not os.path.isfile(source):
            return jsonify(error="找不到名片照片檔案"), 404

        try:
            with open(source, "rb") as fh:
                img = open_and_validate_image(fh.read())
        except (ValueError, OSError) as e:
            return jsonify(error=f"無法讀取名片照片：{e}"), 400

        fields, _raw_text, error = ocr.recognize(img)
        if error:
            return jsonify(available=False, error=error, fields={})
        return jsonify(available=True, fields=fields,
                       filled=sum(1 for value in fields.values() if value))

    # ---------------------------------------------------- API：旋轉名片照片 90 度
    @app.post("/api/cards/<int:card_id>/rotate")
    def rotate_card(card_id):
        """把名片照片旋轉 90 度並存回檔案，同時把累計角度記進資料庫。

        direction = "cw"（順時針，預設）或 "ccw"（逆時針）。

        這裡是直接把 JPEG 轉正後覆寫回去，而不是只在資料庫記角度、由前端旋轉顯示：
        照片本身轉正後，列表縮圖、匯出、以及「重新辨識」全都自動吃到正確方向，
        不必每個使用影像的地方都記得套用角度。資料庫的 rotation 欄位記錄累計角度，
        同時兼作圖片網址的版本號，避免瀏覽器繼續顯示快取中的舊方向。
        """
        # 表單與 JSON 兩種送法都接受（get_json(silent=True) 在非 JSON 請求時回 None
        # 而不會拋例外）
        payload = request.get_json(silent=True) or {}
        direction = (request.form.get("direction") or payload.get("direction") or "cw").strip()
        if direction not in ("cw", "ccw"):
            return jsonify(error="direction 只能是 cw 或 ccw"), 400

        db = get_db()
        row = db.execute(
            "SELECT image_file, rotation FROM cards WHERE id = ?", (card_id,)
        ).fetchone()
        if row is None:
            return jsonify(error="找不到名片"), 404

        image_file = os.path.basename(row["image_file"])
        source = os.path.join(app.config["UPLOAD_DIR"], image_file)
        if not os.path.isfile(source):
            return jsonify(error="找不到名片照片檔案"), 404

        # PIL 的 rotate 是逆時針，所以順時針要轉 -90（等同 270）
        angle = -90 if direction == "cw" else 90
        try:
            with Image.open(source) as img:
                img = ImageOps.exif_transpose(img)
                if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")
                # 每轉一次就重新編碼一次 JPEG，會累積壓縮損失，因此這裡用比建檔
                # (quality=88) 更高的品質，讓使用者反覆轉幾次也看不出畫質變差。
                img.rotate(angle, expand=True).save(source, format="JPEG", quality=95)
        except (OSError, UnidentifiedImageError) as e:
            return jsonify(error=f"旋轉失敗：{e}"), 400

        # 縮圖是照著舊方向產生的，刪掉讓它下次存取時依新方向重建
        try:
            os.remove(os.path.join(app.config["THUMB_DIR"], image_file))
        except OSError:
            pass

        rotation = ((row["rotation"] or 0) + (90 if direction == "cw" else -90)) % 360
        db.execute("UPDATE cards SET rotation = ? WHERE id = ?", (rotation, card_id))
        db.commit()

        return jsonify(
            rotation=rotation,
            image_url=f"/uploads/{image_file}?v={rotation}",
            thumb_url=f"/thumbs/{image_file}?v={rotation}",
        )

    # ---------------------------------------------------- API：刪除名片
    @app.delete("/api/cards/<int:card_id>")
    def delete_card(card_id):
        """刪除名片、其需求紀錄，以及照片與快取縮圖。

        requirements 設了 ON DELETE CASCADE，會隨名片一起刪除。
        照片則要確認沒有其他名片共用同一個檔案才刪（正常情況每張名片都有自己的
        uuid 檔名，但資料若曾被複製過就可能共用，先檢查比較保險）。
        """
        db = get_db()
        row = db.execute("SELECT image_file FROM cards WHERE id = ?", (card_id,)).fetchone()
        if row is None:
            return jsonify(error="找不到名片"), 404

        image_file = os.path.basename(row["image_file"])
        db.execute("DELETE FROM cards WHERE id = ?", (card_id,))
        db.commit()

        still_used = db.execute(
            "SELECT 1 FROM cards WHERE image_file = ? LIMIT 1", (row["image_file"],)
        ).fetchone()
        removed = []
        if not still_used:
            for path in (os.path.join(app.config["UPLOAD_DIR"], image_file),
                         os.path.join(app.config["THUMB_DIR"], image_file)):
                try:
                    os.remove(path)
                    removed.append(os.path.basename(path))
                except FileNotFoundError:
                    pass
                except OSError:
                    # 檔案被佔用等情況：資料已刪掉是主要目的，殘留檔案不算失敗
                    pass
        return jsonify(deleted=card_id, removed_files=removed,
                       image_kept_shared=bool(still_used))

    # ---------------------------------------------------- API：修改既有名片欄位（不含照片）
    @app.put("/api/cards/<int:card_id>")
    def update_card(card_id):
        """查詢頁補填/修正公司、姓名等欄位用；不處理照片更換。"""
        db = get_db()
        if db.execute("SELECT 1 FROM cards WHERE id = ?", (card_id,)).fetchone() is None:
            return jsonify(error="找不到名片"), 404

        form = request.form
        db.execute(
            """UPDATE cards SET name=?, company=?, title=?, phone=?, email=?,
               address=?, note=? WHERE id=?""",
            (
                form.get("name", "").strip(),
                form.get("company", "").strip(),
                form.get("title", "").strip(),
                form.get("phone", "").strip(),
                form.get("email", "").strip(),
                form.get("address", "").strip(),
                form.get("note", "").strip(),
                card_id,
            ),
        )
        db.commit()
        row = db.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        return jsonify(card_to_dict(row))

    # ---------------------------------------------------- API：匯出 CSV
    @app.get("/api/export")
    def export_cards():
        """匯出名片清單成 CSV（可套用與列表相同的關鍵字篩選 ?q=）。

        每張名片的所有需求紀錄合併成一欄（用 " | " 分隔），避免匯出檔案
        因為一對多關聯而產生大量重複的名片列。開頭加 UTF-8 BOM，讓
        Excel 開啟時中文不會變亂碼。
        """
        q = request.args.get("q", "").strip()
        db = get_db()
        rows = fetch_cards(db, q)

        reqs_by_card = {}
        card_ids = [r["id"] for r in rows]
        if card_ids:
            placeholders = ",".join("?" * len(card_ids))
            for r in db.execute(
                f"""SELECT card_id, group_concat(content, ' | ') AS reqs
                    FROM requirements WHERE card_id IN ({placeholders})
                    GROUP BY card_id""",
                card_ids,
            ).fetchall():
                reqs_by_card[r["card_id"]] = r["reqs"] or ""

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["姓名", "公司", "職稱", "電話", "Email", "地址", "備註", "需求紀錄", "建立時間"])
        for r in rows:
            writer.writerow([
                r["name"], r["company"], r["title"], r["phone"], r["email"],
                r["address"], r["note"], reqs_by_card.get(r["id"], ""), r["created_at"],
            ])

        filename = f"cards_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.csv"
        return Response(
            "﻿" + buf.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # ---------------------------------------------------- API：為既有名片新增一筆需求
    @app.post("/api/cards/<int:card_id>/requirements")
    def add_requirement(card_id):
        content = (request.form.get("content") or (request.json or {}).get("content", "")).strip()
        if not content:
            return jsonify(error="需求內容不可為空"), 400
        db = get_db()
        if db.execute("SELECT 1 FROM cards WHERE id = ?", (card_id,)).fetchone() is None:
            return jsonify(error="找不到名片"), 404
        created_at = now_iso()
        db.execute(
            "INSERT INTO requirements (card_id, content, created_at) VALUES (?, ?, ?)",
            (card_id, content, created_at),
        )
        db.commit()
        return jsonify(created_at=created_at), 201

    # ---------------------------------------------------- 圖片存取
    @app.get("/uploads/<path:filename>")
    def uploaded_file(filename):
        # send_from_directory 會自行擋掉 ../ 之類的路徑穿越嘗試。
        return send_from_directory(app.config["UPLOAD_DIR"], filename)

    @app.get("/thumbs/<path:filename>")
    def thumbnail_file(filename):
        """列表用的縮圖，第一次存取時產生後快取到 thumbs 資料夾。

        名片原圖是手機直出的照片，一張常有 2~3MB；列表一次列 20 筆就要下載
        數十 MB，正是清單捲動卡頓的主因。縮到長邊 320px 後每張只剩幾十 KB。
        產生失敗（檔案損毀等）就退回原圖，不讓列表因此開天窗。
        """
        # 僅接受檔名本身，擋掉任何路徑穿越的嘗試（原圖檔名一律是 uuid4 + .jpg）。
        safe_name = os.path.basename(filename)
        source = os.path.join(app.config["UPLOAD_DIR"], safe_name)
        if not os.path.isfile(source):
            return jsonify(error="找不到圖片"), 404

        thumb_dir = app.config["THUMB_DIR"]
        thumb_path = os.path.join(thumb_dir, safe_name)
        # 原圖被覆蓋時（mtime 變新）重新產生，避免一直用到舊縮圖
        if (not os.path.isfile(thumb_path)
                or os.path.getmtime(thumb_path) < os.path.getmtime(source)):
            try:
                with Image.open(source) as img:
                    img = ImageOps.exif_transpose(img)
                    if img.mode not in ("RGB", "L"):
                        img = img.convert("RGB")
                    img.thumbnail((THUMBNAIL_MAX_SIDE, THUMBNAIL_MAX_SIDE), Image.LANCZOS)
                    os.makedirs(thumb_dir, exist_ok=True)
                    img.save(thumb_path, format="JPEG", quality=80)
            except (OSError, UnidentifiedImageError):
                return send_from_directory(app.config["UPLOAD_DIR"], safe_name)

        return send_from_directory(thumb_dir, safe_name)

    return app


def parse_args():
    parser = argparse.ArgumentParser(description="名片管理伺服器")
    parser.add_argument(
        "--db",
        default=os.environ.get("CARD_DB_PATH", os.path.join(BASE_DIR, "cards.db")),
        help="SQLite 資料庫檔案位置（預設可用環境變數 CARD_DB_PATH 指定）",
    )
    parser.add_argument(
        "--uploads",
        default=os.environ.get("CARD_UPLOAD_DIR", os.path.join(BASE_DIR, "uploads")),
        help="名片照片存放資料夾",
    )
    parser.add_argument("--host", default="0.0.0.0", help="監聽位址，預設 0.0.0.0 供區網內手機連線")
    # 預設改用 8001，避開 8000（常被其他本機服務、Django/其他 Flask 專案佔用）。
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument(
        "--tesseract-cmd",
        default=os.environ.get("TESSERACT_CMD"),
        help="tesseract.exe 完整路徑（名片辨識用）；未指定則嘗試從系統 PATH 尋找",
    )
    parser.add_argument("--debug", action="store_true", help="開發模式（自動重載、顯示除錯訊息）")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    resolved = ocr.configure(args.tesseract_cmd)
    application = create_app(os.path.abspath(args.db), os.path.abspath(args.uploads))
    print(f"資料庫位置: {os.path.abspath(args.db)}")
    print(f"照片資料夾: {os.path.abspath(args.uploads)}")
    # 自動辨識失效時最常見的原因就是找不到 Tesseract，啟動時直接把狀態印出來，
    # 使用者才不用等到拍完照才發現沒辨識到、也不知道要查哪裡。
    ready, message = ocr.engine_status()
    print(f"名片辨識: {'可用' if ready else '停用'} - {message}")
    if resolved:
        print(f"Tesseract 路徑: {resolved}")
    if not cardimage.available():
        print("提示: 未安裝 opencv-python，將略過名片自動裁切校正，辨識率會明顯下降")
    print(f"手機請於同網域內開啟: http://<本機區網 IP>:{args.port}/")
    application.run(host=args.host, port=args.port, debug=args.debug, threaded=True)
