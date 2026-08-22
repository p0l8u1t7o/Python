# Step 3: move the binding from plan.site to site.storage_plan, name every
# existing plan after the site it served, then drop the site column.
from django.db import migrations, models


def forwards(apps, schema_editor):
    StoragePlan = apps.get_model("ems", "StoragePlan")
    Site = apps.get_model("devices", "Site")

    taken: dict = {}
    for plan in StoragePlan.objects.select_related("site").all():
        site = plan.site
        base = f"{site.name} 方案" if site else "儲能方案"
        name = base
        count = taken.get((plan.organization_id, base), 0)
        if count:
            name = f"{base} {count + 1}"
        taken[(plan.organization_id, base)] = count + 1
        plan.name = name
        plan.save(update_fields=["name"])
        if site is not None:
            Site.objects.filter(pk=site.pk).update(storage_plan=plan)


def backwards(apps, schema_editor):
    # The site column is gone forward of this point; nothing to restore.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("ems", "0007_plan_templates_step1"),
        ("devices", "0012_site_storage_plan"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
        migrations.RemoveField(model_name="storageplan", name="site"),
        migrations.AlterModelOptions(
            name="storageplan", options={"ordering": ["name"]}
        ),
        migrations.AddConstraint(
            model_name="storageplan",
            constraint=models.UniqueConstraint(
                fields=("organization", "name"), name="uniq_plan_org_name"
            ),
        ),
    ]
