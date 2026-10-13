"""DATABASE_URL parsing.

The Helm chart was already emitting DATABASE_URL, but nothing in the app read
it, so a chart-deployed backend silently fell through to the DB_* defaults and
tried to reach Postgres on localhost. These tests pin the parser and, more
importantly, pin that DB_* keeps working — docker-compose and .env.example set
the five discrete variables and must not be disturbed.
"""
from django.test import SimpleTestCase

from api.settings import _database_config_from_url


class DatabaseUrlParsingTest(SimpleTestCase):

    def test_full_url(self):
        cfg = _database_config_from_url(
            'postgres://alice:s3cret@db.internal:5433/serops')
        self.assertEqual(cfg, {
            'NAME': 'serops', 'USER': 'alice', 'PASSWORD': 's3cret',
            'HOST': 'db.internal', 'PORT': '5433',
        })

    def test_postgresql_scheme_accepted(self):
        cfg = _database_config_from_url(
            'postgresql://u:p@host:5432/db')
        self.assertEqual(cfg['NAME'], 'db')

    def test_port_omitted_leaves_django_default(self):
        cfg = _database_config_from_url('postgres://u:p@host/db')
        self.assertEqual(cfg['PORT'], '')

    def test_percent_encoded_password_is_decoded(self):
        """Generated secrets routinely contain @ : / #, which must be
        percent-encoded in a URL. Handing Django the encoded form would fail
        authentication with a misleading 'password authentication failed'."""
        cfg = _database_config_from_url(
            'postgres://u:p%40ss%3Aword%2F1@host:5432/db')
        self.assertEqual(cfg['PASSWORD'], 'p@ss:word/1')

    def test_percent_encoded_username_is_decoded(self):
        cfg = _database_config_from_url('postgres://a%40b:p@host:5432/db')
        self.assertEqual(cfg['USER'], 'a@b')

    def test_no_credentials(self):
        cfg = _database_config_from_url('postgres://host:5432/db')
        self.assertEqual(cfg['USER'], '')
        self.assertEqual(cfg['PASSWORD'], '')
        self.assertEqual(cfg['HOST'], 'host')

    # -- rejected, so the caller falls back to DB_* --------------------

    def test_missing_database_name_rejected(self):
        self.assertIsNone(_database_config_from_url('postgres://u:p@host:5432'))
        self.assertIsNone(_database_config_from_url('postgres://u:p@host:5432/'))

    def test_missing_host_rejected(self):
        self.assertIsNone(_database_config_from_url('postgres:///db'))

    def test_non_postgres_scheme_rejected(self):
        """SerOps is Postgres-only; accepting mysql:// would produce a config
        the postgresql engine cannot use, failing later and less clearly."""
        for url in ('mysql://u:p@host/db', 'sqlite:///tmp/db.sqlite3',
                    'redis://host:6379/0'):
            with self.subTest(url=url):
                self.assertIsNone(_database_config_from_url(url))

    def test_garbage_rejected(self):
        for url in ('', 'not-a-url', '://', 'postgres://'):
            with self.subTest(url=url):
                self.assertIsNone(_database_config_from_url(url))


class DatabaseSettingsResolutionTest(SimpleTestCase):
    """The precedence itself, exercised by re-importing settings under a
    patched environment."""

    def _resolve(self, env):
        import importlib
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, env, clear=False):
            import api.settings as s
            importlib.reload(s)
            return s.DATABASES['default']

    def tearDown(self):
        # Leave the module matching the real environment for other tests.
        import importlib
        import api.settings as s
        importlib.reload(s)

    def test_database_url_wins_when_set(self):
        cfg = self._resolve({
            'DATABASE_URL': 'postgres://u:p@urlhost:5432/urldb',
            'DB_NAME': 'envdb', 'DB_HOST': 'envhost',
        })
        self.assertEqual(cfg['HOST'], 'urlhost')
        self.assertEqual(cfg['NAME'], 'urldb')

    def test_falls_back_to_discrete_vars(self):
        """docker-compose path — must keep working untouched."""
        cfg = self._resolve({
            'DATABASE_URL': '',
            'DB_NAME': 'envdb', 'DB_USER': 'envuser',
            'DB_PASSWORD': 'envpass', 'DB_HOST': 'postgres', 'DB_PORT': '5432',
        })
        self.assertEqual(cfg['HOST'], 'postgres')
        self.assertEqual(cfg['NAME'], 'envdb')

    def test_unparseable_url_falls_back_rather_than_crashing(self):
        cfg = self._resolve({
            'DATABASE_URL': 'mysql://u:p@nope/db',
            'DB_NAME': 'envdb', 'DB_HOST': 'postgres',
        })
        self.assertEqual(cfg['HOST'], 'postgres')

    def test_engine_always_postgres(self):
        cfg = self._resolve({'DATABASE_URL': 'postgres://u:p@h:5432/d'})
        self.assertEqual(cfg['ENGINE'], 'django.db.backends.postgresql')

    def test_connection_reuse_settings_preserved(self):
        cfg = self._resolve({'DATABASE_URL': 'postgres://u:p@h:5432/d'})
        self.assertEqual(cfg['CONN_MAX_AGE'], 300)
        self.assertTrue(cfg['CONN_HEALTH_CHECKS'])
