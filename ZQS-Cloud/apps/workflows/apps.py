from django.apps import AppConfig


class WorkflowsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.workflows"
    label = "workflows"

    def ready(self) -> None:
        # Registered here rather than at import time: the node types query the
        # ORM, so they must not run before the app registry is populated.
        from apps.workflows.nodes.builtin import register_builtins

        register_builtins()
