"""回歸比對本身要能抓到差異"""
import copy

from . import regress

BASE = {"image/x.tiff": dict(kind="raw16", reference_only=False, status="ok", sites_measured=100, sites_used=90,
                             die_shift=dict(dx=0.5, dy=-0.2, se=0.1, n=90, n_in=85),
                             groups=[dict(id=1, size=90, est=dict(dx=0.5, dy=-0.2, se=0.1, n=90, n_in=85))])}


def test_identical_has_no_diff():
    assert regress.compare(BASE, copy.deepcopy(BASE)) == []


def test_detects_shift_count_and_missing():
    cur = copy.deepcopy(BASE)
    cur["image/x.tiff"]["die_shift"]["dx"] += 0.01
    cur["image/x.tiff"]["sites_used"] = 89
    d = regress.compare(BASE, cur)
    assert any("sites_used" in x for x in d) and any("image (" in x for x in d)
    assert regress.compare(BASE, {}) == ["image/x.tiff: missing"]
