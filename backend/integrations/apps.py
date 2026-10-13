from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'integrations'
    verbose_name = 'Log & Metric Integrations'

    def ready(self):
        # Batch 48 — auto-create IntegrationScope mirror when a new
        # ObservabilityIntegration is created. Import inside ready()
        # so app-registry loads cleanly.
        from . import signals  # noqa: F401
