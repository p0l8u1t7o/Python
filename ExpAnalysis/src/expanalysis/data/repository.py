"""批次資料存取。所有 SQL 集中在這裡，上層只看得到 dataclass。"""

from __future__ import annotations

import time

from ..logging_setup import get_logger
from .db import Database
from .models import Batch, BatchDetail, ElementSpec, Measurement

log = get_logger(__name__)


def _now_ms() -> int:
    return int(time.time() * 1000)


class BatchRepository:
    def __init__(self, db: Database):
        self.db = db

    # ── 寫入 ────────────────────────────────────────────────────
    def upsert_batch(self, b: Batch) -> None:
        self.db.execute(
            """
            INSERT INTO batch (batch_id, run_date, ingot_len_mm, zone_len_mm,
                               speed_mm_hr, temp_c, n_passes, atmosphere,
                               head_crop_frac, feed_purity_note, analysis_method,
                               operator, notes, created_ms)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(batch_id) DO UPDATE SET
                run_date=excluded.run_date,
                ingot_len_mm=excluded.ingot_len_mm,
                zone_len_mm=excluded.zone_len_mm,
                speed_mm_hr=excluded.speed_mm_hr,
                temp_c=excluded.temp_c,
                n_passes=excluded.n_passes,
                atmosphere=excluded.atmosphere,
                head_crop_frac=excluded.head_crop_frac,
                feed_purity_note=excluded.feed_purity_note,
                analysis_method=excluded.analysis_method,
                operator=excluded.operator,
                notes=excluded.notes
            """,
            (b.batch_id, b.run_date, b.ingot_len_mm, b.zone_len_mm, b.speed_mm_hr,
             b.temp_c, b.n_passes, b.atmosphere, b.head_crop_frac,
             b.feed_purity_note, b.analysis_method, b.operator, b.notes, _now_ms()),
        )
        self.db.conn.commit()

    def replace_measurements(self, batch_id: str, rows: list[Measurement]) -> None:
        """整批取代某批次的量測值。匯入同一批次時語意最清楚，不會殘留舊點。"""
        with self.db.conn:
            self.db.conn.execute("DELETE FROM measurement WHERE batch_id=?", (batch_id,))
            self.db.conn.executemany(
                """INSERT INTO measurement
                   (batch_id, element, x_norm, value_ppm, lod_ppm, censored,
                    pass_index, sample_id)
                   VALUES (?,?,?,?,?,?,?,?)""",
                [(m.batch_id, m.element, m.x_norm, m.value_ppm, m.lod_ppm,
                  int(m.censored), m.pass_index, m.sample_id) for m in rows],
            )

    def replace_element_specs(self, batch_id: str, specs: list[ElementSpec]) -> None:
        with self.db.conn:
            self.db.conn.execute("DELETE FROM element_spec WHERE batch_id=?", (batch_id,))
            self.db.conn.executemany(
                """INSERT INTO element_spec (batch_id, element, c0_ppm, spec_ppm, c0_measured)
                   VALUES (?,?,?,?,?)""",
                [(s.batch_id, s.element, s.c0_ppm, s.spec_ppm, int(s.c0_measured))
                 for s in specs],
            )

    def delete_batch(self, batch_id: str) -> bool:
        with self.db.conn:
            cur = self.db.conn.execute("DELETE FROM batch WHERE batch_id=?", (batch_id,))
        return cur.rowcount > 0

    def clear_all(self) -> None:
        with self.db.conn:
            for tbl in ("measurement", "element_spec", "batch"):
                self.db.conn.execute(f"DELETE FROM {tbl}")

    # ── 讀取 ────────────────────────────────────────────────────
    def list_batches(self) -> list[Batch]:
        rows = self.db.query("SELECT * FROM batch ORDER BY run_date, batch_id")
        return [self._row_to_batch(r) for r in rows]

    def get_batch(self, batch_id: str) -> Batch | None:
        row = self.db.query_one("SELECT * FROM batch WHERE batch_id=?", (batch_id,))
        return self._row_to_batch(row) if row else None

    def get_detail(self, batch_id: str) -> BatchDetail | None:
        batch = self.get_batch(batch_id)
        if batch is None:
            return None
        meas = [
            Measurement(
                batch_id=r["batch_id"], element=r["element"], x_norm=r["x_norm"],
                value_ppm=r["value_ppm"], lod_ppm=r["lod_ppm"],
                censored=bool(r["censored"]), pass_index=r["pass_index"],
                sample_id=r["sample_id"],
            )
            for r in self.db.query(
                "SELECT * FROM measurement WHERE batch_id=? ORDER BY element, x_norm",
                (batch_id,),
            )
        ]
        specs = [
            ElementSpec(batch_id=r["batch_id"], element=r["element"],
                        c0_ppm=r["c0_ppm"], spec_ppm=r["spec_ppm"],
                        c0_measured=bool(r["c0_measured"]))
            for r in self.db.query(
                "SELECT * FROM element_spec WHERE batch_id=? ORDER BY element", (batch_id,)
            )
        ]
        return BatchDetail(batch=batch, measurements=meas, element_specs=specs)

    def all_details(self) -> list[BatchDetail]:
        return [d for d in (self.get_detail(b.batch_id) for b in self.list_batches())
                if d is not None]

    def elements(self) -> list[str]:
        rows = self.db.query("SELECT DISTINCT element FROM measurement ORDER BY element")
        return [r["element"] for r in rows]

    def count(self) -> int:
        row = self.db.query_one("SELECT COUNT(*) AS n FROM batch")
        return int(row["n"]) if row else 0

    # ── 內部 ────────────────────────────────────────────────────
    @staticmethod
    def _row_to_batch(r) -> Batch:
        return Batch(
            batch_id=r["batch_id"], run_date=r["run_date"],
            ingot_len_mm=r["ingot_len_mm"], zone_len_mm=r["zone_len_mm"],
            speed_mm_hr=r["speed_mm_hr"], temp_c=r["temp_c"],
            n_passes=r["n_passes"], atmosphere=r["atmosphere"],
            head_crop_frac=r["head_crop_frac"], feed_purity_note=r["feed_purity_note"],
            analysis_method=r["analysis_method"], operator=r["operator"], notes=r["notes"],
        )
