"""Placeholder-secret guard.

.env.example ships change-me values for the secret key and the Postgres and
Redis passwords. Compose rejects a missing password but not a placeholder, so
the backend refuses to start on one (outside DEBUG). These tests pin which
variables are checked and that real values pass.
"""
from django.test import SimpleTestCase

from api.settings import _placeholder_secrets


class PlaceholderSecretsTest(SimpleTestCase):

    def test_quick_start_template_values_are_caught(self):
        env = {
            'DJANGO_SECRET_KEY': 'change-me-generate-a-real-one',
            'DB_PASSWORD': 'change-me-strong-postgres-password',
            'CELERY_BROKER_URL': 'redis://:change-me-strong-redis-password@redis:6379/0',
        }
        self.assertEqual(
            _placeholder_secrets(env),
            ['DJANGO_SECRET_KEY', 'DB_PASSWORD', 'CELERY_BROKER_URL'],
        )

    def test_real_values_pass(self):
        env = {
            'DJANGO_SECRET_KEY': 'x8Jm2kq0-real-random-value',
            'DB_PASSWORD': '3f9a0c7e1b2d',
            'DATABASE_URL': 'postgres://serops:3f9a0c7e1b2d@db:5432/serops',
            'REDIS_URL': 'redis://:a1b2c3@redis:6379/0',
        }
        self.assertEqual(_placeholder_secrets(env), [])

    def test_unset_variables_are_ignored(self):
        self.assertEqual(_placeholder_secrets({}), [])

    def test_case_insensitive(self):
        self.assertEqual(
            _placeholder_secrets({'REDIS_PASSWORD': 'CHANGE-ME-later'}),
            ['REDIS_PASSWORD'],
        )

    def test_unrelated_variables_are_not_checked(self):
        self.assertEqual(
            _placeholder_secrets({'PROJECT_NAME': 'change-me'}), [])
