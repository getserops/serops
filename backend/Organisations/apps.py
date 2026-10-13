from django.apps import AppConfig


class OrganisationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'Organisations'

    def ready(self):
        # Wire onboarding-related signal receivers. Import inside
        # ready() to avoid pulling model modules at AppConfig
        # construction time (Django can't import models before
        # the app registry is populated).
        from . import signals  # noqa: F401
