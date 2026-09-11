"""既有標定資產補上結構化摘要 `meta.summary_parts`（PM-REVIEW-R2 L-4：標定頁依介面語言組句子）。

只讀資產檔算一次，讀不到的（檔案已不在）跳過；沒有 schema 變更。
"""

from django.db import migrations


def backfill(apps, schema_editor):
    Asset = apps.get_model("vision", "Asset")
    from apps.vision import calib

    for asset in Asset.objects.filter(kind="calibration"):
        meta = dict(asset.meta or {})
        if "summary_parts" in meta:
            continue
        try:
            meta["summary_parts"] = calib.summary_parts(calib.load(asset.path))
        except Exception:  # noqa: BLE001 — 檔案不在或壞掉：留給頁面退回英文摘要
            continue
        asset.meta = meta
        asset.save(update_fields=["meta"])


class Migration(migrations.Migration):
    dependencies = [("vision", "0041_composite_tool_versions")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
