"""
Organisation Settings Models

Notification-related models retired in PR-N phase 2 (2026-09-26).
Delivery targets now live on ``notifications.IncidentNotificationChannel``
and routing on ``notifications.NotificationRoutingRule``. Personal
per-user prefs live on ``notifications.UserNotificationPreference``.

This module provides AI Model configuration (extensible for future
providers like Claude) and org-scoped API key storage.
"""

from django.db import models
from Organisations.models import Organisations as Organisation


# PR-N phase 2 (2026-09-26): ``NotificationSettings`` retired here.
# Data moved to ``notifications.IncidentNotificationChannel`` via
# migration ``notifications/0004``; the drop lives in
# ``org_settings/0019_retire_notification_settings``.


class AIModelProvider(models.Model):
    """
    Registered AI model providers.
    Extensible design to add new providers (Gemini, DeepSeek, Claude, etc.)
    """
    name = models.CharField(
        max_length=50,
        unique=True,
    )
    display_name = models.CharField(max_length=100)
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this provider is available for use"
    )
    requires_api_key = models.BooleanField(default=True)
    api_base_url = models.URLField(
        blank=True,
        null=True,
        help_text="Base URL for API calls"
    )
    default_model = models.CharField(
        max_length=100,
        blank=True,
        help_text="Default model name for this provider"
    )
    
    # Vestigial. Migration 0011 removed the env-var fallback in
    # ai_service.get_api_key_for_org and blanked these values precisely so the
    # catalogue would stop advertising "set GOOGLE_API_KEY and it'll work" —
    # but this help text went on advertising it in the admin, which is one of
    # the five places that misconception survived. Kept in the schema for the
    # audit trail; setting it has no effect.
    env_key_name = models.CharField(
        max_length=100, blank=True, default='',
        help_text=(
            "Unused. API keys are not read from the environment — they live on "
            "OrganisationAPIKey, per organisation, encrypted at rest. Kept for "
            "the audit trail only."
        )
    )
    env_url_name = models.CharField(
        max_length=100, blank=True, default='',
        help_text="Env var name for base URL (e.g. DEEPSEEK_API_URL)"
    )
    is_system = models.BooleanField(
        default=False,
        help_text="System providers cannot be deleted by users"
    )

    # Plugin Architecture Fields
    adapter_class = models.CharField(
        max_length=255,
        default='ai_model.adapters.gemini.GeminiAdapter',
        help_text="Python path to the adapter class (e.g. ai_model.adapters.openai.GenericOpenAIAdapter)"
    )
    
    rate_limits = models.JSONField(
        default=dict,
        blank=True,
        help_text="Rate limiting config (e.g. {'rpm': 60, 'tpm': 100000})"
    )
    
    circuit_config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Circuit breaker config (e.g. {'failure_threshold': 5, 'recovery_timeout': 60})"
    )
    
    validation_config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Validation rules for this provider"
    )

    # Public list prices, per 1 million tokens, in USD. Used by
    # AITokenUsageService to estimate per-batch and per-org spend.
    # Moved from a hardcoded dict in usage_tracking.py 2026-08-31 —
    # the dict fell out of sync when model IDs changed in the Day 1
    # rework (references to gemini-2.5-flash / claude-sonnet-4-…
    # after Day 1 updated defaults to 3.5-flash / sonnet-5). Keeping
    # prices on the same row as the model ID means the two can never
    # drift again.
    price_input_per_million = models.DecimalField(
        max_digits=10, decimal_places=6,
        default=0,
        help_text="USD per 1M input tokens (public list price).",
    )
    price_output_per_million = models.DecimalField(
        max_digits=10, decimal_places=6,
        default=0,
        help_text="USD per 1M output tokens (public list price).",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "AI Model Provider"
        verbose_name_plural = "AI Model Providers"
        ordering = ['display_name']

    def __str__(self):
        return self.display_name


class OrganisationAISettings(models.Model):
    """
    AI settings for an organisation.
    Stores preferred model, fallback, and API keys.
    """
    organisation = models.OneToOneField(
        Organisation,
        on_delete=models.CASCADE,
        related_name='ai_settings'
    )
    
    # Default provider selection
    default_provider = models.ForeignKey(
        AIModelProvider,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='default_for_orgs',
        help_text="Primary AI provider to use"
    )
    
    # Fallback provider selection
    fallback_provider = models.ForeignKey(
        AIModelProvider,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='fallback_for_orgs',
        help_text="Fallback provider if primary fails"
    )
    
    # Use organisation's own API keys (if False, use system defaults)
    use_custom_keys = models.BooleanField(
        default=False,
        help_text="Use organisation's custom API keys instead of system defaults"
    )

    # Q3.3 — monthly AI cost cap (USD). None = unlimited (default).
    # When set, ``BudgetTracker`` refuses new AI calls once the
    # calendar-month AITokenUsage.cost_usd sum exceeds this value.
    # Rule-based issue creation (Sentinel, correlation engine) still
    # runs — users don't lose incident detection, just AI polish.
    monthly_budget_usd = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Hard cap on AI API spend per calendar month (USD). "
                  "Leave blank for no cap.",
    )
    budget_warn_pct = models.IntegerField(
        default=80,
        help_text="Percent of monthly_budget_usd at which admins are warned.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Organisation AI Settings"
        verbose_name_plural = "Organisation AI Settings"
    
    def __str__(self):
        return f"AISettings for {self.organisation.name}"
    
    def get_provider_name(self):
        """Get the default provider name or fallback to system default."""
        if self.default_provider:
            return self.default_provider.name
        return 'gemini'  # System default


class OrganisationAPIKey(models.Model):
    """
    Encrypted API keys for AI providers.
    Allows organisations to use their own API keys.
    """
    organisation = models.ForeignKey(
        Organisation,
        on_delete=models.CASCADE,
        related_name='api_keys'
    )
    provider = models.ForeignKey(
        AIModelProvider,
        on_delete=models.CASCADE,
        related_name='org_api_keys'
    )
    
    # API key (should be encrypted in production)
    api_key = models.CharField(
        max_length=500,
        help_text="Encrypted API key"
    )
    
    # Base URL for API calls (optional, for providers like DeepSeek)
    base_url = models.URLField(
        blank=True,
        null=True,
        help_text="Custom API endpoint URL (e.g., https://api.deepseek.com)"
    )

    # Provider-specific configuration bag. Merged into the adapter
    # `config` dict at call time so provider-specific auth quirks can
    # be handled without expanding the model schema per-provider.
    # Currently used keys:
    #   - anthropic: ``workspace_id`` — sent as ``anthropic-workspace-id``
    #     header for workspace-scoped keys, which otherwise fail with
    #     HTTP 400 "This API key is not scoped to a workspace...".
    extra_config = models.JSONField(
        default=dict, blank=True,
        help_text="Provider-specific extras (e.g., anthropic workspace_id).",
    )

    is_active = models.BooleanField(default=True)
    last_tested_at = models.DateTimeField(null=True, blank=True)
    last_test_success = models.BooleanField(null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Organisation API Key"
        verbose_name_plural = "Organisation API Keys"
        unique_together = ['organisation', 'provider']
    
    def __str__(self):
        return f"{self.organisation.name} - {self.provider.display_name}"

    def save(self, *args, **kwargs):
        """Auto-encrypt api_key if it looks like plaintext.

        E6-1 fix: prior to this, saving via naive ORM (``key.api_key = raw;
        key.save()``) stored plaintext, but the retrieval path calls
        ``decrypt_api_key()`` unconditionally → AUTH_ERROR on every AI
        call. Common footgun in scripts + tests + admin actions.

        Fernet ciphertext always starts with 'gAAAAA' after base64.
        If the caller stored something that DOESN'T look like a Fernet
        token, encrypt it here so downstream reads succeed.
        """
        from org_settings.encryption import encrypt_api_key, is_encrypted
        if self.api_key and not is_encrypted(self.api_key):
            self.api_key = encrypt_api_key(self.api_key)
        super().save(*args, **kwargs)

    def get_masked_key(self):
        """Return masked version of API key for display."""
        if not self.api_key:
            return ""
        if len(self.api_key) <= 8:
            return "••••••••"
        return f"{self.api_key[:4]}••••••••{self.api_key[-4:]}"


class IssueSettings(models.Model):
    """
    Issue deduplication and lifecycle settings for an organisation.
    Controls how duplicate issues are handled across batches.
    """
    organisation = models.OneToOneField(
        Organisation,
        on_delete=models.CASCADE,
        related_name='issue_settings'
    )
    
    # Deduplication settings
    dedup_enabled = models.BooleanField(
        default=True,
        help_text="Skip creating duplicate issues with same fingerprint"
    )
    
    DEDUP_WINDOW_CHOICES = [
        (7, '7 days'),
        (14, '14 days'),
        (30, '30 days'),
        (90, '90 days'),
        (0, 'Forever'),
    ]
    dedup_window_days = models.IntegerField(
        choices=DEDUP_WINDOW_CHOICES,
        default=7,
        help_text="How long to remember issues for deduplication"
    )
    
    # Mute options
    MUTE_DURATION_CHOICES = [
        (1, '1 day'),
        (7, '1 week'),
        (30, '30 days'),
        (0, 'Forever'),
    ]
    default_mute_duration_days = models.IntegerField(
        choices=MUTE_DURATION_CHOICES,
        default=7,
        help_text="Default duration when muting an issue"
    )
    
    # Auto-resolve settings
    auto_resolve_enabled = models.BooleanField(
        default=False,
        help_text="Automatically resolve issues not seen for X days"
    )
    auto_resolve_after_days = models.IntegerField(
        default=7,
        help_text="Days without detection before auto-resolving"
    )

    # Past-incident memory — inject resolved-issue root causes into AI prompts
    memory_enabled = models.BooleanField(
        default=True,
        help_text="Inject resolved-issue root causes as diagnostic hints into AI analysis"
    )
    memory_window_days = models.IntegerField(
        default=90,
        help_text="How far back to look for resolved-issue memories (days)"
    )
    memory_max_items = models.IntegerField(
        default=3,
        help_text="Max memories injected per prompt (token budget control)"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Issue Settings"
        verbose_name_plural = "Issue Settings"
    
    def __str__(self):
        return f"IssueSettings for {self.organisation.name}"


class SentinelConfig(models.Model):
    """Per-organisation Sentinel configuration."""
    organisation = models.OneToOneField(
        Organisation,
        on_delete=models.CASCADE,
        related_name='sentinel_config'
    )

    # Master switch
    active_mode = models.BooleanField(
        default=False,
        help_text="When True, quiet batches skip AI analysis. When False, shadow mode."
    )

    # Threshold overrides (0 = use system defaults from Data/sentinel.py)
    error_spike_multiplier = models.FloatField(
        default=0,
        help_text="Override ERROR_SPIKE_MULTIPLIER (0 = use default 2.0)"
    )
    z_score_threshold = models.FloatField(
        default=0,
        help_text="Override Z_SCORE_THRESHOLD (0 = use default 3.0)"
    )

    # Max batches between AI analyses (safety net)
    max_quiet_batches = models.IntegerField(
        default=12,
        help_text="Force AI analysis after this many consecutive quiet batches"
    )

    # Batch 50 — Pre-creation gate. When True (default), quiet batches
    # are dropped BEFORE the DB row is written, saving disk on multi-
    # region / multi-env / N-project shops that would otherwise write
    # hundreds of noise batch rows per hour. When False, all batches
    # are persisted and Sentinel decides AI at analysis time only
    # (pre-Batch 50 behaviour — useful for admins who want a complete
    # audit of every window).
    #
    # Only fires when ``active_mode=True`` — shadow mode always
    # persists so the org can observe what Sentinel would have skipped.
    pre_creation_gate_enabled = models.BooleanField(
        default=True,
        help_text=(
            "When True + active_mode, quiet batches are dropped BEFORE the DB row "
            "is written. Prevents batch-row fanout on quiet windows. Turn OFF if "
            "you want every window persisted (auditability > cost)."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Sentinel Config"

    def __str__(self):
        mode = "active" if self.active_mode else "shadow"
        return f"SentinelConfig ({mode}) for {self.organisation.name}"


# NOTE: SystemMailSettings was removed 2026-09-01. SMTP is now
# env-var-only (Grafana model) — configure EMAIL_HOST etc. in .env
# and restart. See notifications/services.py + migration
# 0013_remove_systemmailsettings.
#
# ``is_configured()``, ``load()`` and ``save()`` intercepts are all
# gone with the model. Nothing else in the codebase depends on the
# ``system_mail_settings`` cache key either.

    def is_configured(self):
        return bool(self.email_host)
