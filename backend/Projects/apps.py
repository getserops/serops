from django.apps import AppConfig


class ProjectsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'Projects'

    def ready(self):
        # Wire signal handlers for auto-creating ProjectDeployment rows
        # when new envs are added (Batch 48). Import inside ready() per
        # Django conventions so tests + management commands don't
        # accidentally import before app registry is ready.
        from . import signals  # noqa: F401
