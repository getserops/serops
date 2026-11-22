"""Email identity is case-insensitive (audit 2026-11-20, item 8)."""
import importlib

from django.contrib.auth import authenticate
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from Organisations.models import Organisations
from Users.emails import normalize_email, sso_domain_claimed_elsewhere
from Users.models import SecuritySettings, User

PW = 'Corr' + 'ectHorse9!'


class NormaliseTest(TestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='Case Org')

    def test_saved_lowercase_on_every_write(self):
        u = User.objects.create_user(username='a', email='  Ann.Lee@Example.COM ', password=PW, organisation=self.org)
        self.assertEqual(u.email, 'ann.lee@example.com')
        u.email = 'ANN@EXAMPLE.COM'; u.save()
        u.refresh_from_db(); self.assertEqual(u.email, 'ann@example.com')
        su = User.objects.create_superuser(username='root', email='Root@Example.com', password=PW)
        self.assertEqual(su.email, 'root@example.com')

    def test_database_refuses_a_case_duplicate(self):
        User.objects.create_user(username='a', email='ann@example.com', password=PW, organisation=self.org)
        with self.assertRaises(IntegrityError), transaction.atomic():
            # Bypass save() normalisation: the constraint is the last line.
            User.objects.bulk_create([User(username='b', email='ANN@example.com', organisation=self.org)])

    def test_helpers(self):
        self.assertEqual(normalize_email(' X@Y.Z '), 'x@y.z')
        self.assertEqual(normalize_email(None), '')


class LookupTest(TestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='Lookup Org')
        self.user = User.objects.create_user(username='m', email='mixed@example.com', password=PW,
                                             organisation=self.org, is_active=True, role='admin')
        self.client = APIClient()

    def test_login_any_case(self):
        r = self.client.post('/api/auth/login', {'email': 'MIXED@Example.com', 'password': PW}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(authenticate(username='Mixed@EXAMPLE.com', password=PW), self.user)

    def test_registration_sees_the_existing_account_any_case(self):
        r = self.client.post('/api/auth/register', {'email': 'MIXED@example.com', 'username': 'x', 'password': PW,
                                                    'password2': PW, 'organisation_name': 'New'}, format='json')
        self.assertIn(r.status_code, (400, 403), r.content)
        self.assertEqual(User.objects.filter(email__iexact='mixed@example.com').count(), 1)


class SsoDomainTest(TestCase):
    def test_claimed_by_another_organisation(self):
        mine = Organisations.objects.create(name='Mine')
        theirs = Organisations.objects.create(name='Theirs')
        SecuritySettings.objects.create(organisation=theirs, sso_enabled=True, sso_provider='oidc', sso_domains=['corp.example'])
        self.assertTrue(sso_domain_claimed_elsewhere('Bob@CORP.example', mine.id))
        self.assertFalse(sso_domain_claimed_elsewhere('bob@corp.example', theirs.id))
        self.assertFalse(sso_domain_claimed_elsewhere('bob@other.example', mine.id))


class MigrationCheckTest(TestCase):
    def test_duplicates_stop_the_migration_and_are_listed(self):
        from django.apps import apps
        mod = importlib.import_module('Users.migrations.0018_email_case_insensitive')
        org = Organisations.objects.create(name='Dup Org')
        User.objects.create_user(username='d1', email='dup@example.com', password=PW, organisation=org)
        self.assertIsNone(mod.refuse_case_duplicates(apps, None))
        with mock_constraint_off():
            User.objects.bulk_create([User(username='d2', email='DUP@example.com', organisation=org)])
            with self.assertRaisesMessage(RuntimeError, 'd***@example.com: user ids'):
                mod.refuse_case_duplicates(apps, None)


class mock_constraint_off:
    """Drop the constraint for the duration (to build the state the migration meets)."""
    def __enter__(self):
        from django.db import connection
        with connection.cursor() as c:
            c.execute('DROP INDEX IF EXISTS users_email_lower_unique')
        return self

    def __exit__(self, *exc):
        return False


class SsoDomainEverywhereTest(TestCase):
    """The rule of an email change now also holds for invitations, SCIM and sign-up."""

    def setUp(self):
        self.mine = Organisations.objects.create(name='Mine2')
        self.theirs = Organisations.objects.create(name='Theirs2')
        SecuritySettings.objects.create(organisation=self.theirs, sso_enabled=True, sso_provider='oidc',
                                        sso_domains=['corp.example'])
        self.admin = User.objects.create_user(username='adm2', email='adm2@mine.example', password=PW,
                                              organisation=self.mine, role='admin', is_active=True)
        self.client = APIClient()

    def test_invitation_refused(self):
        self.client.force_authenticate(self.admin)
        r = self.client.post('/api/organisation/team/', {'user': {'email': 'Bob@Corp.example', 'role': 'viewer'}}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(r.json(), {'email': 'This email address cannot be used.'})
        self.assertFalse(User.objects.filter(email__iexact='bob@corp.example').exists())

    @override_settings(REGISTRATION_ENABLED=True)
    def test_registration_refused(self):
        r = self.client.post('/api/auth/register', {'user': {'email': 'eve@corp.example', 'username': 'eve', 'password': PW,
                                                    'password_confirmation': PW}, 'organisation': {'name': 'Eve Inc'}},
                             format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(r.json()['error'], 'This email address cannot be used.')
        self.assertFalse(User.objects.filter(email__iexact='eve@corp.example').exists())

    @override_settings(REGISTRATION_ENABLED=True)
    def test_registration_refuses_a_malformed_address(self):
        r = self.client.post('/api/auth/register', {'user': {'email': 'not-an-email', 'username': 'x', 'password': PW,
                                                    'password_confirmation': PW}, 'organisation': {'name': 'X'}},
                             format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(r.json()['error'], 'Enter a valid email address.')
