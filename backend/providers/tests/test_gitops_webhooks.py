"""Tests for ArgoCD + Flux native webhook translators (Items #15 + #16).

Both handlers subclass ``GenericDeploymentWebhookHandler`` so the
auth / HMAC / rate-limit / persistence paths are already covered by
``test_deployment_webhook.py``. These tests focus on the payload
translation layer that turns vendor-native shapes into the canonical
``{commit_sha, environment, ...}`` dict.
"""

from django.test import TestCase

from Organisations.models import Organisations
from Projects.models import CICDBinding, Project, ProjectService
from providers.models import Deployment, ProviderIntegration
from providers.tests.signing_client import SigningAPIClient


class GitopsWebhookBase(TestCase):

    def setUp(self):
        self.org = Organisations.objects.create(name='GitopsOrg')
        self.project = Project.objects.create(name='gops-proj', organisation=self.org)
        self.service = ProjectService.objects.create(
            project=self.project, name='api', service_type='application',
        )
        self.integration = ProviderIntegration.objects.create(
            organisation=self.org, provider_type='github', name='gh-int',
        )
        self.binding = CICDBinding.objects.create(
            project_service=self.service, integration=self.integration,
            binding_type='deploy', is_active=True, webhook_secret='gitops-secret',
        )
        self.client = SigningAPIClient('gitops-secret')


# ============================================================================
# ArgoCD
# ============================================================================


class ArgoCDWebhookTest(GitopsWebhookBase):

    def _url(self):
        return f'/api/providers/webhook/argocd/{self.binding.id}/'

    def _payload(self, **overrides):
        base = {
            'app': {
                'metadata': {
                    'name': 'checkout',
                    'namespace': 'production',
                },
                'spec': {'source': {'targetRevision': 'main'}},
                'status': {
                    'sync': {
                        'status': 'Synced',
                        'revision': 'abc123def456789',
                    },
                    'health': {'status': 'Healthy'},
                    'operationState': {
                        'phase': 'Succeeded',
                        'finishedAt': '2026-10-25T14:25:00Z',
                        'operation': {'initiatedBy': {'username': 'gitops-bot'}},
                    },
                },
            },
        }
        # Deep-merge overrides.
        for k, v in overrides.items():
            base[k] = v
        return base

    def test_successful_sync_creates_deployment(self):
        response = self.client.post(self._url(), self._payload(), format='json')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['commit_sha'], 'abc123def456789')
        self.assertEqual(body['environment'], 'production')
        self.assertEqual(Deployment.objects.count(), 1)
        dep = Deployment.objects.get()
        self.assertEqual(dep.deployed_by, 'gitops-bot')
        # Notes surface the argocd app name so the AI prompt has context.
        self.assertIn('argocd-app=checkout', dep.notes)

    def test_failed_operation_is_recorded_as_a_failed_deployment(self):
        """A rejected sync is a change that did not land; the analysis must
        see it (client C4 P6, Argo CD equivalent)."""
        payload = self._payload()
        payload['app']['status']['operationState']['phase'] = 'Failed'
        payload['app']['status']['operationState']['message'] = 'one or more objects failed to apply'
        response = self.client.post(self._url(), payload, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'failed')
        dep = Deployment.objects.get()
        self.assertEqual(dep.status, 'failed')
        self.assertIn('failed (Failed): one or more objects failed to apply', dep.notes)

    def test_running_operation_is_ignored_with_200(self):
        payload = self._payload()
        payload['app']['status']['operationState']['phase'] = 'Running'
        response = self.client.post(self._url(), payload, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ignored'])
        self.assertEqual(Deployment.objects.count(), 0)

    def test_out_of_sync_without_an_operation_is_ignored(self):
        payload = self._payload()
        payload['app']['status']['sync']['status'] = 'OutOfSync'
        del payload['app']['status']['operationState']
        response = self.client.post(self._url(), payload, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ignored'])
        self.assertEqual(Deployment.objects.count(), 0)

    def test_failed_then_succeeded_sync_of_one_revision_records_both(self):
        payload = self._payload()
        payload['app']['status']['operationState']['phase'] = 'Failed'
        self.client.post(self._url(), payload, format='json')
        payload = self._payload()
        payload['app']['status']['operationState']['finishedAt'] = '2026-10-25T14:35:00Z'
        response = self.client.post(self._url(), payload, format='json')
        self.assertEqual(response.json()['status'], 'success')
        self.assertEqual(sorted(Deployment.objects.values_list('status', flat=True)), ['failed', 'success'])

    def test_succeeded_sync_counts_even_if_already_out_of_sync(self):
        """Argo CD 2.13 renders the notification after the sync; the app can
        already read OutOfSync, and with oncePer the revision is never sent
        again (journey suite). The operation's own revision is recorded."""
        payload = self._payload()
        payload['app']['status']['sync'] = {'status': 'OutOfSync', 'revision': 'abc123def456789'}
        payload['app']['status']['operationState']['syncResult'] = {'revision': 'fedcba987654321'}
        response = self.client.post(self._url(), payload, format='json')
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(Deployment.objects.get().code_change.commit_sha, 'fedcba987654321')

    def test_missing_revision_400(self):
        payload = self._payload()
        payload['app']['status']['sync']['revision'] = ''
        response = self.client.post(self._url(), payload, format='json')
        self.assertEqual(response.status_code, 400)

    def test_missing_app_object_400(self):
        response = self.client.post(self._url(), {'foo': 'bar'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_env_from_annotation_wins_over_namespace(self):
        payload = self._payload()
        payload['app']['metadata']['annotations'] = {
            'serops.io/environment': 'staging',
        }
        payload['app']['metadata']['namespace'] = 'production'   # would win otherwise
        response = self.client.post(self._url(), payload, format='json')
        self.assertEqual(response.json()['environment'], 'staging')

    def test_env_alias_prod_maps_to_production(self):
        payload = self._payload()
        payload['app']['metadata']['namespace'] = 'prod'
        response = self.client.post(self._url(), payload, format='json')
        self.assertEqual(response.json()['environment'], 'production')

    def test_env_unknown_namespace_falls_back_to_production(self):
        payload = self._payload()
        payload['app']['metadata']['namespace'] = 'weird-team-namespace'
        response = self.client.post(self._url(), payload, format='json')
        self.assertEqual(response.json()['environment'], 'production')

    def test_env_from_destination_namespace_not_argocd_namespace(self):
        """SC-09: the Application lives in ``argocd``; it deploys to ``staging``."""
        payload = self._payload()
        payload['app']['metadata'] = {'name': 'payments', 'namespace': 'argocd'}
        payload['app']['spec']['destination'] = {'namespace': 'staging', 'server': 'https://kubernetes.default.svc'}
        response = self.client.post(self._url(), payload, format='json')
        self.assertEqual(response.json()['environment'], 'staging')
        self.assertNotIn('assumed-production', Deployment.objects.get().notes)

    def test_env_from_app_name_suffix(self):
        payload = self._payload()
        payload['app']['metadata'] = {'name': 'payments-staging', 'namespace': 'argocd'}
        payload['app']['spec']['destination'] = {'namespace': 'payments'}
        response = self.client.post(self._url(), payload, format='json')
        self.assertEqual(response.json()['environment'], 'staging')

    def test_env_from_destination_namespace_prefix(self):
        payload = self._payload()
        payload['app']['metadata'] = {'name': 'payments', 'namespace': 'argocd'}
        payload['app']['spec']['destination'] = {'namespace': 'dev-payments'}
        response = self.client.post(self._url(), payload, format='json')
        self.assertEqual(response.json()['environment'], 'development')

    def test_destination_wins_over_app_namespace(self):
        payload = self._payload()
        payload['app']['metadata'] = {'name': 'checkout', 'namespace': 'production'}
        payload['app']['spec']['destination'] = {'namespace': 'staging'}
        response = self.client.post(self._url(), payload, format='json')
        self.assertEqual(response.json()['environment'], 'staging')

    def test_unresolved_environment_is_flagged(self):
        payload = self._payload()
        payload['app']['metadata'] = {'name': 'payments', 'namespace': 'argocd'}
        payload['app']['spec']['destination'] = {'namespace': 'payments'}
        response = self.client.post(self._url(), payload, format='json')
        self.assertEqual(response.json()['environment'], 'production')
        self.assertIn('environment=assumed-production', Deployment.objects.get().notes)

    def test_multi_source_application_records_the_git_revision(self):
        """C2: Helm chart + values repo; the revision is in ``revisions[]``."""
        sha = 'a1b2c3d4e5f60718293a4b5c6d7e8f9012345678'
        payload = self._payload()
        payload['app']['status']['sync'] = {'status': 'Synced', 'revisions': ['1.4.0', sha]}
        payload['app']['status']['operationState']['syncResult'] = {'revisions': ['1.4.0', sha]}
        response = self.client.post(self._url(), payload, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['commit_sha'], sha)

    def test_multi_source_with_only_chart_versions_is_rejected(self):
        payload = self._payload()
        payload['app']['status']['sync'] = {'status': 'Synced', 'revisions': ['1.4.0', '2.0.1']}
        response = self.client.post(self._url(), payload, format='json')
        self.assertEqual(response.status_code, 400)

    def test_no_operation_state_still_records(self):
        """Some ArgoCD event templates omit operationState (health-only
        transitions). If sync is Synced and no phase is set, accept it."""
        payload = self._payload()
        payload['app']['status'].pop('operationState')
        response = self.client.post(self._url(), payload, format='json')
        self.assertEqual(response.status_code, 200)

    def test_actor_defaults_to_argocd(self):
        payload = self._payload()
        payload['app']['status']['operationState']['operation'] = {}
        response = self.client.post(self._url(), payload, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Deployment.objects.get().deployed_by, 'argocd')


# ============================================================================
# Flux
# ============================================================================


class FluxWebhookTest(GitopsWebhookBase):

    def _url(self):
        return f'/api/providers/webhook/flux/{self.binding.id}/'

    def _payload(self, **overrides):
        base = {
            'involvedObject': {
                'kind': 'Kustomization',
                'name': 'checkout',
                'namespace': 'production',
            },
            'severity': 'info',
            'reason': 'Progressing',
            'message': 'Deployment/production/checkout configured\nService/production/checkout unchanged',
            'metadata': {'revision': 'main@sha1:abc123def456789'},
            'timestamp': '2026-10-25T14:25:00Z',
            'reportingController': 'kustomize-controller',
        }
        base.update(overrides)
        return base

    def test_successful_reconciliation_creates_deployment(self):
        response = self.client.post(self._url(), self._payload(), format='json')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['commit_sha'], 'abc123def456789')
        self.assertEqual(body['environment'], 'production')
        dep = Deployment.objects.get()
        self.assertEqual(dep.deployed_by, 'kustomize-controller')
        self.assertIn('flux-kustomization=checkout', dep.notes)

    def test_repeated_reconcile_events_record_one_deployment(self):
        """Flux sends an info event on every reconcile; one revision is one deploy."""
        for _ in range(3):
            r = self.client.post(self._url(), self._payload(), format='json')
            self.assertEqual(r.status_code, 200)
        self.assertEqual(Deployment.objects.count(), 1)
        self.assertTrue(r.json().get('deduplicated'))

    def test_new_revision_and_rollback_are_recorded(self):
        self.client.post(self._url(), self._payload(), format='json')
        self.client.post(self._url(), self._payload(metadata={'revision': 'main@sha1:fff999eee888777'}), format='json')
        # Roll back to the first revision: a real deployment again.
        self.client.post(self._url(), self._payload(timestamp='2026-10-25T14:40:00Z'), format='json')
        self.assertEqual(Deployment.objects.count(), 3)

    def test_failed_apply_is_recorded_as_a_failed_deployment(self):
        """Client C4 P6: "dry-run failed (Invalid)" was answered 400 and
        recorded nowhere; the analysis never knew the change was rejected."""
        response = self.client.post(self._url(), self._payload(
            severity='error', reason='ReconciliationFailed',
            message='Deployment/production/checkout dry-run failed (Invalid): spec.template.spec.containers[0]'
                    '.resources.requests: Invalid value: "30m": must be less than or equal to cpu limit',
        ), format='json')
        self.assertEqual(response.status_code, 200)
        dep = Deployment.objects.get()
        self.assertEqual(dep.status, 'failed')
        self.assertIn('failed (ReconciliationFailed): Deployment/production/checkout dry-run failed', dep.notes)

    def test_repeated_failed_apply_records_one_failure(self):
        for _ in range(3):
            self.client.post(self._url(), self._payload(severity='error', reason='ReconciliationFailed',
                                                         message='dry-run failed'), format='json')
        self.assertEqual(Deployment.objects.count(), 1)

    def test_failed_then_fixed_apply_of_one_revision_records_both(self):
        self.client.post(self._url(), self._payload(severity='error', reason='ReconciliationFailed',
                                                     message='dry-run failed'), format='json')
        r = self.client.post(self._url(), self._payload(timestamp='2026-10-25T14:30:00Z'), format='json')
        self.assertEqual(r.json()['status'], 'success')
        self.assertEqual(Deployment.objects.count(), 2)

    def test_unchanged_reconcile_is_ignored_with_200(self):
        """Client C4 P3: every Kustomization of a monorepo reports the new
        revision on any commit; only the one whose apply changed objects
        deployed anything."""
        response = self.client.post(self._url(), self._payload(
            reason='ReconciliationSucceeded',
            message='Reconciliation finished in 2.1s, next run in 10m0s',
            metadata={'revision': 'main@sha1:fff999eee888777'},
        ), format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ignored'])
        self.assertEqual(Deployment.objects.count(), 0)

    def test_monorepo_commit_records_only_the_changed_kustomization(self):
        unchanged = self._payload(reason='ReconciliationSucceeded',
                                  message='Reconciliation finished in 1.2s, next run in 10m0s')
        changed = self._payload()   # "Deployment/production/checkout configured"
        self.client.post(self._url(), unchanged, format='json')
        self.client.post(self._url(), changed, format='json')
        self.client.post(self._url(), unchanged, format='json')
        self.assertEqual(Deployment.objects.count(), 1)

    def test_cluster_scoped_and_created_objects_count_as_changes(self):
        response = self.client.post(self._url(), self._payload(
            message='Namespace/payments created\nClusterRole/payments-reader configured'), format='json')
        self.assertEqual(response.json().get('status'), 'success')

    def test_info_notices_are_ignored_with_200(self):
        """Client C4 P4: DependencyNotReady / Progressing got 400 and Flux logged
        "failed to send notification" on every reconcile."""
        for reason, message in (('DependencyNotReady', "dependency 'flux-system/infra' is not ready"),
                                ('Progressing', 'Reconciliation in progress'),
                                ('HealthCheckPassed', 'Health check passed in 2s')):
            r = self.client.post(self._url(), self._payload(reason=reason, message=message), format='json')
            self.assertEqual(r.status_code, 200, reason)
            self.assertTrue(r.json()['ignored'], reason)
        self.assertEqual(Deployment.objects.count(), 0)

    def test_helmrelease_upgrade_is_a_deploy_from_origin_revision(self):
        sha = 'b' * 40
        response = self.client.post(self._url(), self._payload(
            involvedObject={'kind': 'HelmRelease', 'name': 'payments', 'namespace': 'production'},
            reason='UpgradeSucceeded', reportingController='helm-controller',
            message='Helm upgrade succeeded for release production/payments.v4 with chart payments@1.4.2',
            metadata={'revision': '1.4.2', 'originRevision': f'main@sha1:{sha}'},
        ), format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['commit_sha'], sha)
        self.assertIn('flux-helmrelease=payments', Deployment.objects.get().notes)

    def test_helmrelease_from_a_chart_repository_is_ignored(self):
        response = self.client.post(self._url(), self._payload(
            involvedObject={'kind': 'HelmRelease', 'name': 'payments', 'namespace': 'production'},
            reason='UpgradeSucceeded', message='Helm upgrade succeeded', metadata={'revision': '1.4.2'},
        ), format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ignored'])

    def test_revision_without_sha_is_ignored(self):
        response = self.client.post(
            self._url(),
            self._payload(metadata={'revision': 'main@sha1:'}),
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ignored'])

    def test_revision_with_sha256_algo(self):
        """Newer Flux builds use sha256 prefix — must still parse."""
        response = self.client.post(
            self._url(),
            self._payload(metadata={'revision': 'main@sha256:abc123def456789'}),
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['commit_sha'], 'abc123def456789')

    def test_env_from_namespace(self):
        response = self.client.post(
            self._url(),
            self._payload(involvedObject={
                'kind': 'Kustomization', 'name': 'x', 'namespace': 'staging',
            }),
            format='json',
        )
        self.assertEqual(response.json()['environment'], 'staging')

    def test_env_from_kustomization_name_in_flux_system(self):
        """SC-09: involvedObject.namespace is ``flux-system``, not an environment."""
        response = self.client.post(
            self._url(),
            self._payload(involvedObject={
                'kind': 'Kustomization', 'name': 'apps-staging', 'namespace': 'flux-system',
            }),
            format='json',
        )
        self.assertEqual(response.json()['environment'], 'staging')

    def test_flux_unresolved_environment_is_flagged(self):
        response = self.client.post(
            self._url(),
            self._payload(involvedObject={
                'kind': 'Kustomization', 'name': 'apps', 'namespace': 'flux-system',
            }),
            format='json',
        )
        self.assertEqual(response.json()['environment'], 'production')
        self.assertIn('environment=assumed-production', Deployment.objects.get().notes)

    def test_env_alias_dev_maps_to_development(self):
        response = self.client.post(
            self._url(),
            self._payload(involvedObject={
                'kind': 'Kustomization', 'name': 'x', 'namespace': 'dev',
            }),
            format='json',
        )
        self.assertEqual(response.json()['environment'], 'development')

    def test_missing_metadata_is_ignored(self):
        response = self.client.post(
            self._url(),
            self._payload(metadata={}),
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ignored'])
        self.assertEqual(Deployment.objects.count(), 0)


class FluxGenericHmacSignatureTest(GitopsWebhookBase):
    """Flux's generic-hmac provider sends X-Signature, not X-SerOps-Signature."""

    def test_x_signature_header_accepted(self):
        import hashlib
        import hmac
        import json
        body = json.dumps({
            'involvedObject': {'kind': 'Kustomization', 'name': 'api', 'namespace': 'flux-system'},
            'severity': 'info', 'reason': 'ReconciliationSucceeded',
            'metadata': {'revision': 'main@sha1:' + 'a' * 40}, 'message': 'Deployment/flux-system/api configured',
        }).encode()
        sig = 'sha256=' + hmac.new(b'gitops-secret', body, hashlib.sha256).hexdigest()
        response = self.client.post(f'/api/providers/webhook/flux/{self.binding.id}/', data=body,
                                    content_type='application/json',
                                    HTTP_X_SEROPS_SIGNATURE='', HTTP_X_SIGNATURE=sig)
        self.assertNotEqual(response.status_code, 403, response.content)



class FailedApplyReachesTheAnalysisTest(GitopsWebhookBase):
    """The rejected apply's message reaches the code-changes section as
    "NOT deployed: … failed …" (client C4 P6)."""

    def test_failed_apply_line_in_the_prompt(self):
        from datetime import datetime, timedelta, timezone as dt_tz
        from ai_model.diff_selection import build_code_changes_section
        from providers.code_change_service import CodeChangeService
        from providers.deployment_service import DeploymentService
        r = self.client.post(f'/api/providers/webhook/flux/{self.binding.id}/', {
            'involvedObject': {'kind': 'Kustomization', 'name': 'api', 'namespace': 'production'},
            'severity': 'error', 'reason': 'ReconciliationFailed',
            'message': 'Deployment/production/api dry-run failed (Invalid): cpu request exceeds limit',
            'metadata': {'revision': 'main@sha1:' + 'c' * 40},
            'timestamp': '2026-10-25T14:25:00Z', 'reportingController': 'kustomize-controller',
        }, format='json')
        self.assertEqual(r.status_code, 200)
        at = datetime(2026, 10, 25, 14, 25, tzinfo=dt_tz.utc)
        changes = DeploymentService.get_deployments_for_batch(
            environment='production', start_time=at - timedelta(minutes=5), end_time=at + timedelta(minutes=5),
            organisation_id=self.org.id, only_successful=False)
        summaries = CodeChangeService.prepare_changes_for_ai(changes, environment='production')
        self.assertEqual(summaries[0]['pipeline_status'], 'failed')
        section = build_code_changes_section(summaries, [], redact=lambda t: t)
        self.assertIn('NOT deployed: pipeline failed', section)
        self.assertIn('dry-run failed (Invalid): cpu request exceeds limit', section)
