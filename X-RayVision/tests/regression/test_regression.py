"""回歸影像集比對 (Batch1、Batch2)；影像不存在時略過"""
import json
import os

import pytest

from . import regress

pytestmark = pytest.mark.regression


@pytest.mark.skipif(not regress.available_images(), reason="regression images not available")
def test_regression_matches_baseline():
    base = json.load(open(regress.BASELINE, encoding="utf-8"))
    files = [os.path.join(regress.ROOT, k) for k in base if os.path.exists(os.path.join(regress.ROOT, k))]
    assert files, "no baseline images found"
    cur = regress.run_all(files)
    diffs = regress.compare({k: v for k, v in base.items() if k in cur}, cur)
    assert not diffs, "\n".join(diffs)
