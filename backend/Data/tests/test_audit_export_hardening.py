"""Audit log export and filters (audit 2026-11-20, item 14).

1. CSV cells that start like a formula (=, +, -, @, tab, CR) are prefixed
   with a quote, so opening the export in a spreadsheet runs nothing.
2. Unparseable date_from / date_to return 400 in both views (they reached
   the database and failed with a 500).
"""
import csv
import io
from datetime import datetime, timezone as dt_timezone

from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from Data.models import AuditLog
from Data.settings_views import _audit_date_filters, _csv_safe
from Organisations.models import Organisations
from Users.models import User


class CsvSafeTest(SimpleTestCase):
    def test_formula_starts_are_quoted(self):
        for raw in ('=HYPERLINK("http://x")', '+1+1', '-2+3', '@SUM(A1)', '\tx', '\rx'):
            with self.subTest(raw=raw):
                self.assertEqual(_csv_safe(raw), "'" + raw)

    def test_other_values_unchanged(self):
        for raw in ('LOGIN', 'admin@example.com', '127.0.0.1', '', "{'a': 1}"):
            with self.subTest(raw=raw):
                self.assertEqual(_csv_safe(raw), raw)
        self.assertEqual(_csv_safe(None), '')


class AuditDateFiltersTest(SimpleTestCase):
    def test_date_and_datetime(self):
        f = _audit_date_filters({'date_from': '2026-11-01', 'date_to': '2026-11-20T10:30:00Z'})
        self.assertEqual(f['created_at__gte'], datetime(2026, 11, 1, tzinfo=dt_timezone.utc))
        self.assertEqual(f['created_at__lte'], datetime(2026, 11, 20, 10, 30, tzinfo=dt_timezone.utc))

    def test_empty_is_no_filter(self):
        self.assertEqual(_audit_date_filters({'date_from': '', 'date_to': '  '}), {})

    def test_garbage_raises(self):
        for raw in ('yesterday', '2026-13-45', "2026-11-01' OR 1=1", '20261101x'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                _audit_date_filters({'date_from': raw})


class AuditViewsTest(TestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='Audit Org')
        self.admin = User.objects.create_user(
            username='auditadmin', email='auditadmin@test.com', password='Pass1234!',
            organisation=self.org, role='admin', is_active=True)
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def test_bad_dates_are_400_in_both_views(self):
        for name in ('audit-log', 'audit-log-export'):
            for param in ('date_from', 'date_to'):
                with self.subTest(view=name, param=param):
                    r = self.client.get(reverse(name), {param: 'not-a-date'})
                    self.assertEqual(r.status_code, 400)
                    self.assertIn(param, r.json()['error'])

    def test_good_dates_still_filter(self):
        old = AuditLog.objects.create(organisation=self.org, user=self.admin, action='LOGIN', details={})
        AuditLog.objects.filter(pk=old.pk).update(created_at=datetime(2026, 1, 5, tzinfo=dt_timezone.utc))
        AuditLog.objects.create(organisation=self.org, user=self.admin, action='LOGIN', details={})
        r = self.client.get(reverse('audit-log'), {'date_from': '2026-02-01'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['pagination']['total'], 1)

    def test_export_cells_cannot_be_formulas(self):
        AuditLog.objects.create(organisation=self.org, user=self.admin, action='LOGIN',
                                details='=HYPERLINK("http://evil.example","x")')
        r = self.client.get(reverse('audit-log-export'))
        self.assertEqual(r.status_code, 200)
        rows = list(csv.reader(io.StringIO(r.content.decode())))
        details = [row[3] for row in rows[1:] if 'HYPERLINK' in row[3]]
        self.assertEqual(details, ['\'=HYPERLINK("http://evil.example","x")'])
