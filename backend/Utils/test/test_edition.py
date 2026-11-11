"""Community side of the edition registry: never imports ee/, and a broken
or missing Enterprise provider can't take a Community feature down."""
from unittest import mock

from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from Organisations.models import Organisations
from Users.models import User
from Utils import edition


class FakeProvider:
    def __init__(self, features=(), summary=None, fail=False):
        self.features, self.summary, self.fail = features, summary or {'status': 'valid'}, fail

    def licensed_features(self):
        if self.fail:
            raise RuntimeError('boom')
        return self.features

    def license_summary(self):
        if self.fail:
            raise RuntimeError('boom')
        return self.summary


class EditionRegistryTest(SimpleTestCase):
    def setUp(self):
        patcher = mock.patch.object(edition, '_provider', None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_community_has_no_enterprise_feature(self):
        self.assertFalse(edition.enterprise_available())
        self.assertEqual(edition.licensed_features(), frozenset())
        self.assertFalse(edition.has_feature('saml'))
        self.assertEqual(edition.summary(), {'enterprise_available': False, 'features': [], 'license': None})

    def test_registered_provider_answers(self):
        edition.register(FakeProvider(features={'saml'}))
        self.assertTrue(edition.has_feature('saml'))
        self.assertFalse(edition.has_feature('scim'))
        self.assertEqual(edition.summary()['features'], ['saml'])

    def test_failing_provider_means_no_enterprise_feature(self):
        edition.register(FakeProvider(fail=True))
        with self.assertLogs('Utils.edition', 'ERROR'):
            self.assertFalse(edition.has_feature('saml'))
        with self.assertLogs('Utils.edition', 'ERROR'):
            self.assertEqual(edition.summary()['license'], None)


class EditionEndpointTest(APITestCase):
    def setUp(self):
        org = Organisations.objects.create(name='Acme')
        self.viewer = User.objects.create_user(username='v', email='v@acme.test', password='Pass-word-123',
                                               organisation=org, role='viewer', is_active=True)

    def test_any_member_reads_the_edition(self):
        self.assertEqual(self.client.get('/api/organisation/edition/').status_code, 401)
        self.client.force_authenticate(user=self.viewer)
        with mock.patch.object(edition, '_provider', None):
            response = self.client.get('/api/organisation/edition/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'enterprise_available': False, 'features': [], 'license': None})
