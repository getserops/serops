"""Cache backend choice (audit 2026-11-20, item 5).

Throttles, the AI circuit breaker and SAML request tracking need a cache
shared by every process. Only redis:// used to count, so rediss:// (TLS) and
unix:// installs silently got a cache per process.
"""
from django.test import SimpleTestCase

from api.settings import _cache_config

REDIS = 'django.core.cache.backends.redis.RedisCache'
LOCMEM = 'django.core.cache.backends.locmem.LocMemCache'


class CacheConfigTest(SimpleTestCase):
    def test_redis_schemes_use_redis(self):
        for url in ('redis://redis:6379/0', 'rediss://:pw@cache.example:6380/0',
                    'unix:///var/run/redis/redis.sock?db=0', 'REDISS://cache.example:6380/0'):
            for debug in (True, False):
                with self.subTest(url=url, debug=debug):
                    caches, problem = _cache_config(url, debug)
                    self.assertEqual(caches['default']['BACKEND'], REDIS)
                    self.assertEqual(caches['default']['LOCATION'], url)
                    self.assertIsNone(problem)

    def test_unusable_scheme_is_an_error_outside_debug(self):
        for url in ('amqp://guest@rabbit//', 'sqs://', 'memcached://m:11211', 'redis-sentinel'):
            with self.subTest(url=url):
                caches, problem = _cache_config(url, False)
                self.assertEqual(problem[0], 'error')
                self.assertIn('redis://, rediss:// or unix://', problem[1])
                self.assertEqual(caches['default']['BACKEND'], LOCMEM)

    def test_no_url_warns_outside_debug(self):
        caches, problem = _cache_config('', False)
        self.assertEqual(caches['default']['BACKEND'], LOCMEM)
        self.assertEqual(problem[0], 'warning')
        self.assertIn('per process', problem[1])

    def test_debug_is_quiet_without_redis(self):
        for url in ('', 'amqp://guest@rabbit//'):
            with self.subTest(url=url):
                caches, problem = _cache_config(url, True)
                self.assertEqual(caches['default']['BACKEND'], LOCMEM)
                self.assertIsNone(problem)
