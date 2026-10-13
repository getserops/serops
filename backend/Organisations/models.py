from django.db import models
from django.utils.text import slugify


class Organisations(models.Model):
    LANGUAGE_CHOICES = [
        ('en', 'English'),
        ('fr', 'Français'),
    ]
    
    name = models.CharField(unique=True, null=False, max_length=255)
    slug = models.SlugField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text='URL-safe identifier, used as org_slug in log index naming'
    )
    website = models.CharField(null=True, blank=True, max_length=255)
    logo = models.ImageField(upload_to='org_logos/', null=True, blank=True)
    language = models.CharField(max_length=5, choices=LANGUAGE_CHOICES, default='en')

    # Flags this organisation as the public read-only demo on
    # app.serops.ai. Demo orgs are excluded from cross-org analytics
    # and signup search, and their data is regenerated nightly. Only
    # one demo org is expected per deployment.
    is_demo = models.BooleanField(
        default=False,
        db_index=True,
        help_text='True for the public demo org; data is regenerated nightly.',
    )

    # Q5-5 (2026-09-21): per-org secret for inbound alert webhooks
    # (Alertmanager / Grafana / Datadog / …). Verified as the Bearer
    # token in ``Data.alert_webhooks._authenticate``. When set, takes
    # precedence over the global ``settings.ALERT_WEBHOOK_SECRETS``
    # (backward compat for single-tenant deployments). Rotate via
    # ``POST /api/organisation/alert-secret/rotate/`` — plaintext is
    # returned once and never persisted; only its SHA-256 hash is
    # stored so a DB dump doesn't leak live secrets.
    alert_ingest_secret_hash = models.CharField(
        max_length=64, blank=True, default='',
        help_text='SHA-256 of the org\'s alert-ingest bearer secret. '
                  'Empty means fall back to global ALERT_WEBHOOK_SECRETS.',
    )
    alert_ingest_secret_prefix = models.CharField(
        max_length=12, blank=True, default='',
        help_text='First few chars of the secret for identification.',
    )
    alert_ingest_secret_rotated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'Organisations'
        
    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class OnboardingStatus(models.Model):
    """Tracks onboarding progress for an organisation.

    Reworked 2026-08-30 (item #11). Prior version was a self-attested
    checklist — user clicked "Mark Complete" and we trusted them. That
    produced high abandonment (users click through without doing the
    actual setup) and the whole wizard could show "100% complete" on
    an org where nothing was actually configured.

    New model:

    - **Completion is computed from real DB state**, not clicked. See
      :meth:`get_computed_state`. Every ``GET /status/`` recomputes so
      the wizard reflects reality even if the user did the work in
      another tab / via the API / via Terraform.
    - **Required steps cannot be individually skipped** (the completion
      detector will just keep returning False until the underlying
      resource exists). Two steps (SCM + CI/CD) are explicitly optional
      via :meth:`skip_step` — the user acknowledges "I don't want this
      right now" and it goes into ``skipped_steps``.
    - **Global dismiss (``is_skipped``) is UI-only**. It hides the
      wizard but does NOT mark onboarding complete. That way we don't
      falsely report activation for orgs that only wanted the wizard
      out of their way. Reversible via :meth:`resume`.
    - **``is_completed`` is a derived field** — auto-recomputed from
      the computed state on every :meth:`refresh_and_advance` call.
      Kept as a stored field (rather than @property) so downstream
      queries can filter on it without recomputing per row.

    Step order and skippability:

        welcome              (auto, informational)
        connect_ai_provider  (required)
        connect_observability(required)
        create_project       (required)
        link_service         (required)
        connect_scm          (skippable)
        connect_cicd         (skippable)
        waiting_for_first_analysis (required — flips when a batch is
                                    actually analyzed; this is the
                                    "aha moment" gate per Sentry /
                                    Datadog onboarding pattern)
        completed            (terminal — set once everything above
                              is resolved)
    """

    ONBOARDING_STEPS = [
        ('welcome', 'Welcome'),
        ('connect_ai_provider', 'Choose AI Model'),
        ('connect_observability', 'Connect Observability'),
        ('create_project', 'Create Project'),
        ('link_service', 'Link Service'),
        ('connect_scm', 'Connect Source Control'),
        ('connect_cicd', 'Connect CI/CD'),
        ('waiting_for_first_analysis', 'Waiting for First Analysis'),
        ('completed', 'Completed'),
    ]

    # Steps the user can explicitly say "skip for now" on. Required
    # steps aren't in this set — skipping them would leave the product
    # non-functional, so we just wait for the resource to exist.
    SKIPPABLE_STEPS = frozenset({'connect_scm', 'connect_cicd'})

    # Terminal-ish steps that don't need a completion detector. They
    # advance based on the state machine, not on external resources.
    _AUTO_STEPS = frozenset({'welcome', 'completed'})

    organisation = models.OneToOneField(
        Organisations,
        on_delete=models.CASCADE,
        related_name='onboarding_status',
    )

    current_step = models.CharField(
        max_length=40,
        choices=ONBOARDING_STEPS,
        default='welcome',
        help_text='Cursor into the step list — the first un-resolved step.',
    )

    # Cache of steps that pass their computed completion check.
    # Refreshed on every refresh_and_advance() call. Kept as a JSON
    # column (rather than always recomputing on read) so serializer
    # responses can render without re-running four DB queries.
    completed_steps = models.JSONField(
        default=list,
        blank=True,
        help_text='Steps that pass their computed completion check.',
    )

    # Steps the user explicitly opted out of. Only meaningful for
    # SKIPPABLE_STEPS — the model validates that on skip_step().
    skipped_steps = models.JSONField(
        default=list,
        blank=True,
        help_text='Skippable steps the user has dismissed for now.',
    )

    # Global "dismiss the wizard UI" flag — does NOT mean the org is
    # actually set up. Kept semantically distinct from is_completed
    # so we can report accurate activation numbers on the dashboard.
    is_skipped = models.BooleanField(
        default=False,
        help_text='UI-only: wizard is hidden. Onboarding may still be incomplete.',
    )
    # help_text kept to match migration 0004's original definition —
    # Django was auto-generating a spurious AlterField every batch
    # because the model dropped the help_text but the migration
    # history still had it. Restoring here (Q1.3, Batch 24) so
    # makemigrations produces zero pending changes going forward.
    skipped_at = models.DateTimeField(
        null=True, blank=True,
        help_text='When onboarding was skipped',
    )

    # Derived — refresh_and_advance() sets this. Kept as a stored
    # field so downstream code can .filter(is_completed=True)
    # without a python-side recompute.
    is_completed = models.BooleanField(
        default=False,
        help_text='All required steps resolved AND first analysis completed.',
    )
    completed_at = models.DateTimeField(
        null=True, blank=True,
        help_text='When onboarding was completed',
    )

    onboarding_data = models.JSONField(
        default=dict,
        blank=True,
        help_text='Wizard scratchpad: last-picked integration_id, first_analysis_dispatched_at, etc.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Onboarding Status'
        verbose_name_plural = 'Onboarding Statuses'

    def __str__(self):
        if self.is_completed:
            return f"{self.organisation.name} - Onboarding Complete"
        elif self.is_skipped:
            return f"{self.organisation.name} - Onboarding Dismissed"
        return f"{self.organisation.name} - Step: {self.get_current_step_display()}"

    # ------------------------------------------------------------------
    # Progress derivation
    # ------------------------------------------------------------------

    @property
    def _tracked_steps(self):
        """Steps that count toward progress %. Excludes welcome + completed."""
        return [s[0] for s in self.ONBOARDING_STEPS if s[0] not in self._AUTO_STEPS]

    @property
    def progress_percentage(self):
        """0-100 based on resolved (completed OR skipped) steps.

        A skipped optional step counts as resolved — from the user's
        perspective, they've made the decision, they're done with it.
        """
        tracked = self._tracked_steps
        if not tracked:
            return 100
        resolved = set(self.completed_steps or []) | set(self.skipped_steps or [])
        # Only count steps that are actually tracked, in case the DB
        # holds cruft from a prior schema (old step names).
        resolved_tracked = [s for s in tracked if s in resolved]
        return int((len(resolved_tracked) / len(tracked)) * 100)

    # ------------------------------------------------------------------
    # Computed state — the source of truth
    # ------------------------------------------------------------------

    def get_computed_state(self):
        """Return ``{step_name: is_complete_bool}`` derived from real state.

        Each check hits its underlying model directly rather than
        trusting a cached ``completed_steps`` list — the whole point
        of the rework is that the DB, not user clicks, decides what's
        done. Lazy-imports guard against circular imports at Django
        app-load time.
        """
        from django.apps import apps

        org = self.organisation

        AIModelProvider = apps.get_model('org_settings', 'AIModelProvider')
        OrganisationAPIKey = apps.get_model('org_settings', 'OrganisationAPIKey')
        ObservabilityIntegration = apps.get_model('integrations', 'ObservabilityIntegration')
        Project = apps.get_model('Projects', 'Project')
        ProjectService = apps.get_model('Projects', 'ProjectService')
        SCMBinding = apps.get_model('Projects', 'SCMBinding')
        CICDBinding = apps.get_model('Projects', 'CICDBinding')
        AIAnalyzedBatch = apps.get_model('Data', 'AIAnalyzedBatch')

        # AI provider: either the org has an active API key (for
        # keyed providers), or its default_provider is a keyless one
        # (Ollama). Both count as "configured".
        has_ai = OrganisationAPIKey.objects.filter(
            organisation=org, is_active=True,
        ).exists()
        if not has_ai:
            # Keyless-provider case: default_provider is set to
            # something with requires_api_key=False (Ollama).
            try:
                settings = org.ai_settings
                if settings and settings.default_provider_id:
                    provider = AIModelProvider.objects.filter(
                        id=settings.default_provider_id,
                    ).first()
                    if provider and not provider.requires_api_key:
                        has_ai = True
            except Exception:
                # ai_settings may not exist yet — treat as unconfigured.
                pass

        # Observability: at least one active integration with a
        # "logs" capability (SerOps is log-centric; a metrics-only
        # provider isn't enough to run first analysis).
        has_obs = ObservabilityIntegration.objects.filter(
            organisation=org, is_active=True,
            capabilities__contains=['logs'],
        ).exists()

        has_project = Project.objects.filter(organisation=org).exists()
        has_service = ProjectService.objects.filter(project__organisation=org).exists()

        # SCM / CICD count as "resolved" if either the binding exists
        # OR the user explicitly skipped that step. The skip check
        # lives in the caller (refresh_and_advance) so this method
        # stays a pure state-of-the-world function.
        has_scm = SCMBinding.objects.filter(
            project_service__project__organisation=org,
        ).exists()
        has_cicd = CICDBinding.objects.filter(
            project_service__project__organisation=org,
        ).exists()

        # First analysis: analyzed_at is set only after the batch
        # task completes with a real AI response. Empty analysis_history
        # is the default value and wouldn't distinguish "no analysis
        # yet" from "analysis ran but produced nothing".
        has_first_analysis = AIAnalyzedBatch.objects.filter(
            organisation=org, analyzed_at__isnull=False,
        ).exists()

        return {
            'welcome': True,  # implicit — advancing past it is user action
            'connect_ai_provider': has_ai,
            'connect_observability': has_obs,
            'create_project': has_project,
            'link_service': has_service,
            'connect_scm': has_scm,
            'connect_cicd': has_cicd,
            'waiting_for_first_analysis': has_first_analysis,
        }

    def refresh_and_advance(self):
        """Recompute completion + advance current_step + set is_completed.

        Idempotent — safe to call on every GET. Combines the computed
        state with user-declared skips to decide what's "resolved",
        then finds the first un-resolved step and parks the cursor
        there. If everything is resolved, sets ``is_completed=True``
        and ``current_step='completed'``.
        """
        from django.utils import timezone

        computed = self.get_computed_state()
        skipped = set(self.skipped_steps or [])

        # Rebuild completed_steps from computed truth. Anything the
        # user skipped stays out of completed_steps but is
        # considered "resolved" for cursor-advancement purposes.
        self.completed_steps = [name for name, done in computed.items() if done]

        step_order = [s[0] for s in self.ONBOARDING_STEPS if s[0] != 'completed']
        resolved = set(self.completed_steps) | skipped

        next_step = 'completed'
        for step in step_order:
            if step not in resolved:
                next_step = step
                break

        self.current_step = next_step

        # is_completed requires: every required step passes its
        # computed check (not just skip), AND the first analysis has
        # arrived. Skipping an optional step still counts as resolved
        # for progress, but doesn't fake-complete onboarding.
        all_required_done = all(
            computed[s] for s in step_order
            if s not in self.SKIPPABLE_STEPS and s != 'welcome'
        )
        if all_required_done and not self.is_completed:
            self.is_completed = True
            self.completed_at = timezone.now()
        elif not all_required_done and self.is_completed:
            # Real state has regressed (e.g. admin deleted the
            # observability integration). Un-complete honestly.
            self.is_completed = False
            self.completed_at = None

        self.save()
        return self

    # ------------------------------------------------------------------
    # State mutations
    # ------------------------------------------------------------------

    def skip_step(self, step_name):
        """Add ``step_name`` to skipped_steps if it's a skippable step.

        Raises ``ValueError`` if the caller tries to skip a required
        step — required steps have no meaningful "skip" (the completion
        detector will just keep returning False and the product will
        be broken). Callers should route those to the global dismiss
        flag (:meth:`dismiss`) instead.
        """
        if step_name not in self.SKIPPABLE_STEPS:
            raise ValueError(
                f"Step '{step_name}' is required and cannot be skipped. "
                f"Skippable steps: {sorted(self.SKIPPABLE_STEPS)}"
            )
        skipped = list(self.skipped_steps or [])
        if step_name not in skipped:
            skipped.append(step_name)
            self.skipped_steps = skipped
            self.save(update_fields=['skipped_steps', 'updated_at'])
        self.refresh_and_advance()
        return self

    def store_data(self, data):
        """Merge ``data`` into onboarding_data (wizard scratchpad)."""
        if not isinstance(data, dict):
            raise ValueError('onboarding_data payload must be a dict')
        current = dict(self.onboarding_data or {})
        current.update(data)
        self.onboarding_data = current
        self.save(update_fields=['onboarding_data', 'updated_at'])
        return self

    def dismiss(self):
        """Hide the wizard UI without marking onboarding complete.

        The distinction matters for reporting: a dismissed org is not
        an activated org. Reversible via :meth:`resume`.
        """
        from django.utils import timezone
        self.is_skipped = True
        self.skipped_at = timezone.now()
        self.save(update_fields=['is_skipped', 'skipped_at', 'updated_at'])
        return self

    def resume(self):
        """Undo :meth:`dismiss` — wizard reappears."""
        self.is_skipped = False
        self.skipped_at = None
        self.save(update_fields=['is_skipped', 'skipped_at', 'updated_at'])
        return self

    def reset(self):
        """Reset onboarding to start fresh (admin action)."""
        self.current_step = 'welcome'
        self.completed_steps = []
        self.skipped_steps = []
        self.is_skipped = False
        self.skipped_at = None
        self.is_completed = False
        self.completed_at = None
        self.onboarding_data = {}
        self.save()
        return self

    # ------------------------------------------------------------------
    # Deprecated shims — kept only so anything mid-transaction doesn't
    # explode. The wizard rewrite calls the new methods above.
    # ------------------------------------------------------------------

    def mark_step_complete(self, step_name, data=None):
        """Deprecated: completion is now computed, not stored.

        Prior callers used this to advance the wizard state machine.
        Under the new model, completion comes from
        :meth:`refresh_and_advance` reading real DB state. This shim
        stores any provided ``data`` in onboarding_data (which was
        the legitimate side-effect of the old call) and refreshes,
        but does NOT attempt to mark a step as done — that decision
        belongs to the underlying data now.
        """
        import warnings
        warnings.warn(
            "OnboardingStatus.mark_step_complete() is deprecated. "
            "Completion is computed from real state — call refresh_and_advance() instead. "
            "For storing wizard scratchpad data, use store_data(data).",
            DeprecationWarning,
            stacklevel=2,
        )
        if data:
            self.store_data(data)
        self.refresh_and_advance()
        return self

    def skip_onboarding(self):
        """Deprecated alias for :meth:`dismiss`.

        Old semantics also set ``current_step='completed'``, which
        we intentionally no longer do — dismiss is UI-only now.
        """
        import warnings
        warnings.warn(
            "OnboardingStatus.skip_onboarding() is deprecated. Use dismiss() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.dismiss()

    @classmethod
    def get_or_create_for_org(cls, organisation):
        """Get or create onboarding status for an organisation."""
        status, _ = cls.objects.get_or_create(organisation=organisation)
        return status
