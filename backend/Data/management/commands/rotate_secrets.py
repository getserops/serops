"""
Re-encrypt every stored secret under the current SEROPS_ENCRYPTION_KEY.

Run it once after upgrading to a version with this key, and after each key
change. It is safe to run again. See Utils/crypto.py.
"""
from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from Utils import crypto
from integrations.models import SECRET_EXTRA_CONFIG_KEYS
from providers.encryption import SENSITIVE_FIELDS

# (model, field). Plain values on the GitLab table predate its encryption.
STRING_FIELDS = [
    ('org_settings.OrganisationAPIKey', 'api_key'),
    ('providers.GitlabProject', 'access_token'),
    ('notifications.IncidentNotificationChannel', 'webhook_url'),
    ('notifications.IncidentNotificationChannel', 'api_key'),
    ('integrations.ObservabilityIntegration', 'password'),
    ('Users.SecuritySettings', 'sso_client_secret_encrypted'),
]
PLAINTEXT_ALLOWED = {('providers.GitlabProject', 'access_token')}
DICT_FIELDS = [
    ('providers.ProviderIntegration', 'credentials', SENSITIVE_FIELDS),
    ('integrations.ObservabilityIntegration', 'extra_config', SECRET_EXTRA_CONFIG_KEYS),
]


class Command(BaseCommand):
    help = 'Re-encrypt every stored secret under the current SEROPS_ENCRYPTION_KEY.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Report what would change and write nothing.')

    def _rewrite(self, value, plaintext_allowed=False):
        """(new value or None if unchanged, whether the value is unreadable)."""
        if not crypto.is_ciphertext(value):
            return (crypto.encrypt(value), False) if plaintext_allowed else (None, True)
        if not crypto.can_decrypt(value):
            return None, True
        return (crypto.encrypt(crypto.decrypt(value)), False) if crypto.needs_rewrite(value) else (None, False)

    def handle(self, *args, **options):
        rewritten, unreadable = 0, []
        with transaction.atomic():
            for label, field in STRING_FIELDS:
                model = apps.get_model(label)
                for pk, value in model.objects.exclude(**{field: ''}).exclude(**{f'{field}__isnull': True}).values_list('pk', field):
                    new, bad = self._rewrite(value, (label, field) in PLAINTEXT_ALLOWED)
                    if bad:
                        unreadable.append(f'{label} {pk} {field}')
                    elif new:
                        rewritten += 1
                        if not options['dry_run']:
                            model.objects.filter(pk=pk).update(**{field: new})
            for label, field, secret_keys in DICT_FIELDS:
                model = apps.get_model(label)
                for pk, data in model.objects.values_list('pk', field):
                    updated, changed = dict(data or {}), 0
                    for key in secret_keys & updated.keys():
                        if not isinstance(updated[key], str) or not updated[key]:
                            continue
                        new, bad = self._rewrite(updated[key])
                        if bad:
                            unreadable.append(f'{label} {pk} {field}.{key}')
                        elif new:
                            updated[key], changed = new, changed + 1
                    rewritten += changed
                    if changed and not options['dry_run']:
                        model.objects.filter(pk=pk).update(**{field: updated})
        verb = 'Would re-encrypt' if options['dry_run'] else 'Re-encrypted'
        self.stdout.write(f'{verb} {rewritten} secret(s).')
        if unreadable:
            raise CommandError(
                f'{len(unreadable)} secret(s) cannot be read and were left as they are. Check that '
                'DJANGO_SECRET_KEY and SEROPS_ENCRYPTION_KEY_PREVIOUS are the ones they were written with, '
                'or enter them again:\n  ' + '\n  '.join(unreadable))
