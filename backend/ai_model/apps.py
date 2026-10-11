from django.apps import AppConfig


class AiModelConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ai_model'

    def ready(self):
        # Registers the startup check that warns when an AI provider key is
        # set in the environment, where nothing reads it. Imported inside
        # ready() so the app registry loads cleanly.
        from . import checks  # noqa: F401
