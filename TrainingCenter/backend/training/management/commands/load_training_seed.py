"""匯入教育訓練教材（元件知識卡、來料辨識、測驗、課程、Mini Project）。

以 code / slug 為鍵 upsert，可重複執行。

用法：
  python manage.py load_training_seed
  python manage.py load_training_seed --relink   # 只重建知識卡與實機元件的關聯
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import Component, Equipment
from training.models import (
    Course,
    IdentificationGuide,
    KnowledgeCard,
    Lesson,
    Project,
    QuizQuestion,
)

SEED = Path(__file__).resolve().parents[2] / "seed"

# 知識卡 ←→ 實機元件的對照：catalog 的 Component.slug → 教材的知識卡 code。
# 同一個 slug 在多台設備都會出現，這裡一次連到全部，讓 3D 頁點元件就能帶出知識卡。
LINKS: dict[str, str] = {
    # 機構
    "belt-conveyor": "MEC-20", "cell-conveyor": "MEC-20", "belt-section": "MEC-20",
    "cable-chain": "MEC-23", "dress-pack": "MEC-23",
    "stopper-cyl": "MEC-21", "stopper": "MEC-21", "lift-cyl": "MEC-21",
    "lift-locate": "CNV-11", "reject-cyl": "MEC-10", "cross-belt": "CNV-01",
    "x-axis": "MEC-05", "y-axis": "MEC-05", "z-axis": "MEC-05",
    "guide-shaft": "MEC-04", "shock": "MEC-22",
    "fixture": "MEC-17", "vacuum-pad": "MEC-14", "pneumatic-gripper": "MEC-16",
    "roller-conveyor": "CNV-02", "branch-conveyor": "CNV-02",
    "side-guide": "CNV-09", "carrier": "CNV-12",
    # 氣路
    "frl": "MEC-13", "push-in-fitting": "PNE-16", "quick-coupler": "PNE-16",
    "air-tube": "PNE-17", "speed-controller": "MEC-12", "pressure-switch": "PNE-12",
    "cylinder-sensor": "MEC-11", "solenoid-manifold": "PNE-15", "valve-manifold": "PNE-15",
    "air-inlet": "PNE-05", "h2-purge-valve": "FCS-06",
    # 電控
    "plc": "ELE-07", "master-plc": "ELE-07", "safety-plc": "ELE-26", "safety-relay": "ELE-26",
    "servo-drive": "ELE-11", "servo-motor": "ELE-12", "joint-servo": "ELE-12",
    "vfd": "ELE-15", "psu": "ELE-06", "encoder": "ELE-13",
    "light-curtain": "ELE-28", "tower-light": "ELE-29", "estop": "ELE-25",
    "terminal-block": "ELE-31", "grounding": "ELE-33", "main-breaker": "ELE-02",
    "photo-sensor": "ELE-19", "photo-sensors": "ELE-19",
    "hmi": "ELE-30", "hmi-ui": "SFT-09", "vision-ipc": "ELE-34", "rfid": "ELE-35",
    "remote-io": "ELE-10", "laser-scanner": "ARM-24", "safety-fence": "ARM-24",
    "switch": "SFT-12", "gateway": "SFT-14",
    # 軟體
    "plc-program": "SFT-01", "cell-plc-program": "SFT-01",
    "recipe-db": "SFT-07", "mes-link": "SFT-15", "digital-twin": "SFT-21",
    "routing": "SFT-02", "fleet": "SFT-15", "scada": "SFT-10", "bms-firmware": "FCS-15",
    # 機械手臂
    "base": "ARM-01", "j1": "ARM-01", "j2": "ARM-10", "j3": "ARM-10", "j4-j6": "ARM-11",
    "reducer": "ARM-08", "brake": "ARM-07", "flange": "ARM-11",
    "robot-controller": "ARM-05", "teach-pendant": "ARM-06", "robot-program": "ARM-26",
    "tool-changer": "ARM-13", "force-sensor": "ARM-15", "screwdriver": "ARM-12",
    "hand-eye-calib": "ARM-16", "vision-guidance": "ARM-16", "rotary-union": "ARM-14",
    # AOI／視覺
    "camera": "AOI-01", "fixed-camera": "AOI-01", "hand-camera": "AOI-01",
    "lens": "AOI-03", "ring-light": "AOI-04", "lighting": "AOI-04",
    "light-controller": "AOI-05", "calib-board": "AOI-10", "vision-sw": "AOI-11",
    "3d-camera": "AOI-02", "bin-picking": "AOI-12",
    # 氫燃料電池
    "pem-stack": "FCS-01", "h2-buffer-tank": "FCS-02", "h2-regulator": "FCS-03",
    "h2-solenoid": "FCS-04", "h2-detector": "FCS-07", "air-blower": "FCS-09",
    "humidifier": "FCS-10", "coolant-pump": "FCS-11", "radiator": "FCS-11",
    "temp-rtd": "FCS-12", "pressure-tx": "FCS-12", "dcdc": "FCS-13",
    "inverter": "FCS-14", "battery": "FCS-15", "cvm": "FCS-18",
}


def load(name: str):
    return json.loads((SEED / f"{name}.json").read_text(encoding="utf-8"))


class Command(BaseCommand):
    help = "匯入教育訓練教材 seed"

    def add_arguments(self, parser):
        parser.add_argument("--relink", action="store_true", help="只重建知識卡與元件的關聯")

    @transaction.atomic
    def handle(self, *args, **opts):
        if opts["relink"]:
            self.link_components()
            return

        cards = self.load_cards()
        self.load_identification(cards)
        self.load_quiz()
        self.load_courses(cards)
        self.load_projects()
        self.link_components()

    # ------------------------------------------------------------------
    def load_cards(self) -> dict[str, KnowledgeCard]:
        out = {}
        for row in load("knowledge_cards"):
            card, _ = KnowledgeCard.objects.update_or_create(
                code=row["code"], defaults={k: v for k, v in row.items() if k != "code"}
            )
            out[card.code] = card
        self.stdout.write(f"知識卡  {len(out)}")
        return out

    def load_identification(self, cards):
        for row in load("identification"):
            cands = row.pop("candidates", [])
            guide, _ = IdentificationGuide.objects.update_or_create(
                order=row["order"], defaults={k: v for k, v in row.items() if k != "order"}
            )
            guide.candidates.set([cards[c] for c in cands if c in cards])
        self.stdout.write(f"來料辨識 {IdentificationGuide.objects.count()}")

    def load_quiz(self):
        for row in load("quiz"):
            QuizQuestion.objects.update_or_create(
                order=row["order"], course=None,
                defaults={k: v for k, v in row.items() if k != "order"},
            )
        self.stdout.write(f"測驗題  {QuizQuestion.objects.count()}")

    def load_courses(self, cards):
        by_cat: dict[str, list] = {}
        for c in cards.values():
            by_cat.setdefault(c.category, []).append(c)
        n_lessons = 0
        for row in load("courses"):
            lessons = row.pop("lessons")
            course, _ = Course.objects.update_or_create(
                slug=row["slug"], defaults={k: v for k, v in row.items() if k != "slug"}
            )
            for lr in lessons:
                eq_slug = lr.pop("equipment", "")
                lesson, _ = Lesson.objects.update_or_create(
                    course=course,
                    slug=lr["slug"],
                    defaults={k: v for k, v in lr.items() if k != "slug"}
                    | {"equipment": Equipment.objects.filter(slug=eq_slug).first()},
                )
                lesson.cards.set(by_cat.get(lesson.card_category, []))
                n_lessons += 1
        self.stdout.write(f"課程    {Course.objects.count()}（章節 {n_lessons}）")

    def load_projects(self):
        for row in load("projects"):
            course_slug = row.pop("course", "")
            Project.objects.update_or_create(
                slug=row["slug"],
                defaults={k: v for k, v in row.items() if k != "slug"}
                | {"course": Course.objects.filter(slug=course_slug).first()},
            )
        self.stdout.write(f"專案    {Project.objects.count()}")

    def link_components(self):
        """把知識卡連到 catalog 裡的實機元件。同 slug 的元件（跨設備）一次全連。"""
        cards = {c.code: c for c in KnowledgeCard.objects.all()}
        linked = missing = 0
        for card in cards.values():
            card.components.clear()
        for slug, code in LINKS.items():
            card = cards.get(code)
            comps = list(Component.objects.filter(slug=slug))
            if not card or not comps:
                missing += 1
                continue
            card.components.add(*comps)
            linked += len(comps)
        covered = Component.objects.filter(knowledge_cards__isnull=False).distinct().count()
        total = Component.objects.count()
        self.stdout.write(
            f"元件關聯 {linked} 筆；{covered}/{total} 個元件已對到知識卡"
            + (f"（{missing} 條對照找不到目標）" if missing else "")
        )
