import logging

from django.db import models
from Organisations.models import Organisations

logger = logging.getLogger(__name__)

# Create your models here.

# SCM Provider choices (extensible for GitHub, Bitbucket, etc.)
SCM_PROVIDER_CHOICES = [
    ('gitlab', 'GitLab'),
    ('github', 'GitHub'),
    ('bitbucket', 'Bitbucket'),
    ('azure_devops', 'Azure DevOps'),
]

# CI/CD Provider choices
CICD_PROVIDER_CHOICES = [
    ('gitlab', 'GitLab CI'),
    ('github_actions', 'GitHub Actions'),
    ('jenkins', 'Jenkins'),
    ('azure_devops', 'Azure DevOps'),
    ('bitbucket_pipelines', 'Bitbucket Pipelines'),
]


class GitlabProject(models.Model):
    gitlab_url = models.CharField(max_length=255)
    username = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    project_id = models.CharField(max_length=255, unique=True)
    access_token = models.CharField(max_length=512)
    organisation = models.ForeignKey(Organisations, on_delete=models.CASCADE, null=True, blank=True)
    webhook = models.BooleanField(default=False)
    es_index_name = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"{self.name} ({self.project_id})"

    def save(self, *args, **kwargs):
        """Auto-encrypt access_token if it looks like plaintext.

        Matches the OrganisationAPIKey pattern (E6-1): callers that
        assign a raw PAT via ORM (``gp.access_token = 'glpat-...'``)
        get encryption for free instead of storing plaintext that
        downstream ``get_access_token()`` would fail to decrypt.
        """
        from org_settings.encryption import encrypt_api_key, is_encrypted
        if self.access_token and not is_encrypted(self.access_token):
            self.access_token = encrypt_api_key(self.access_token)
        super().save(*args, **kwargs)

    def get_access_token(self) -> str:
        """Return the decrypted PAT. Callers must use this — never
        touch ``self.access_token`` directly at read time."""
        from org_settings.encryption import decrypt_api_key, is_encrypted
        if not self.access_token:
            return ''
        if is_encrypted(self.access_token):
            return decrypt_api_key(self.access_token)
        # Legacy row saved before this migration — return as-is so
        # existing installs don't hard-fail on the first read after
        # deploy. The next save() will encrypt it.
        return self.access_token


class Pipeline(models.Model):
    """
    CI/CD Pipeline model - supports multiple providers.
    
    For GitLab: Uses 'project' FK (backwards compatible)
    For other providers: Uses 'external_project_id' + 'provider_metadata'
    
    Multi-tenancy: organisation FK provides direct isolation.
    """
    # Direct organisation link for multi-tenancy isolation
    organisation = models.ForeignKey(
        Organisations,
        on_delete=models.CASCADE,
        null=True,  # Nullable for backward compatibility during migration
        blank=True,
        db_index=True,
        related_name='pipelines',
        help_text='Organisation this pipeline belongs to (for data isolation)'
    )
    
    # GitLab FK (backwards compatible)
    project = models.ForeignKey(
        GitlabProject, 
        on_delete=models.CASCADE,
        null=True,  # Make nullable for non-GitLab providers
        blank=True
    )
    pipeline_id = models.CharField(max_length=255)  # Unique per provider, see Meta
    status = models.CharField(max_length=255)
    branch = models.CharField(max_length=255)
    
    # NEW - Multi-provider support (Phase 2)
    cicd_provider = models.CharField(
        max_length=50,
        choices=CICD_PROVIDER_CHOICES,
        default='gitlab',
        db_index=True,
        help_text='CI/CD engine that ran this pipeline'
    )
    
    provider_metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text='Provider-specific data (workflow_id, job_name, etc.)'
    )
    
    external_project_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        db_index=True,
        help_text='Project/repo ID for non-GitLab providers (e.g., owner/repo for GitHub)'
    )
    
    environment = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text='Detected deployment environment'
    )
    
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['cicd_provider', 'pipeline_id']),
            models.Index(fields=['cicd_provider', 'external_project_id']),
        ]
        # Pipeline IDs are only unique within the same provider (e.g.
        # GitLab "12345" and GitHub "12345" are different pipelines).
        unique_together = [('cicd_provider', 'pipeline_id')]
    
    def __str__(self):
        project_name = self.project.name if self.project else self.external_project_id or 'Unknown'
        return f"[{self.cicd_provider}] {project_name} - {self.pipeline_id}"


class Job(models.Model):
    pipeline = models.ForeignKey(Pipeline, on_delete=models.CASCADE, related_name='jobs')
    job_id = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    status = models.CharField(max_length=50)
    # DEPRECATED: Will be removed in future migration. Use error_summary instead.
    logs = models.TextField(
        blank=True, null=True,
        help_text='DEPRECATED — full job log output. Use error_summary for AI analysis.'
    )
    error_summary = models.TextField(
        blank=True, null=True,
        help_text='Filtered error/warning lines from job output (max ~20 lines). '
                  'Replaces full logs storage for AI analysis.'
    )
    log_storage_url = models.URLField(
        blank=True, null=True,
        help_text='URL to externally-stored log (S3/MinIO) when logs exceed inline cap.'
    )

    # Hard cap: 1 MB of inline log text
    MAX_LOG_SIZE = 1_048_576

    class Meta:
        unique_together = ('pipeline', 'job_id')

    def __str__(self):
        return f"{self.name} ({self.job_id})"


class CodeChange(models.Model):
    """
    Stores commit data and diffs for AI correlation.
    
    Provider-agnostic design - can be used with GitLab, GitHub, Bitbucket.
    The 'provider' and 'project_id' fields identify the SCM project,
    while 'gitlab_project' provides direct linkage when using GitLab.
    
    Multi-tenancy: organisation FK provides direct isolation.
    """
    # Direct organisation link for multi-tenancy isolation
    organisation = models.ForeignKey(
        Organisations,
        on_delete=models.CASCADE,
        null=True,  # Nullable for backward compatibility during migration
        blank=True,
        db_index=True,
        related_name='code_changes',
        help_text='Organisation this code change belongs to (for data isolation)'
    )
    
    # Provider-agnostic fields (for future GitHub/Bitbucket support)
    provider = models.CharField(
        max_length=20, 
        choices=SCM_PROVIDER_CHOICES, 
        default='gitlab'
    )
    project_id = models.CharField(max_length=255, db_index=True)  # SCM project ID
    
    # GitLab-specific link (optional, for backwards compat)
    gitlab_project = models.ForeignKey(
        GitlabProject, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        related_name='code_changes'
    )
    
    # Commit metadata
    commit_sha = models.CharField(max_length=64, db_index=True)  # SHA can be up to 64 chars
    commit_message = models.TextField()
    author_name = models.CharField(max_length=255)
    author_email = models.CharField(max_length=255, blank=True, null=True)
    timestamp = models.DateTimeField(db_index=True)
    branch = models.CharField(max_length=255)
    
    # Related pipeline (if commit triggered a build)
    pipeline = models.ForeignKey(
        Pipeline, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='code_changes'
    )
    
    # Diff statistics
    files_changed = models.IntegerField(default=0)
    additions = models.IntegerField(default=0)
    deletions = models.IntegerField(default=0)
    
    # Detailed diff summary (JSON)
    # Example: {"files": [{"path": "app.py", "additions": 10, "deletions": 5, "is_new": false}]}
    diff_summary = models.JSONField(default=dict, blank=True)
    
    # Processing metadata
    created_at = models.DateTimeField(auto_now_add=True)
    diff_fetched = models.BooleanField(default=False)  # True if full diff was retrieved
    
    class Meta:
        ordering = ['-timestamp']
        unique_together = [('provider', 'project_id', 'commit_sha')]
        indexes = [
            models.Index(fields=['provider', 'project_id', 'timestamp']),
        ]
    
    def __str__(self):
        short_sha = self.commit_sha[:8] if self.commit_sha else 'N/A'
        return f"[{short_sha}] {self.commit_message[:50]}"
    
    def get_summary_for_ai(self) -> dict:
        """Return a compact summary suitable for AI analysis."""
        # Lookup service_name from linked ProjectService
        service_name = None
        if self.gitlab_project:
            try:
                from Projects.models import ProjectService
                project_service = ProjectService.objects.filter(
                    gitlab_project=self.gitlab_project
                ).select_related('project').first()
                if project_service:
                    service_name = project_service.service_name or self.gitlab_project.name
                else:
                    service_name = self.gitlab_project.name
            except Exception:
                service_name = self.gitlab_project.name if self.gitlab_project else None
        
        return {
            'sha': self.commit_sha[:8],
            'message': self.commit_message[:200],
            'author': self.author_name,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'branch': self.branch,
            'service_name': service_name,  # NEW: Which service this commit belongs to
            'stats': {
                'files': self.files_changed,
                'additions': self.additions,
                'deletions': self.deletions,
            },
            'files': [
                {
                    'path': f.get('path', ''),
                    'diff': f.get('diff_preview', '')  # Include the diff preview
                } 
                for f in self.diff_summary.get('files', [])
            ][:10],
        }


class Deployment(models.Model):
    """
    Tracks when a code change is deployed to a specific environment.
    
    Key concept: One CodeChange can have multiple Deployments (dev → staging → prod).
    This enables proper temporal correlation - batches include code based on WHEN
    it was deployed to that environment, not when it was committed.
    
    Example:
        Code committed Monday 09:00
        Deployed to dev Monday 09:15 → Deployment(env='development', deployed_at='09:15')
        Deployed to prod Wednesday 14:00 → Deployment(env='production', deployed_at='14:00')
        
        Result: Dev batch (Monday 10:00) includes it, Prod batch (Wednesday 15:00) also includes it
    """
    
    # What was deployed
    code_change = models.ForeignKey(
        CodeChange,
        on_delete=models.CASCADE,
        related_name='deployments',
        help_text="The code change that was deployed"
    )
    
    # Where it was deployed
    ENVIRONMENT_CHOICES = [
        ('development', 'Development'),
        ('staging', 'Staging'),
        ('production', 'Production'),
    ]
    environment = models.CharField(
        max_length=50,
        choices=ENVIRONMENT_CHOICES,
        db_index=True,
        help_text="Target environment for this deployment"
    )
    
    # When it was deployed
    deployed_at = models.DateTimeField(
        db_index=True,
        help_text="When the deployment occurred (UTC)"
    )
    
    # How it was deployed
    pipeline = models.ForeignKey(
        Pipeline,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='deployments',
        help_text="CI/CD pipeline that performed the deployment"
    )
    
    # Status
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('rolled_back', 'Rolled Back'),
    ]
    status = models.CharField(
        max_length=50,
        choices=STATUS_CHOICES,
        default='success',
        db_index=True,
        help_text="Deployment status"
    )
    
    # Who deployed
    deployed_by = models.CharField(
        max_length=100,
        default='CI/CD',
        help_text="Who triggered the deployment (username or 'CI/CD')"
    )
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(
        blank=True,
        help_text="Optional deployment notes (e.g., 'Emergency hotfix')"
    )
    
    class Meta:
        ordering = ['-deployed_at']
        
        indexes = [
            # Query: Get deployments for environment in time window
            models.Index(fields=['environment', 'deployed_at']),
            # Query: Get all deployments for a code change
            models.Index(fields=['code_change', 'environment']),
            # Query: Get successful deployments
            models.Index(fields=['status', 'environment', 'deployed_at']),
        ]
        
        # Prevent duplicate deployments
        unique_together = [('code_change', 'environment', 'deployed_at')]
    
    def __str__(self):
        short_sha = self.code_change.commit_sha[:8] if self.code_change else 'N/A'
        deployed_time = self.deployed_at.strftime('%Y-%m-%d %H:%M') if self.deployed_at else 'N/A'
        return f"{short_sha} → {self.environment} @ {deployed_time}"
    
    def is_successful(self):
        """Helper: Check if deployment was successful"""
        return self.status == 'success'

class ProviderIntegration(models.Model):
    """
    Global Provider Integration settings.
    Stores credentials and configuration for SCM and CI/CD providers at the organisation level.
    
    Security: Credentials are encrypted at rest using Fernet encryption.
    Multi-tenancy: Scoped to organisation for data isolation.
    """
    PROVIDER_TYPES = [
        ('gitlab', 'GitLab'),
        ('github', 'GitHub'),
        ('bitbucket', 'Bitbucket'),
        ('azure_devops', 'Azure DevOps'),
        ('jenkins', 'Jenkins'),
    ]
    
    CATEGORY_CHOICES = [
        ('devops', 'DevOps Platform'),  # GitLab, GitHub, Azure DevOps - has SCM + CI/CD
        ('scm', 'Source Control Only'),
        ('cicd', 'CI/CD Only'),  # Jenkins
    ]
    
    VERIFICATION_STATUS_CHOICES = [
        ('pending', 'Pending Verification'),
        ('verified', 'Verified'),
        ('failed', 'Verification Failed'),
        ('expired', 'Token Expired'),
    ]
    
    # Provider configuration
    name = models.CharField(max_length=255, help_text='Display name for this integration')
    provider_type = models.CharField(choices=PROVIDER_TYPES, max_length=50, db_index=True)
    category = models.CharField(choices=CATEGORY_CHOICES, max_length=20, default='devops')
    base_url = models.URLField(blank=True, null=True, help_text='Base URL for self-hosted instances')
    
    # Credentials (ENCRYPTED at rest)
    credentials = models.JSONField(
        default=dict, 
        help_text='Encrypted credentials (access_token, api_key, etc.)'
    )
    
    # Capabilities (auto-detected or manually set)
    capabilities = models.JSONField(
        default=list,
        help_text='Provider capabilities: ["scm", "cicd", "deployments", "issues"]'
    )

    # Pre-computed masked token hint (avoids decryption on read)
    # Populated by set_credentials(); format: "glpa...xY4q" or empty.
    token_hint = models.CharField(
        max_length=20,
        blank=True,
        default='',
        help_text='First 4 + last 4 chars of the access token, for display without decryption.',
    )
    
    # Verification status
    verification_status = models.CharField(
        max_length=20,
        choices=VERIFICATION_STATUS_CHOICES,
        default='pending',
        db_index=True
    )
    last_verified_at = models.DateTimeField(null=True, blank=True)
    verification_error = models.TextField(blank=True, help_text='Last verification error message')
    
    # Token management
    token_expires_at = models.DateTimeField(null=True, blank=True, help_text='When the token expires (if known)')
    
    # Multi-tenancy
    organisation = models.ForeignKey(
        Organisations, 
        on_delete=models.CASCADE, 
        related_name='integrations',
        db_index=True
    )
    
    # Audit fields
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        'Users.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_integrations'
    )
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organisation', 'provider_type']),
            models.Index(fields=['organisation', 'is_active']),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_provider_type_display()})"
    
    def set_credentials(self, credentials_dict: dict) -> None:
        """
        Securely set credentials with encryption.

        Also pre-computes token_hint so the serializer can mask
        without ever decrypting.
        """
        from .encryption import encrypt_credentials
        # Pre-compute hint *before* encrypting
        raw_token = (
            credentials_dict.get('access_token')
            or credentials_dict.get('token')
            or credentials_dict.get('api_key')
            or credentials_dict.get('api_token')
            or ''
        )
        if raw_token and len(raw_token) > 8:
            self.token_hint = f"{raw_token[:4]}...{raw_token[-4:]}"
        elif raw_token:
            self.token_hint = '****'
        else:
            self.token_hint = ''
        self.credentials = encrypt_credentials(credentials_dict)
    
    def get_credentials(self) -> dict:
        """
        Get decrypted credentials.
        
        Returns:
            Decrypted credentials dictionary
        """
        from .encryption import decrypt_credentials
        return decrypt_credentials(self.credentials)
    
    def get_access_token(self) -> str:
        """
        Convenience method to get the access token.

        Raises:
            ValueError: If the token has expired.
        """
        if self.is_token_expired:
            raise ValueError(
                f"Token for integration '{self.name}' expired at {self.token_expires_at}. "
                "Please refresh the credentials."
            )
        creds = self.get_credentials()
        return creds.get('access_token') or creds.get('token') or creds.get('api_key') or creds.get('api_token', '')

    @property
    def is_token_expired(self) -> bool:
        """Return True if token_expires_at is set and in the past."""
        if not self.token_expires_at:
            return False
        from django.utils import timezone
        return self.token_expires_at <= timezone.now()

    @property
    def token_expires_soon(self) -> bool:
        """Return True if token expires within 7 days."""
        if not self.token_expires_at:
            return False
        from django.utils import timezone
        from datetime import timedelta
        return self.token_expires_at <= timezone.now() + timedelta(days=7)

    def check_token_expiry(self) -> str:
        """
        Check token expiry and update verification_status accordingly.

        Returns:
            'expired', 'expires_soon', or 'ok'
        """
        if self.is_token_expired:
            logger.warning(f"Token expired for integration '{self.name}' (pk={self.pk})")
            self.verification_status = 'expired'
            self.save(update_fields=['verification_status'])
            return 'expired'
        if self.token_expires_soon:
            logger.warning(
                f"Token expires soon for integration '{self.name}' (pk={self.pk}) "
                f"at {self.token_expires_at}"
            )
            return 'expires_soon'
        return 'ok'

    def mark_verified(self, success: bool = True, error: str = '') -> None:
        """Update verification status after a connection test."""
        from django.utils import timezone
        
        if success:
            self.verification_status = 'verified'
            self.verification_error = ''
        else:
            self.verification_status = 'failed'
            self.verification_error = error
        
        self.last_verified_at = timezone.now()
        self.save(update_fields=['verification_status', 'verification_error', 'last_verified_at'])
    
    def get_default_capabilities(self) -> list:
        """Get default capabilities based on provider type."""
        capability_map = {
            'gitlab': ['scm', 'cicd', 'deployments', 'issues'],
            'github': ['scm', 'cicd', 'deployments', 'issues'],
            'azure_devops': ['scm', 'cicd', 'deployments', 'issues'],
            'bitbucket': ['scm', 'cicd'],
            'jenkins': ['cicd', 'deployments'],
        }
        return capability_map.get(self.provider_type, ['scm'])
    
    @property
    def is_verified(self) -> bool:
        """Check if integration is verified and ready to use."""
        return self.verification_status == 'verified'
    
    @property
    def needs_verification(self) -> bool:
        """Check if integration needs verification."""
        return self.verification_status in ('pending', 'failed', 'expired')
    
    @property
    def display_url(self) -> str:
        """Get display URL (base_url or default provider URL)."""
        if self.base_url:
            return self.base_url
        
        default_urls = {
            'gitlab': 'https://gitlab.com',
            'github': 'https://github.com',
            'bitbucket': 'https://bitbucket.org',
            'azure_devops': 'https://dev.azure.com',
            'jenkins': '',  # No default
        }
        return default_urls.get(self.provider_type, '')

