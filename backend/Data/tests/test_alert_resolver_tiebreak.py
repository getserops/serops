"""Tests for the resolver wiring-score tiebreak (PR-AUDIT5, RCA audit
finding #5).

When two projects share a service name (and possibly an environment
name), the resolver should prefer the one with more integration
wiring — a production project with an active SCMBinding + CICDBinding
is a stronger match than an empty audit / seed shell.
"""

from __future__ import annotations

from django.test import TestCase

from Data.models import AlertEvent
from Data.tasks import _project_wiring_score, _resolve_alert_project
from Organisations.models import Organisations
from Projects.models import (
    CICDBinding,
    Project,
    ProjectEnvironment,
    ProjectService,
    SCMBinding,
)
from providers.models import ProviderIntegration


class WiringScoreTest(TestCase):

    def setUp(self):
        self.org = Organisations.objects.create(name='TiebreakOrg')
        self.provider_integration = ProviderIntegration.objects.create(
            organisation=self.org,
            name='tiebreak-github',
            provider_type='github',
            category='devops',
        )

    def _make_project_with_wiring(
        self,
        name: str,
        with_scm: bool = False,
        with_cicd: bool = False,
    ) -> Project:
        project = Project.objects.create(organisation=self.org, name=name)
        service = ProjectService.objects.create(
            project=project, name='checkout', status='Active',
        )
        if with_scm:
            SCMBinding.objects.create(
                project_service=service,
                integration=self.provider_integration,
                repository_id='42',
            )
        if with_cicd:
            CICDBinding.objects.create(
                project_service=service,
                integration=self.provider_integration,
                binding_type='deploy',
                pipeline_id='job-1',
                pipeline_name='deploy-checkout',
            )
        return project

    def test_bare_project_scores_lowest(self):
        p = self._make_project_with_wiring('bare')
        # active service alone = 1
        self.assertEqual(_project_wiring_score(p), 1)

    def test_scm_alone_scores_higher(self):
        p = self._make_project_with_wiring('scm-only', with_scm=True)
        # +2 SCM +1 active
        self.assertEqual(_project_wiring_score(p), 3)

    def test_scm_plus_cicd_scores_highest(self):
        p = self._make_project_with_wiring('full', with_scm=True, with_cicd=True)
        # +2 SCM +2 CI/CD +1 active
        self.assertEqual(_project_wiring_score(p), 5)


class ResolverTiebreakTest(TestCase):

    def setUp(self):
        self.org = Organisations.objects.create(name='TiebreakOrg2')
        self.provider_integration = ProviderIntegration.objects.create(
            organisation=self.org,
            name='tiebreak-github',
            provider_type='github',
            category='devops',
        )

    def _wire(self, name, with_scm=False, with_cicd=False):
        project = Project.objects.create(organisation=self.org, name=name)
        service = ProjectService.objects.create(
            project=project, name='gateway', status='Active',
        )
        ProjectEnvironment.objects.create(
            project=project, name='production', is_active=True,
        )
        if with_scm:
            SCMBinding.objects.create(
                project_service=service,
                integration=self.provider_integration,
                repository_id='r',
            )
        if with_cicd:
            CICDBinding.objects.create(
                project_service=service,
                integration=self.provider_integration,
                binding_type='deploy',
                pipeline_id='p',
                pipeline_name='pipe',
            )
        return project

    def _alert(self, service='gateway', env='production'):
        return AlertEvent.objects.create(
            organisation=self.org,
            source='alertmanager',
            alertname='HighErrorRate',
            state='firing',
            service=service,
            environment=env,
        )

    def test_better_wired_project_wins_service_plus_env_match(self):
        # empty first, wired second — pre-fix ambiguity resolver would
        # have picked lowest-id (the empty one). Post-fix picks by wiring.
        empty = self._wire('empty-shell', with_scm=False, with_cicd=False)
        wired = self._wire('real-prod', with_scm=True, with_cicd=True)
        # Verify both exist and both match on service+env
        self.assertLess(empty.id, wired.id)
        picked = _resolve_alert_project(self._alert())
        self.assertEqual(picked.id, wired.id,
                         'better-wired project must win the tiebreak')

    def test_id_tiebreak_when_wiring_equal(self):
        # Same wiring → lowest id wins (stable + auditable).
        p1 = self._wire('p1', with_scm=True)
        p2 = self._wire('p2', with_scm=True)
        picked = _resolve_alert_project(self._alert())
        self.assertEqual(picked.id, min(p1.id, p2.id))

    def test_single_match_no_tiebreak_needed(self):
        only = self._wire('the-only-one')
        picked = _resolve_alert_project(self._alert())
        self.assertEqual(picked.id, only.id)
