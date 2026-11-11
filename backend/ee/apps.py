from django.apps import AppConfig


class EnterpriseConfig(AppConfig):
    name = 'ee'
    label = 'ee'
    verbose_name = 'SerOps Enterprise'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        from Utils import edition
        from ee.licensing.store import provider
        edition.register(provider)
