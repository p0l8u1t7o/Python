# 模型版本與註冊式工具快照。

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vision', '0033_vision_settings'),
    ]

    operations = [
        migrations.CreateModel(
            name='DlModelVersion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('node_id', models.CharField(blank=True, default='', max_length=80)),
                ('number', models.PositiveIntegerField()),
                ('asset_id', models.CharField(blank=True, default='', max_length=40)),
                ('params', models.JSONField(default=dict)),
                ('tune_samples', models.JSONField(default=list)),
                ('holdout_samples', models.JSONField(default=list)),
                ('metrics', models.JSONField(default=dict)),
                ('failures', models.JSONField(default=list)),
                ('status', models.CharField(choices=[('candidate', 'Candidate'), ('active', 'Active'), ('retired', 'Retired')], default='candidate', max_length=12)),
                ('note', models.TextField(blank=True, default='')),
                ('created_by', models.CharField(blank=True, default='', max_length=150)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('dataset_version', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.RESTRICT, related_name='models', to='vision.dldatasetversion')),
                ('flow', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='model_versions', to='vision.flow')),
                ('parent', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='children', to='vision.dlmodelversion')),
                ('project', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='model_versions', to='vision.dlproject')),
            ],
            options={
                'ordering': ['-number'],
                'constraints': [models.UniqueConstraint(fields=('project', 'number'), name='dl_model_project_number'), models.UniqueConstraint(fields=('flow', 'node_id', 'number'), name='dl_model_node_number'), models.UniqueConstraint(condition=models.Q(('status', 'active')), fields=('project',), name='dl_model_project_active'), models.UniqueConstraint(condition=models.Q(('status', 'active')), fields=('flow', 'node_id'), name='dl_model_node_active'), models.CheckConstraint(condition=models.Q(models.Q(('flow__isnull', True), ('node_id', ''), ('project__isnull', False)), models.Q(('flow__isnull', False), ('project__isnull', True), models.Q(('node_id', ''), _negated=True)), _connector='OR'), name='dl_model_scope')],
            },
        ),
    ]
