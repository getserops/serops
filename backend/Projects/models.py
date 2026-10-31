import logging

from django.db import models
from Organisations.models import Organisations
from providers.models import GitlabProject, ProviderIntegration, ProviderIntegration

logger = logging.getLogger(__name__)

class Project(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    organisation = models.ForeignKey(Organisations, on_delete=models.CASCADE, related_name='projects')
    es_index_name = models.CharField(max_length=255, blank=True, null=True)
    app_logs_index_name = models.CharField(max_length=255, blank=True, null=True)
    # Item #19 — optional cluster assignment. Lets the multi-cluster
    # picker filter Dashboard / Batches / Issues by cluster and lets
    # the batch pipeline route to the cluster's scoped integrations.
    # NULL = "unassigned" (project not tied to a cluster; falls back
    # to unscoped integrations). Backward-compatible with single-
    # cluster installs — no existing project needs a cluster.
    cluster = models.ForeignKey(
        'integrations.Cluster',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='projects',
        help_text='Optional K8s cluster this project runs in. '
                  'Deleting a cluster leaves the project unassigned, '
                  'not deleted.',
    )
    # Other ways this project's logs are tagged, besides project_name /
    # project = <name>: [{"field": "service.namespace", "value": "shop"}, ...].
    # A log belongs to the project when it carries the project name OR
    # matches any rule, so a rule only ever adds logs. See log_rules_clean().
    log_rules = models.JSONField(default=list, blank=True)

    MAX_LOG_RULES = 5

    def __str__(self):
        return self.name

    @staticmethod
    def clean_log_rule(field, value):
        """A (field, value) a query can carry safely, or ValueError.

        Field names are identifiers in every query language SerOps writes
        (dotted paths, Kubernetes label keys); values are quoted by each
        builder, but bounded here.
        """
        import re
        field = str(field or '').strip()
        value = str(value or '').strip()
        if not re.fullmatch(r'[A-Za-z_@][A-Za-z0-9_.@/-]{0,127}', field):
            raise ValueError('field must be a field name such as service.namespace or kubernetes.namespace')
        if not value or len(value) > 200 or any(c in value for c in '\n\r'):
            raise ValueError('value must be 1 to 200 characters on one line')
        return field, value

    def log_rules_clean(self):
        """The valid rules, as (field, value) pairs (invalid ones are skipped)."""
        out = []
        for rule in self.log_rules or []:
            try:
                pair = self.clean_log_rule(rule.get('field'), rule.get('value'))
            except (ValueError, AttributeError):
                continue
            if pair not in out:
                out.append(pair)
        return out[:self.MAX_LOG_RULES]

    class Meta:
        unique_together = ('name', 'organisation')


class ProjectService(models.Model):
    """
    Links a Project to services that emit logs.
    
    Unified Service Model (3 types only):
    - application: Code-based services (microservices, backends, frontends)
    - infrastructure: Non-code services (database, cache, queue)
    - custom: Manual entries for legacy/external systems
    
    SCM and CI/CD connections are handled via SCMBinding and CICDBinding models,
    not service_type. This allows flexible provider combinations.
    """
    SERVICE_TYPES = [
        ('application', 'Application'),
        ('infrastructure', 'Infrastructure'),
        ('custom', 'Custom'),
    ]
    
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='services')
    service_type = models.CharField(max_length=20, choices=SERVICE_TYPES, default='application')

    subtype = models.CharField(
        max_length=50, 
        blank=True, 
        default='',
        help_text='Optional subtype (e.g., database, cache, queue, backend, frontend)'
    )
    name = models.CharField(max_length=255, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, default='Active')
    
    # KEEP EXISTING - GitLab FK (backwards compatible)
    gitlab_project = models.ForeignKey(
        GitlabProject,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='project_services'
    )
    
    # NEW - Generic provider configuration
    provider_config = models.JSONField(
        default=dict,
        blank=True,
        help_text='Provider-specific configuration (repo, token_env, webhook_url, etc.)'
    )
    # Example for GitHub: {"owner": "org", "repo": "name", "webhook_secret_env": "GITHUB_SECRET"}
    # Example for Jenkins: {"job_name": "build", "jenkins_url": "https://jenkins.example.com"}
    
    webhook_configured = models.BooleanField(
        default=False,
        help_text='Whether webhook has been set up for this service'
    )

    # Global Integration Link (Scalable Architecture)
    provider_integration = models.ForeignKey(
        ProviderIntegration,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='services',
        help_text='Link to global integration credentials'
    )
    
    def __str__(self):
        """Return human-readable service name."""
        # Try to get name from SCM binding (preferred for application services)
        if hasattr(self, 'scm_binding') and self.scm_binding:
            return f"{self.scm_binding.repository_name} - {self.project.name}"
        
        # Legacy GitLab FK support (backwards compatibility)
        if self.gitlab_project:
            return f"{self.gitlab_project.name} - {self.project.name}"
        
        # Use service name or type-based fallback
        if self.name:
            return f"{self.name} - {self.project.name}"
        
        # Type-based display name
        type_display = dict(self.SERVICE_TYPES).get(self.service_type, 'Service')
        if self.subtype:
            return f"[{type_display}:{self.subtype}] - {self.project.name}"
        return f"[{type_display}] - {self.project.name}"
    
    def get_provider_display_name(self):
        """Return human-readable provider/type name."""
        # If has SCM binding, show the SCM provider
        if hasattr(self, 'scm_binding') and self.scm_binding:
            provider_names = {
                'gitlab': 'GitLab',
                'github': 'GitHub', 
                'bitbucket': 'Bitbucket',
            }
            return provider_names.get(self.scm_binding.provider_type, self.scm_binding.provider_type)
        
        # Otherwise return service type display name
        return dict(self.SERVICE_TYPES).get(self.service_type, 'Unknown')


class ProjectEnvironment(models.Model):
    """
    User-defined environments for a project.
    
    Each environment has:
    - Branch/tag patterns for deployment detection
    - Log label matching for environment filtering
    - Active/inactive status
    
    Batch creation runs separately for each active environment.
    """
    project = models.ForeignKey(
        Project, 
        on_delete=models.CASCADE, 
        related_name='environments'
    )
    name = models.CharField(
        max_length=50,
        help_text='Environment identifier (e.g., development, staging, production)'
    )
    display_name = models.CharField(
        max_length=100,
        help_text='Human-readable name (e.g., Development, Staging, Production)'
    )
    
    # Branch/tag patterns for deployment detection
    branch_patterns = models.JSONField(
        default=list,
        blank=True,
        help_text='Git branch patterns for this environment, e.g., ["develop", "feature/*"]'
    )
    tag_patterns = models.JSONField(
        default=list,
        blank=True,
        help_text='Git tag patterns for this environment, e.g., ["v*", "release-*"]'
    )
    
    # Log environment label matching
    log_label_value = models.CharField(
        max_length=100,
        blank=True,
        help_text='Value to match in log environment field'
    )
    
    is_active = models.BooleanField(
        default=True,
        help_text='Whether batch creation runs for this environment'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ('project', 'name')
        ordering = ['name']
    
    def __str__(self):
        return f"{self.project.name} / {self.display_name}"

    def log_labels(self):
        """Values of the log environment field, besides the name and its
        usual spellings, that mean this environment (comma-separated in
        ``log_label_value``)."""
        return [v.strip() for v in (self.log_label_value or '').split(',') if v.strip()]
    
    def matches_branch(self, branch_name):
        """Check if a branch matches this environment's patterns."""
        import fnmatch
        for pattern in self.branch_patterns:
            if fnmatch.fnmatch(branch_name, pattern):
                return True
        return False
    
    def matches_tag(self, tag_name):
        """Check if a tag matches this environment's patterns."""
        import fnmatch
        for pattern in self.tag_patterns:
            if fnmatch.fnmatch(tag_name, pattern):
                return True
        return False


class ProjectDeployment(models.Model):
    """The unit of "where a project runs" — one row per (env × cluster × region × namespace).

    Batch 48 (Deployment-model universal-topology rework). Replaces the
    implicit ``(project × active_env)`` batch tuple with an explicit
    deployment concept that can compose the four orthogonal dimensions
    real enterprise topologies actually use.

    Design notes:

    * ``environment`` is **nullable** — legacy projects with zero active
      envs get a single deployment with env=None so migration doesn't
      strand them. New projects always have an env.
    * ``cluster`` is nullable for VM / bare-metal / Docker-Swarm shops
      (majority case for SMB users).
    * ``region`` and ``namespace`` are free-text strings — enterprises
      use custom labels ("dc1", "primary", "dr") + K8s namespaces
      that don't fit a fixed enum. Empty string = unset.
    * ``namespace`` requires ``cluster`` — namespaces exist within a
      cluster. Enforced by CheckConstraint at the DB level so a
      client can never persist a nonsensical state.
    * ``name`` is auto-generated on save (e.g. ``prod-eks / production``)
      but user-editable. Unique per project so display lists never
      show duplicates.
    * Unique-together on (project, env, cluster, region, namespace) so
      exact-shape duplicates are impossible.

    Deploying same project to multiple clusters / regions / namespaces
    = multiple ``ProjectDeployment`` rows on ONE project row. No more
    "duplicate the project" workaround.
    """

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='deployments',
    )
    environment = models.ForeignKey(
        ProjectEnvironment,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='deployments',
        help_text='Nullable for legacy 0-env projects; new deployments always set it.',
    )
    cluster = models.ForeignKey(
        'integrations.Cluster',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='project_deployments',
        help_text='VM / bare-metal / Swarm deployments leave NULL.',
    )
    region = models.CharField(
        max_length=64, blank=True, default='',
        help_text='Free-text region label (e.g. "us-east-1", "eu-west-1", "dc1").',
    )
    namespace = models.CharField(
        max_length=128, blank=True, default='',
        help_text='K8s namespace. Requires cluster to be set.',
    )

    name = models.CharField(
        max_length=200, blank=True,
        help_text='Display name, auto-suggested from cluster/env/region on save. User-editable.',
    )
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'project_deployment'
        constraints = [
            # Exact-shape duplicates are impossible. Note (project, env)
            # can appear multiple times if cluster/region/namespace differ.
            models.UniqueConstraint(
                fields=['project', 'environment', 'cluster', 'region', 'namespace'],
                name='uniq_project_deployment_shape',
            ),
            # Display name uniqueness within a project so lists /
            # dropdowns never confuse users with duplicates.
            models.UniqueConstraint(
                fields=['project', 'name'],
                name='uniq_project_deployment_name',
            ),
            # Namespace requires cluster — expressed as: namespace empty
            # OR cluster set. Blocks (cluster=NULL, namespace='foo')
            # at the DB level (SQL: NOT (namespace <> '' AND cluster_id IS NULL)).
            models.CheckConstraint(
                check=models.Q(namespace='') | models.Q(cluster__isnull=False),
                name='namespace_requires_cluster',
            ),
        ]
        indexes = [
            models.Index(fields=['project', 'is_active'], name='deploy_proj_active_idx'),
            models.Index(fields=['cluster', 'is_active'], name='deploy_cluster_active_idx'),
        ]
        ordering = ['project', 'name']

    def __str__(self):
        return f"{self.project.name} — {self.name or 'deployment ' + str(self.pk)}"

    def suggest_name(self) -> str:
        """Build a readable display name from the deployment's dimensions.

        Order chosen to surface the most-distinguishing field first:
        cluster (usually the "physical" identity) > env > region > namespace.
        Falls back to just the env name (or "default") when nothing else is set.
        """
        parts = []
        if self.cluster_id:
            parts.append(self.cluster.name)
        if self.environment_id:
            parts.append(self.environment.name)
        if self.region:
            parts.append(self.region)
        if self.namespace:
            parts.append(f"ns={self.namespace}")
        if not parts:
            parts.append('default')
        return ' / '.join(parts)

    def save(self, *args, **kwargs):
        # Auto-populate name on create if the user didn't provide one.
        # Never overwrites a user-set name on update — respecting user
        # agency is worth the tiny complexity here.
        if not self.name:
            self.name = self.suggest_name()
        super().save(*args, **kwargs)


def create_default_environments(project):
    """
    Create default environments for a new project.
    Called during project creation if no environments specified.
    """
    defaults = [
        {
            'name': 'development',
            'display_name': 'Development',
            'branch_patterns': ['develop', 'dev', 'feature/*'],
            'tag_patterns': [],
            'log_label_value': 'development',
        },
        {
            'name': 'staging',
            'display_name': 'Staging',
            'branch_patterns': ['staging', 'release/*'],
            'tag_patterns': [],
            'log_label_value': 'staging',
        },
        {
            'name': 'production',
            'display_name': 'Production',
            'branch_patterns': ['main', 'master'],
            'tag_patterns': ['v*', 'release-*'],
            'log_label_value': 'production',
        },
    ]
    
    created = []
    for env_data in defaults:
        env, _ = ProjectEnvironment.objects.get_or_create(
            project=project,
            name=env_data['name'],
            defaults=env_data
        )
        created.append(env)
    
    return created


class SCMBinding(models.Model):
    """
    Links a ProjectService to a Source Code Management provider.
    
    Separates SCM concerns from CI/CD, enabling scenarios like:
    - GitLab SCM + Jenkins CI/CD
    - GitHub SCM + CircleCI
    - Bitbucket SCM + Azure Pipelines
    
    Each ProjectService can have ONE SCM binding (the source of truth for code).
    """
    project_service = models.OneToOneField(
        ProjectService,
        on_delete=models.CASCADE,
        related_name='scm_binding',
        help_text='The project service this SCM is bound to'
    )
    integration = models.ForeignKey(
        ProviderIntegration,
        on_delete=models.PROTECT,
        related_name='scm_bindings',
        help_text='Global integration containing credentials'
    )
    
    # Repository identification
    repository_id = models.CharField(
        max_length=255,
        help_text='Provider-specific repository ID (e.g., GitLab project ID, GitHub owner/repo)'
    )
    repository_name = models.CharField(
        max_length=255,
        blank=True,
        help_text='Human-readable repository name'
    )
    repository_url = models.URLField(
        blank=True,
        help_text='Web URL to the repository'
    )
    default_branch = models.CharField(
        max_length=100,
        default='main',
        help_text='Default branch for this repository'
    )
    
    # Webhook configuration
    webhook_id = models.CharField(
        max_length=100,
        blank=True,
        help_text='Provider webhook ID (for management)'
    )
    webhook_secret = models.CharField(
        max_length=255,
        blank=True,
        help_text='Webhook signature secret'
    )
    webhook_configured = models.BooleanField(
        default=False,
        help_text='Whether webhook is configured on the provider'
    )
    
    # Sync state
    last_sync_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Last successful sync of commits/changes'
    )
    sync_error = models.TextField(
        blank=True,
        help_text='Last sync error message if any'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'SCM Binding'
        verbose_name_plural = 'SCM Bindings'
    
    def __str__(self):
        return f"SCM: {self.repository_name or self.repository_id} ({self.integration.provider_type})"
    
    @property
    def provider_type(self):
        return self.integration.provider_type
    
    def get_provider(self):
        """Get configured provider instance for this binding."""
        from providers.scm_providers import get_provider
        return get_provider(
            provider_name=self.integration.provider_type,
            project_id=self.repository_id,
            access_token=self.integration.get_access_token(),
            base_url=self.integration.base_url,
            organization=self.integration.provider_organization(),
        )


    def save(self, *args, **kwargs):
        """Give the binding a webhook secret on creation.

        Security (2026-10-20 review): the SCM webhook receiver fails closed
        when a binding has no secret, so a binding must never exist without
        one — otherwise it would accept unauthenticated payloads. Covering
        it here means every creation path (UI, onboarding, import) is safe.
        """
        if not self.webhook_secret:
            import secrets as _secrets
            self.webhook_secret = _secrets.token_hex(32)
        super().save(*args, **kwargs)


class CICDBinding(models.Model):
    """
    Links a ProjectService to a CI/CD provider.
    
    Separates CI/CD concerns from SCM, enabling:
    - Multiple CI/CD pipelines per service (build + deploy)
    - Different providers (Jenkins for build, ArgoCD for deploy)
    - Cross-provider correlation (commits → builds)
    
    Each ProjectService can have MULTIPLE CI/CD bindings.
    """
    BINDING_TYPES = [
        ('build', 'Build Pipeline'),
        ('deploy', 'Deployment Pipeline'),
        ('test', 'Test Pipeline'),
        ('release', 'Release Pipeline'),
    ]
    
    project_service = models.ForeignKey(
        ProjectService,
        on_delete=models.CASCADE,
        related_name='cicd_bindings',
        help_text='The project service this CI/CD is bound to'
    )
    integration = models.ForeignKey(
        ProviderIntegration,
        on_delete=models.PROTECT,
        related_name='cicd_bindings',
        help_text='Global integration containing credentials'
    )
    
    binding_type = models.CharField(
        max_length=20,
        choices=BINDING_TYPES,
        default='build',
        help_text='Purpose of this CI/CD binding'
    )
    
    # Pipeline/Job identification
    pipeline_id = models.CharField(
        max_length=255,
        help_text='Provider-specific pipeline/job ID'
    )
    pipeline_name = models.CharField(
        max_length=255,
        blank=True,
        help_text='Human-readable pipeline name'
    )
    pipeline_url = models.URLField(
        blank=True,
        help_text='Web URL to the pipeline'
    )
    
    # Trigger configuration
    auto_trigger = models.BooleanField(
        default=True,
        help_text='Whether to auto-trigger on SCM events'
    )
    trigger_branches = models.JSONField(
        default=list,
        blank=True,
        help_text='Branch patterns that trigger this pipeline'
    )
    
    # Webhook configuration
    webhook_id = models.CharField(
        max_length=100,
        blank=True,
        help_text='Provider webhook ID'
    )
    webhook_secret = models.CharField(
        max_length=255,
        blank=True,
        help_text='Webhook signature secret'
    )
    webhook_configured = models.BooleanField(
        default=False,
        help_text='Whether webhook is configured'
    )
    
    # Sync state
    last_sync_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Last successful sync of builds'
    )
    sync_error = models.TextField(
        blank=True,
        help_text='Last sync error message'
    )
    
    is_active = models.BooleanField(
        default=True,
        help_text='Whether this binding is active'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'CI/CD Binding'
        verbose_name_plural = 'CI/CD Bindings'
        ordering = ['binding_type', 'pipeline_name']
    
    def __str__(self):
        return f"CI/CD: {self.pipeline_name or self.pipeline_id} ({self.get_binding_type_display()})"

    def save(self, *args, **kwargs):
        """Upsert the legacy GitlabProject row for GitLab bindings.

        E27 self-hoster footgun (2026-09-13): the CI/CD RCA path
        (``providers/tasks.py::retrieve_gitlab_job_logs`` +
        ``gitlab_webhook.py::_create_pipeline_record``) still looks up
        ``GitlabProject.objects.filter(project_id=<external_id>)``
        for the org resolver + access_token. A new self-hoster who
        onboards purely through this modern binding UI silently gets
        zero RCA output because that row doesn't exist. Auto-create
        it here so bindings alone are sufficient.
        """
        super().save(*args, **kwargs)
        try:
            self._sync_legacy_gitlab_project()
        except Exception:
            # Never let the legacy shim block a legitimate CICDBinding
            # write — surface via logs only.
            import logging
            logging.getLogger(__name__).warning(
                "CICDBinding %s save: legacy GitlabProject sync failed",
                self.pk, exc_info=True,
            )

    def _sync_legacy_gitlab_project(self):
        if not self.integration or self.integration.provider_type != 'gitlab':
            return
        if not self.pipeline_id:
            return

        from providers.models import GitlabProject

        creds = self.integration.get_credentials() or {}
        token = (
            creds.get('api_token')
            or creds.get('access_token')
            or creds.get('token')
            or ''
        )
        org = self.project_service.project.organisation
        base_url = self.integration.base_url or ''

        gp, _ = GitlabProject.objects.get_or_create(
            project_id=str(self.pipeline_id),
            defaults={
                'organisation': org,
                'name': self.pipeline_name or f'gitlab-project-{self.pipeline_id}',
                'gitlab_url': base_url,
                'username': creds.get('username', '') or '',
                'access_token': token,
                'webhook': self.webhook_configured,
            },
        )
        # The legacy row is unique per GitLab project id across the install.
        # If another organisation already has it, leave it alone: moving it
        # (and replacing its token) let one organisation take over another's
        # repository and, through the legacy webhook paths, receive its CI
        # events. This binding still works through the new paths.
        if gp.organisation_id != org.id:
            logger.warning("CICDBinding %s: GitLab project %s belongs to another organisation; legacy row left as is",
                           self.pk, self.pipeline_id)
            return
        # Keep url/token fresh if the integration was updated.
        dirty = False
        if base_url and gp.gitlab_url != base_url:
            gp.gitlab_url = base_url
            dirty = True
        if token and gp.get_access_token() != token:
            gp.access_token = token  # save() auto-encrypts
            dirty = True
        if dirty:
            gp.save()

    @property
    def provider_type(self):
        return self.integration.provider_type
    
    def get_provider(self):
        """Get configured provider instance for this binding."""
        from providers.scm_providers import get_provider, get_cicd_provider, CICD_PROVIDERS
        
        if self.integration.provider_type in CICD_PROVIDERS:
            creds = self.integration.get_credentials()
            return get_cicd_provider(
                provider_name=self.integration.provider_type,
                base_url=self.integration.base_url or '',
                username=creds.get('username', ''),
                api_token=self.integration.get_access_token(),
            )
        else:
            return get_provider(
                provider_name=self.integration.provider_type,
                project_id=self.pipeline_id,
                access_token=self.integration.get_access_token(),
                base_url=self.integration.base_url,
                organization=self.integration.provider_organization(),
            )


