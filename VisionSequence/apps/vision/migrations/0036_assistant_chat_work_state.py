from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("vision", "0035_agent_session_lessons")]
    operations = [
        migrations.AddField(
            model_name="assistantchat", name="flow",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name="assistant_chats", to="vision.flow"),
        ),
        migrations.AddField(model_name="assistantchat", name="work_state", field=models.JSONField(blank=True, default=dict)),
    ]
