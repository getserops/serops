"""POST /api/organisation/create/ is gone (audit 2026-11-20, item 12).

It created an organisation with settings.manage, a permission any
organisation admin holds; the web app never called it. Organisations are
created by sign-up (when registration is open) and createsuperuser.
"""
from django.test import SimpleTestCase
from django.urls import Resolver404, resolve


class NoCreateRouteTest(SimpleTestCase):
    def test_route_removed(self):
        with self.assertRaises(Resolver404):
            resolve('/api/organisation/create/')
