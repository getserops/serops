"""
Smart Features Services for SCM/CI-CD Integration

Contains:
- AutoLinkService: Automatically detect and suggest CI/CD bindings for SCM repos
- IntegrationHealthService: Monitor health of provider integrations
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Any
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

# Providers that support both SCM and CI/CD
UNIFIED_PROVIDERS = ['gitlab', 'github', 'azure_devops', 'bitbucket']

# Maximum integrations to check per stale-check run
_STALE_CHECK_BATCH_SIZE = 100

# Thread pool size for parallel health checks
_HEALTH_CHECK_WORKERS = 5


class AutoLinkService:
    """
    Automatically detect and suggest CI/CD bindings for SCM repositories.

    When a user creates an SCMBinding, this service:
    1. Checks if the provider supports integrated CI/CD
    2. Queries for pipelines/workflows in the same repository
    3. Returns suggestions for CICDBinding creation

    Usage:
        service = AutoLinkService(scm_binding)
        suggestions = service.get_cicd_suggestions()
    """

    def __init__(self, scm_binding):
        self.scm_binding = scm_binding
        self.integration = scm_binding.integration
        self.provider_type = self.integration.provider_type

    def can_auto_link(self) -> bool:
        """Check if this SCM can be auto-linked to CI/CD."""
        return self.provider_type in UNIFIED_PROVIDERS

    def get_cicd_suggestions(self) -> List[Dict[str, Any]]:
        """Get suggested CI/CD bindings for this SCM."""
        if not self.can_auto_link():
            logger.debug("Provider %s does not support auto-linking", self.provider_type)
            return []

        try:
            provider = self.scm_binding.get_provider()
            dispatch = {
                'gitlab': self._detect_gitlab_pipelines,
                'github': self._detect_github_actions,
                'azure_devops': self._detect_azure_pipelines,
                'bitbucket': self._detect_bitbucket_pipelines,
            }
            handler = dispatch.get(self.provider_type)
            return handler(provider) if handler else []
        except Exception as e:
            logger.exception("Auto-link detection failed: %s", e)
            return []

    # ── Provider-specific detection ──────────────────────────────

    def _detect_gitlab_pipelines(self, provider) -> List[Dict[str, Any]]:
        """Detect GitLab CI pipelines in the repository."""
        suggestions = []
        try:
            project_id = self.scm_binding.repository_id
            url = f"{provider.base_url}/api/v4/projects/{project_id}/pipelines"
            response = provider._make_request(
                "GET", url, headers=provider._get_headers(), params={'per_page': 5}
            )
            if response.status_code == 200:
                pipelines = response.json()
                if pipelines:
                    suggestions.append({
                        'type': 'build',
                        'name': 'GitLab CI',
                        'pipeline_id': str(project_id),
                        'pipeline_name': f"{self.scm_binding.repository_name} CI/CD",
                        'pipeline_url': f"{self.scm_binding.repository_url}/-/pipelines",
                        'provider': 'gitlab',
                        'detected_from': 'recent_pipelines',
                        'last_run': pipelines[0].get('updated_at') if pipelines else None,
                        'last_status': pipelines[0].get('status') if pipelines else None,
                        'total_pipelines': len(pipelines),
                    })
        except Exception as e:
            logger.warning("Failed to detect GitLab pipelines: %s", e)
        return suggestions

    def _detect_github_actions(self, provider) -> List[Dict[str, Any]]:
        """Detect GitHub Actions workflows in the repository."""
        suggestions = []
        try:
            repo = self.scm_binding.repository_id
            url = f"{provider.base_url}/repos/{repo}/actions/workflows"
            response = provider._make_request("GET", url, headers=provider._get_headers())
            if response.status_code == 200:
                data = response.json()
                for workflow in data.get('workflows', []):
                    if workflow.get('state') == 'active':
                        suggestions.append({
                            'type': 'build',
                            'name': workflow.get('name', 'GitHub Action'),
                            'pipeline_id': str(workflow.get('id')),
                            'pipeline_name': workflow.get('name'),
                            'pipeline_url': workflow.get('html_url'),
                            'provider': 'github',
                            'detected_from': 'workflow_file',
                            'workflow_path': workflow.get('path'),
                        })
        except Exception as e:
            logger.warning("Failed to detect GitHub Actions: %s", e)
        return suggestions

    def _detect_azure_pipelines(self, provider) -> List[Dict[str, Any]]:
        """Detect Azure Pipelines in the project."""
        suggestions = []
        try:
            url = (
                f"{provider.base_url}/{provider.organization}"
                f"/{provider.project}/_apis/pipelines"
            )
            response = provider._make_request(
                "GET", url, headers=provider._get_headers(),
                params={'api-version': '7.1'},
            )
            if response.status_code == 200:
                for pipeline in response.json().get('value', []):
                    suggestions.append({
                        'type': 'build',
                        'name': pipeline.get('name', 'Azure Pipeline'),
                        'pipeline_id': str(pipeline.get('id')),
                        'pipeline_name': pipeline.get('name'),
                        'pipeline_url': pipeline.get('_links', {}).get('web', {}).get('href', ''),
                        'provider': 'azure_devops',
                        'detected_from': 'project_pipelines',
                        'folder': pipeline.get('folder'),
                    })
        except Exception as e:
            logger.warning("Failed to detect Azure Pipelines: %s", e)
        return suggestions

    def _detect_bitbucket_pipelines(self, provider) -> List[Dict[str, Any]]:
        """Detect Bitbucket Pipelines in the repository."""
        suggestions = []
        try:
            repo = self.scm_binding.repository_id
            url = f"{provider.base_url}/repositories/{repo}/pipelines/"
            response = provider._make_request(
                "GET", url, headers=provider._get_headers(), params={'pagelen': 5}
            )
            if response.status_code == 200:
                pipelines = response.json().get('values', [])
                if pipelines:
                    suggestions.append({
                        'type': 'build',
                        'name': 'Bitbucket Pipelines',
                        'pipeline_id': repo,
                        'pipeline_name': f"{self.scm_binding.repository_name} Pipelines",
                        'pipeline_url': f"https://bitbucket.org/{repo}/pipelines",
                        'provider': 'bitbucket',
                        'detected_from': 'recent_pipelines',
                        'last_run': pipelines[0].get('created_on') if pipelines else None,
                        'last_status': (
                            pipelines[0].get('state', {}).get('name')
                            if pipelines else None
                        ),
                    })
        except Exception as e:
            logger.warning("Failed to detect Bitbucket Pipelines: %s", e)
        return suggestions

    def create_suggested_bindings(self, suggestions, project_service):
        """
        Create CICDBinding instances from suggestions.

        Args:
            suggestions: List of suggestion dicts from get_cicd_suggestions()
            project_service: ProjectService to bind to

        Returns:
            List of created CICDBinding instances
        """
        from Projects.models import CICDBinding

        created = []
        for suggestion in suggestions:
            binding, was_created = CICDBinding.objects.get_or_create(
                project_service=project_service,
                integration=self.integration,
                pipeline_id=suggestion['pipeline_id'],
                defaults={
                    'binding_type': suggestion.get('type', 'build'),
                    'pipeline_name': suggestion.get('pipeline_name', ''),
                    'pipeline_url': suggestion.get('pipeline_url', ''),
                    'auto_trigger': True,
                },
            )
            if was_created:
                created.append(binding)
                logger.info("Auto-created CICDBinding: %s", binding)
        return created


class IntegrationHealthService:
    """
    Monitor health of provider integrations.

    Periodically verifies connections and tracks health status.

    Usage:
        # Check single integration
        service = IntegrationHealthService(integration)
        health = service.check_health()

        # Check all integrations for an org (parallel)
        results = IntegrationHealthService.check_all_for_org(organisation)
    """

    def __init__(self, integration):
        self.integration = integration

    def check_health(self) -> Dict[str, Any]:
        """
        Check health of the integration.

        Returns:
            Dict with health status, latency, and any errors.
        """
        from datetime import datetime

        start_time = datetime.now()
        result = {
            'integration_id': self.integration.id,
            'provider_type': self.integration.provider_type,
            'name': self.integration.name,
            'checked_at': timezone.now().isoformat(),
            'healthy': False,
            'latency_ms': None,
            'error': None,
            'details': None,
        }

        try:
            from providers.scm_providers import (
                get_provider, get_cicd_provider,
                SCMProviderError, CICD_PROVIDERS,
            )

            if self.integration.provider_type in CICD_PROVIDERS:
                creds = self.integration.get_credentials()
                provider = get_cicd_provider(
                    provider_name=self.integration.provider_type,
                    base_url=self.integration.base_url or '',
                    username=creds.get('username', ''),
                    api_token=self.integration.get_access_token(),
                )
            else:
                provider = get_provider(
                    provider_name=self.integration.provider_type,
                    project_id='',
                    access_token=self.integration.get_access_token(),
                    base_url=self.integration.base_url,
                )

            details = provider.verify_connection()
            latency = (datetime.now() - start_time).total_seconds() * 1000

            result['healthy'] = True
            result['latency_ms'] = round(latency, 2)
            result['details'] = details
            self.integration.mark_verified(success=True)

        except SCMProviderError as e:
            result['error'] = str(e)
            self.integration.mark_verified(success=False, error=str(e))
        except Exception as e:
            logger.exception("Health check failed: %s", e)
            result['error'] = f"Unexpected error: {str(e)}"
            self.integration.mark_verified(success=False, error=str(e))

        return result

    # ── Parallel / batch health checks ───────────────────────────

    @classmethod
    def check_all_for_org(cls, organisation) -> List[Dict[str, Any]]:
        """
        Check health of all active integrations for an organisation **in parallel**.

        Uses a thread pool to fan out external API calls so that N integrations
        complete in ~max(latency) time instead of sum(latency).
        """
        from providers.models import ProviderIntegration

        integrations = list(
            ProviderIntegration.objects.filter(
                organisation=organisation,
                is_active=True,
            )
        )
        if not integrations:
            return []

        return cls._check_parallel(integrations)

    @classmethod
    def check_stale_integrations(cls, hours: int = 24) -> List[Dict[str, Any]]:
        """
        Check integrations that haven't been verified recently.

        Bounded to ``_STALE_CHECK_BATCH_SIZE`` per run to avoid
        overwhelming external APIs.

        Args:
            hours: Number of hours since last verification.
        """
        from providers.models import ProviderIntegration

        stale_threshold = timezone.now() - timedelta(hours=hours)

        stale_qs = ProviderIntegration.objects.filter(
            is_active=True,
        ).filter(
            # Never verified OR verified long ago
            last_verified_at__lt=stale_threshold,
        ) | ProviderIntegration.objects.filter(
            is_active=True,
            last_verified_at__isnull=True,
        )

        integrations = list(
            stale_qs
            .order_by('last_verified_at')[:_STALE_CHECK_BATCH_SIZE]
        )

        results = cls._check_parallel(integrations)
        logger.info("Checked %d stale integrations", len(results))
        return results

    # ── Internal helpers ─────────────────────────────────────────

    @classmethod
    def _check_parallel(cls, integrations) -> List[Dict[str, Any]]:
        """Run health checks in parallel using a thread pool."""
        results: List[Dict[str, Any]] = []

        def _check_one(integration):
            return cls(integration).check_health()

        workers = min(len(integrations), _HEALTH_CHECK_WORKERS)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_check_one, integ): integ
                for integ in integrations
            }
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as exc:
                    integ = futures[future]
                    logger.error(
                        "Health check thread failed for %s: %s",
                        integ.name, exc,
                    )
                    results.append({
                        'integration_id': integ.id,
                        'provider_type': integ.provider_type,
                        'name': integ.name,
                        'checked_at': timezone.now().isoformat(),
                        'healthy': False,
                        'latency_ms': None,
                        'error': str(exc),
                        'details': None,
                    })

        return results
