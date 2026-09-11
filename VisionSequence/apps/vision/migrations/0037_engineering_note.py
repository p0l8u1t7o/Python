# 工程筆記資料表，接續對話工作進度 migration。

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vision', '0036_assistant_chat_work_state'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='EngineeringNote',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('project', models.CharField(blank=True, default='', max_length=200)),
                ('part_number', models.CharField(blank=True, db_index=True, default='', max_length=120)),
                ('kind', models.CharField(choices=[('decision', 'decision'), ('lesson', 'lesson'), ('constraint', 'constraint'), ('lighting', 'lighting'), ('calibration', 'calibration'), ('tolerance_rationale', 'tolerance_rationale'), ('known_issue', 'known_issue')], default='decision', max_length=24)),
                ('title', models.CharField(max_length=200)),
                ('body', models.TextField()),
                ('conditions', models.JSONField(blank=True, default=dict)),
                ('applies_from_version', models.PositiveIntegerField(blank=True, null=True)),
                ('applies_to_version', models.PositiveIntegerField(blank=True, null=True)),
                ('status', models.CharField(choices=[('draft', 'draft'), ('confirmed', 'confirmed'), ('superseded', 'superseded'), ('retracted', 'retracted')], db_index=True, default='draft', max_length=16)),
                ('confirmed_at', models.DateTimeField(blank=True, null=True)),
                ('images', models.JSONField(blank=True, default=list)),
                ('runs', models.JSONField(blank=True, default=list)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('confirmed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='confirmed_engineering_notes', to=settings.AUTH_USER_MODEL)),
                ('flow', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='engineering_notes', to='vision.flow')),
                ('owner', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='engineering_notes', to=settings.AUTH_USER_MODEL)),
                ('recipe', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='engineering_notes', to='vision.flowrecipe')),
                ('source', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='engineering_notes', to='vision.imagesource')),
                ('supersedes', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='replacement', to='vision.engineeringnote')),
            ],
            options={
                'ordering': ['-updated_at', '-id'],
                'constraints': [models.CheckConstraint(condition=models.Q(('applies_from_version__isnull', True), ('applies_to_version__isnull', True), ('applies_from_version__lte', models.F('applies_to_version')), _connector='OR'), name='note_version_range')],
            },
        ),
    ]
