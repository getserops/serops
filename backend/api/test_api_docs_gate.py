"""Swagger UI only in DEBUG or with SEROPS_API_DOCS=true (audit 2026-11-20, item 13).

/api/docs/ listed every endpoint to anyone; a second, unused schema view in
providers/views.py was public "for easier testing" and is gone.
"""
import importlib

from django.test import SimpleTestCase, override_settings
from django.urls import Resolver404, clear_url_caches, resolve

import api.urls
import providers.views


def _reload_urls():
    clear_url_caches()
    importlib.reload(api.urls)


class ApiDocsGateTest(SimpleTestCase):
    def tearDown(self):
        _reload_urls()  # back to the settings the run started with

    @override_settings(SEROPS_API_DOCS=False)
    def test_docs_not_served_when_off(self):
        _reload_urls()
        with self.assertRaises(Resolver404):
            resolve('/api/docs/')

    @override_settings(SEROPS_API_DOCS=True)
    def test_docs_served_when_on(self):
        _reload_urls()
        self.assertEqual(resolve('/api/docs/').url_name, 'schema-swagger-ui')

    def test_metadata(self):
        info = api.urls.API_INFO
        self.assertEqual(info.title, 'SerOps API')
        self.assertEqual(info.terms_of_service, 'https://serops.ai/terms')
        self.assertIn('AGPL-3.0', info.license.name)
        self.assertNotIn('google', str(info).lower())

    def test_unused_schema_view_removed(self):
        self.assertFalse(hasattr(providers.views, 'schema_view'))
