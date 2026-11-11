"""Roles and accounts from the identity provider's groups (Users/sso_roles.py)."""
import base64
import json
from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from Data.models import AuditLog
from Organisations.models import Organisations
from Users import sso_roles
from Users.models import SecuritySettings, User
from Users.test.test_sso_flow import start_flow


def id_token(claims):
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')
    return f'eyJhbGciOiJSUzI1NiJ9.{body}.sig'


class ResolveRoleTest(SimpleTestCase):
    RULES = [{'group': 'platform-admins', 'role': 'admin'}, {'group': 'sre', 'role': 'user'}]

    def test_first_matching_rule_wins(self):
        self.assertEqual(sso_roles.resolve_role(['sre', 'platform-admins'], self.RULES, 'viewer'), 'admin')
        self.assertEqual(sso_roles.resolve_role(['sre'], self.RULES, 'viewer'), 'user')

    def test_case_and_group_paths(self):
        self.assertEqual(sso_roles.resolve_role(['/Org/SRE'], self.RULES, 'viewer'), 'user')

    def test_default_and_deny(self):
        self.assertEqual(sso_roles.resolve_role(['sales'], self.RULES, 'viewer'), 'viewer')
        self.assertIsNone(sso_roles.resolve_role([], self.RULES, 'deny'))

    def test_extract_groups(self):
        claims = {'groups': ['a', 'b'], 'realm_access': {'roles': ['x']}, 'team': 'solo', 'n': 5}
        self.assertEqual(sso_roles.extract_groups(claims, 'groups'), ['a', 'b'])
        self.assertEqual(sso_roles.extract_groups(claims, 'realm_access.roles'), ['x'])
        self.assertEqual(sso_roles.extract_groups(claims, 'team'), ['solo'])
        self.assertEqual(sso_roles.extract_groups(claims, 'missing.path'), [])
        self.assertEqual(sso_roles.extract_groups(claims, 'n'), [])

    def test_id_token_claims(self):
        self.assertEqual(sso_roles.id_token_claims({'id_token': id_token({'groups': ['g']})}), {'groups': ['g']})
        self.assertEqual(sso_roles.id_token_claims({'id_token': 'garbage'}), {})
        self.assertEqual(sso_roles.id_token_claims('not-a-dict'), {})

    def test_domains(self):
        self.assertEqual(sso_roles.normalise_domains([' @Acme.COM', 'acme.com', '']), ['acme.com'])
        with self.assertRaises(ValueError):
            sso_roles.normalise_domains(['not a domain'])


class SSOGroupCallbackTest(APITestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='Acme')
        self.admin = User.objects.create_user(
            username='admin', email='admin@acme.test', password='x', organisation=self.org, role='admin', is_active=True)
        self.sec = SecuritySettings.objects.create(
            organisation=self.org, sso_enabled=True, sso_provider='oidc', sso_client_id='c',
            sso_discovery_url='https://idp.example.com/.well-known/openid-configuration',
            sso_role_mappings=[{'group': 'platform-admins', 'role': 'admin'}, {'group': 'sre', 'role': 'user'}],
            sso_domains=['acme.test'])

    def sign_in(self, email, groups=None, token_groups=None):
        with patch('Users.sso_views.SSOService') as Service:
            sso = Service.return_value
            token = {'access_token': 't'}
            if token_groups is not None:
                token['id_token'] = id_token({'groups': token_groups})
            sso.exchange_code_for_token.return_value = token
            info = {'email': email, 'email_verified': True}
            if groups is not None:
                info['groups'] = groups
            sso.get_user_info.return_value = info
            state = start_flow(self.client, self.org.id)
            return self.client.get(reverse('sso-callback'), {'code': 'c', 'state': state}), Service

    def test_new_account_gets_the_mapped_role(self):
        response, _ = self.sign_in('bo@acme.test', groups=['sre'])
        self.assertTrue(response['Location'].endswith('/auth/callback'))
        user = User.objects.get(email='bo@acme.test')
        self.assertEqual((user.role, user.organisation_id), ('user', self.org.id))
        self.assertTrue(AuditLog.objects.filter(action='SSO_PROVISION', details__role='user').exists())

    def test_groups_only_in_the_id_token(self):
        self.sign_in('id@acme.test', token_groups=['platform-admins'])
        self.assertEqual(User.objects.get(email='id@acme.test').role, 'admin')

    def test_no_matching_group_uses_the_default(self):
        self.sign_in('sales@acme.test', groups=['sales'])
        self.assertEqual(User.objects.get(email='sales@acme.test').role, 'viewer')

    def test_deny_default_refuses_and_audits(self):
        self.sec.sso_default_role = 'deny'
        self.sec.save()
        response, _ = self.sign_in('sales@acme.test', groups=['sales'])
        self.assertTrue(response['Location'].endswith('/login?sso=denied'))
        self.assertNotIn('serops_sso_handoff', response.cookies)
        self.assertFalse(User.objects.filter(email='sales@acme.test').exists())
        self.assertTrue(AuditLog.objects.filter(organisation=self.org, action='SSO_DENIED').exists())

    def test_deny_default_also_refuses_existing_members(self):
        User.objects.create_user(username='m', email='m@acme.test', password='x', organisation=self.org,
                                 role='user', is_active=True)
        self.sec.sso_default_role = 'deny'
        self.sec.save()
        response, _ = self.sign_in('m@acme.test', groups=[])
        self.assertTrue(response['Location'].endswith('/login?sso=denied'))

    def test_without_sync_an_existing_role_is_kept(self):
        member = User.objects.create_user(username='m', email='m@acme.test', password='x', organisation=self.org,
                                          role='viewer', is_active=True)
        self.sign_in('m@acme.test', groups=['platform-admins'])
        member.refresh_from_db()
        self.assertEqual(member.role, 'viewer')

    def test_with_sync_the_provider_decides(self):
        self.sec.sso_sync_role = True
        self.sec.save()
        member = User.objects.create_user(username='m', email='m@acme.test', password='x', organisation=self.org,
                                          role='admin', is_active=True)
        self.sign_in('m@acme.test', groups=['sre'])
        member.refresh_from_db()
        self.assertEqual(member.role, 'user')
        entry = AuditLog.objects.get(action='TEAM_ROLE_CHANGE')
        self.assertEqual((entry.details['source'], entry.details['old_role']), ('sso', 'admin'))

    def test_sync_never_demotes_the_last_admin(self):
        self.sec.sso_sync_role = True
        self.sec.save()
        self.sign_in('admin@acme.test', groups=[])
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, 'admin')

    def test_extra_scopes_are_requested(self):
        self.sec.sso_extra_scopes = 'groups'
        self.sec.save()
        _, Service = self.sign_in('bo@acme.test', groups=['sre'])
        self.assertEqual(Service.call_args.kwargs['extra_scopes'], 'groups')

    def test_custom_claim_path(self):
        self.sec.sso_groups_claim = 'realm_access.roles'
        self.sec.save()
        with patch('Users.sso_views.SSOService') as Service:
            Service.return_value.exchange_code_for_token.return_value = {'access_token': 't'}
            Service.return_value.get_user_info.return_value = {
                'email': 'kc@acme.test', 'email_verified': True, 'realm_access': {'roles': ['platform-admins']}}
            self.client.get(reverse('sso-callback'), {'code': 'c', 'state': start_flow(self.client, self.org.id)})
        self.assertEqual(User.objects.get(email='kc@acme.test').role, 'admin')


class SSODomainDiscoveryTest(APITestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='Acme')
        SecuritySettings.objects.create(
            organisation=self.org, sso_enabled=True, sso_provider='oidc', sso_client_id='c',
            sso_discovery_url='https://idp.example.com/.well-known/openid-configuration',
            sso_domains=['acme.test'])

    def init(self, email):
        with patch('Users.sso_views.SSOService') as Service:
            Service.return_value.get_authorization_url.return_value = ('https://idp.example.com/auth?x', 's')
            return self.client.post(reverse('sso-init'), {'email': email}, format='json')

    def test_uninvited_person_of_a_listed_domain_can_start(self):
        response = self.init('newcomer@ACME.test')
        self.assertEqual(response.status_code, 200)
        self.assertIn('auth_url', response.data)

    def test_other_domains_get_the_generic_answer(self):
        self.assertEqual(self.init('someone@elsewhere.test').status_code, 400)

    def test_disabled_account_is_not_rescued_by_its_domain(self):
        User.objects.create_user(username='d', email='gone@acme.test', password='x', organisation=self.org,
                                 role='user', is_active=False)
        self.assertEqual(self.init('gone@acme.test').status_code, 400)


class SSOConfigMappingTest(APITestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='Acme')
        self.admin = User.objects.create_user(
            username='admin', email='admin@acme.test', password='x', organisation=self.org, role='admin', is_active=True)
        self.client.force_authenticate(user=self.admin)
        self.url = reverse('sso-config')

    def put(self, **data):
        return self.client.put(self.url, data, format='json')

    def test_rules_round_trip(self):
        rules = [{'group': ' sre ', 'role': 'user'}]
        self.assertEqual(self.put(sso_role_mappings=rules, sso_default_role='deny', sso_sync_role=True,
                                  sso_groups_claim='groups', sso_extra_scopes=' groups  ').status_code, 200)
        data = self.client.get(self.url).data
        self.assertEqual(data['sso_role_mappings'], [{'group': 'sre', 'role': 'user'}])
        self.assertEqual((data['sso_default_role'], data['sso_sync_role'], data['sso_extra_scopes']),
                         ('deny', True, 'groups'))

    def test_invalid_rules_are_refused(self):
        self.assertEqual(self.put(sso_role_mappings=[{'group': 'x', 'role': 'owner'}]).status_code, 400)
        self.assertEqual(self.put(sso_role_mappings=[{'group': '', 'role': 'user'}]).status_code, 400)
        self.assertEqual(self.put(sso_default_role='root').status_code, 400)

    def test_single_org_admin_sets_domains(self):
        self.assertEqual(self.put(sso_domains=['Acme.test']).status_code, 200)
        self.assertEqual(SecuritySettings.objects.get(organisation=self.org).sso_domains, ['acme.test'])

    def test_domains_need_staff_on_a_multi_org_install(self):
        Organisations.objects.create(name='Other')
        response = self.put(sso_domains=['acme.test'])
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.client.get(self.url).data['sso_domains_editable'])

    def test_a_domain_belongs_to_one_organisation(self):
        other = Organisations.objects.create(name='Other')
        SecuritySettings.objects.create(organisation=other, sso_domains=['acme.test'])
        self.admin.is_staff = True
        self.admin.save()
        self.assertEqual(self.put(sso_domains=['acme.test']).status_code, 400)


class SSOExchangePermissionsTest(APITestCase):
    def test_exchange_returns_the_permission_list(self):
        from knox.models import AuthToken
        org = Organisations.objects.create(name='Acme')
        user = User.objects.create_user(username='u', email='u@acme.test', password='x', organisation=org,
                                        role='user', is_active=True)
        _, token = AuthToken.objects.create(user)
        self.client.cookies['serops_sso_handoff'] = token
        response = self.client.post(reverse('sso-exchange'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('project.write', response.data['user']['permissions'])
        self.assertNotIn('password', response.data['user'])


class SSOEmailDomainsCommandTest(APITestCase):
    def test_sets_lists_and_refuses_duplicates(self):
        from io import StringIO
        from django.core.management import CommandError, call_command
        acme = Organisations.objects.create(name='Acme')
        other = Organisations.objects.create(name='Other')
        call_command('sso_domains', 'Acme', 'ACME.test', 'acme.io', stdout=StringIO())
        self.assertEqual(SecuritySettings.objects.get(organisation=acme).sso_domains, ['acme.test', 'acme.io'])
        with self.assertRaises(CommandError):
            call_command('sso_domains', str(other.id), 'acme.io', stdout=StringIO())
        out = StringIO()
        call_command('sso_domains', '--list', stdout=out)
        self.assertIn('acme.test', out.getvalue())
        call_command('sso_domains', 'Acme', '--clear', stdout=StringIO())
        self.assertEqual(SecuritySettings.objects.get(organisation=acme).sso_domains, [])


class UserPayloadShapeTest(APITestCase):
    """Login, profile and the SSO exchange send the same user shape (the UI
    reads ``organisation`` as a name: an id crashed the Settings page)."""

    def test_organisation_is_the_name_everywhere(self):
        from knox.models import AuthToken
        org = Organisations.objects.create(name='Acme')
        user = User.objects.create_user(username='u', email='u@acme.test', password='Pass-word-123', organisation=org,
                                        role='user', is_active=True)
        login = self.client.post(reverse('login'), {'email': 'u@acme.test', 'password': 'Pass-word-123'}, format='json')
        _, token = AuthToken.objects.create(user)
        self.client.cookies['serops_sso_handoff'] = token
        exchange = self.client.post(reverse('sso-exchange'))
        self.client.force_authenticate(user=user)
        profile = self.client.get('/api/auth/profile')
        for name, data in (('login', login.data['user']), ('exchange', exchange.data['user']), ('profile', profile.data)):
            self.assertEqual((data['organisation'], data['organisation_id'], data['role']), ('Acme', org.id, 'user'), name)
