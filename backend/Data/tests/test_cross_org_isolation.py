"""Cross-organisation isolation: a signed-in admin of org B must never read,
change or delete org A's objects by id. Every detail/action endpoint that
takes an object id is probed; all must return a non-2xx. 2026-10-20 review."""
from unittest import mock
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from Organisations.models import Organisations
from Projects.models import Project, ProjectService, ProjectEnvironment, CICDBinding
from Users.models import User
from Data.models import AIAnalyzedBatch, Issue, Investigation
from notifications.models import Notification, ProjectSubscription, EscalationRule
from providers.models import GitlabProject, ProviderIntegration
from org_settings.models import OrganisationAPIKey, AIModelProvider

class CrossOrgIsolationTest(TestCase):
    def setUp(self):
        self.A = Organisations.objects.create(name='Victim A')
        self.B = Organisations.objects.create(name='Attacker B')
        self.va = User.objects.create_user(username='va', email='va@a.x', password='x', organisation=self.A, role='admin', is_active=True)
        self.ba = User.objects.create_user(username='ba', email='ba@b.x', password='x', organisation=self.B, role='admin', is_active=True)
        self.member_a = User.objects.create_user(username='ma', email='ma@a.x', password='x', organisation=self.A, role='user', is_active=True)
        p = Project.objects.create(name='vproj', organisation=self.A)
        self.ids = {}
        self.ids['project'] = p.id
        svc = ProjectService.objects.create(project=p, name='vsvc')
        self.ids['service'] = svc.id
        b = AIAnalyzedBatch.objects.create(batch_id='VB1', project=p, organisation=self.A, timestamp=timezone.now(), data={'logs': []})
        self.ids['batch_id'] = b.batch_id
        iss = Issue.objects.create(batch=b, project=p, organisation=self.A, severity='CRITICAL', description='d', root_cause='r', fingerprint='vf', component='c')
        self.ids['issue'] = iss.id
        env = ProjectEnvironment.objects.create(project=p, name='production')
        inv = Investigation.objects.create(organisation=self.A, project=p, requested_by=self.va, environment=env, window_start=timezone.now(), window_end=timezone.now())
        self.ids['investigation'] = inv.id
        notif = Notification.objects.create(user=self.va, subject='s', message='m', notification_type='issue')
        self.ids['notification'] = notif.id
        sub = ProjectSubscription.objects.create(user=self.va, project=p)
        self.ids['subscription'] = sub.id
        esc = EscalationRule.objects.create(organisation=self.A, project=p)
        self.ids['escalation'] = esc.id
        gp = GitlabProject.objects.create(gitlab_url='u', username='u', name='n', project_id='9001', access_token='victim-tok', organisation=self.A)
        self.ids['gitlabproject'] = gp.id
        key = OrganisationAPIKey.objects.create(organisation=self.A, provider=AIModelProvider.objects.create(name='vp', display_name='VP'))
        self.ids['apikey_provider'] = key.provider.id

    def run_probe(self, cases):
        c = APIClient(); c.force_authenticate(user=self.ba)
        leaks = []
        for method, path in cases:
            r = getattr(c, method.lower())(path, {}, format='json')
            # Any 2xx means org B touched org A's object.
            if 200 <= r.status_code < 300:
                leaks.append(f'{method} {path} -> {r.status_code}')
        self.assertEqual(leaks, [], f'cross-org leaks: {leaks}')

    def test_probe(self):
        i = self.ids
        with mock.patch('providers.views.requests'):
            self.run_probe([
                ('GET', f"/api/projects/{i['project']}/"),
                ('PUT', f"/api/projects/{i['project']}/"),
                ('DELETE', f"/api/projects/{i['project']}/"),
                ('GET', f"/api/projects/{i['project']}/services/"),
                ('GET', f"/api/projects/services/{i['service']}/"),
                ('PUT', f"/api/projects/services/{i['service']}/"),
                ('DELETE', f"/api/projects/services/{i['service']}/"),
                ('GET', f"/api/data/investigations/{i['investigation']}/"),
                ('GET', f"/api/data/issues/{i['issue']}/similar/"),
                ('POST', f"/api/data/issues/{i['issue']}/resolve/"),
                ('POST', f"/api/data/batches/{i['batch_id']}/postmortem/"),
                ('POST', f"/api/data/batches/{i['batch_id']}/promote-analysis/"),
                ('GET', f"/api/data/batches/{i['batch_id']}/"),
                ('GET', f"/api/notification/{i['notification']}/"),
                ('DELETE', f"/api/notification/{i['notification']}/"),
                ('GET', f"/api/notification/subscriptions/{i['subscription']}/"),
                ('DELETE', f"/api/notification/subscriptions/{i['subscription']}/"),
                ('GET', f"/api/notification/escalation-rules/{i['escalation']}/"),
                ('PUT', f"/api/notification/escalation-rules/{i['escalation']}/"),
                ('DELETE', f"/api/notification/escalation-rules/{i['escalation']}/"),
                ('POST', f"/api/notification/issues/{i['issue']}/acknowledge/"),
                ('DELETE', f"/api/organisation/delete/{self.A.id}/"),
                ('PUT', f"/api/organisation/update/{self.A.id}/"),
                ('GET', f"/api/organisation/member/{self.member_a.id}/"),
                ('PUT', f"/api/organisation/member/{self.member_a.id}/"),
                ('DELETE', f"/api/organisation/member/{self.member_a.id}/"),
                ('DELETE', f"/api/providers/{i['gitlabproject']}/"),
                ('DELETE', f"/api/settings/api-keys/{i['apikey_provider']}/"),
            ])
