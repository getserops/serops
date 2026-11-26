"""
seed_demo_org — build the read-only demo organisation from real analyses.

This command powers the public demo at https://app.serops.ai. It is
also useful when you self-host SerOps: running it once on a fresh
instance gives you a populated org, so you can explore every dashboard
and drill into issues without first wiring up observability providers.

The content is not written here. It is loaded from ``Data/demo_seed/``:
14 analyses SerOps made during its benchmark runs on test environments,
converted by ``tools/demo-seed/build_seed.py`` (format and renaming in
``tools/demo-seed/README.md``). What SerOps collected, what the model
answered and the issues it raised are stored as captured.

What it creates:

  - Organisations row "Acme Cloud" (``is_demo=True``) with the demo user
  - The people who started the investigations, as team members who
    cannot sign in
  - 3 projects (Fleet, Shopfront, Studio), their services, one
    environment and one cluster each
  - One AIAnalyzedBatch and its Investigation per seed file
  - The issues those analyses raised, one row per issue with one
    occurrence per analysis that raised it
  - The trace rows the seed files hold
  - Resolution notes from ``demo_seed/resolutions.json``, written by
    the SerOps team from the injection records, on the resolved issues
  - Chat sessions from ``demo_seed/chat/*.json``: three real conversations,
    asked through SerOps's own chat on a local instance; their token and
    cost figures stay in the files and are not loaded as spend
  - The stores each environment had connected, from
    ``demo_seed/integrations.json``: a type and a name per row, with no
    address, host or credential, so the Integrations page shows what the
    analyses read and nothing can be called

  - One delivery channel and one routing rule, so Alerts & routing shows
    how a critical incident reaches the on-call: a Slack channel whose
    webhook is the seed placeholder (the incident dispatcher never sends
    to it, and the API only says that a webhook is set) and a rule for
    critical issues in production

What it never creates: AI usage or cost rows (the captures hold none),
an AI budget, alert events, pipelines, a channel that can send, or an
integration pointing at a host.

Every analysis is moved by one whole number of days, so that the newest
falls on the day before the command runs and nothing is in the future.
Its batch id does not move: it is made from the seed file name
(``acme-fleet-k7-r1``), so a link to a demo analysis keeps working.

The command is **idempotent** — running it twice is safe. It wipes the
demo org's content and loads it again, and never touches any other
organisation.

Usage::

    python manage.py seed_demo_org             # fresh-build / nightly reset
    python manage.py seed_demo_org --dry-run   # report what would change
"""

from __future__ import annotations

import re
import uuid
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from Organisations.models import Organisations
from Users.models import User
from Projects.models import Project, ProjectDeployment, ProjectEnvironment, ProjectService
from providers.models import Pipeline, CodeChange, Deployment, ProviderIntegration
from Data import demo_seed_loader as seed_files
from Data.demo_seed_time import parse_time
from Data.models import AIAnalyzedBatch, Issue, IssueOccurrence, AuditLog, AlertEvent, Investigation, DataRunStatus
from ai_model.models import ChatSession, ChatMessage, AITokenUsage
from integrations.field_aliases import ENVIRONMENT_ALIASES, PROJECT_NAME_ALIASES, first_present
from integrations.models import ObservabilityIntegration, Cluster
from notifications.models import (
    Notification, ProjectSubscription, EscalationRule,
    IncidentNotificationChannel, NotificationRoutingRule,
)
from org_settings.encryption import encrypt_api_key
from org_settings.models import (
    OrganisationAISettings, OrganisationAPIKey, AIModelProvider, SentinelConfig,
)
from traces.models import IngestKey, Span, Trace


# ---------------------------------------------------------------------------
# Constants — pinned values so the demo is reproducible across runs
# ---------------------------------------------------------------------------

DEMO_ORG_NAME = 'Acme Cloud'
DEMO_ORG_SLUG = 'acme-cloud'

DEMO_USER_EMAIL = 'demo@serops.ai'
DEMO_USER_USERNAME = 'demo'
DEMO_USER_PASSWORD = 'demo'  # the demo is publicly accessible; password is informational

# The demo org's AI provider: the one that answered the seeded analyses.
# Its key row holds the placeholder (see ``_upsert_ai_key``) because the
# read-only demo never calls the provider. The model shown on a batch is
# the model id the seed file records (``model.used``), not this name.
DEMO_AI_PROVIDER = 'claude'

# Sentinel value stored in place of real credentials on demo records.
# Serializers detect this string and mask the response so no secret
# material ever leaves the API, and the incident dispatcher does not send
# to a channel that holds it.
SEED_DEMO_PLACEHOLDER = 'SEED_DEMO_PLACEHOLDER_NOT_A_REAL_SECRET'

# The on-call example on Alerts & routing (video v11, line 12).
DEMO_ONCALL_CHANNEL = 'Acme on-call (Slack)'
DEMO_ONCALL_RULE = 'Production critical to on-call'

# Team members get an address on a reserved domain (RFC 2606): no mail
# sent to it, a password reset link included, can reach anyone.
DEMO_MAIL_DOMAIN = 'acme.example'

DEMO_INGEST_KEY_NAME = 'otel-collector'

_SPAN_ID = re.compile(r'[0-9a-f]{16}')


def cluster_name(project_key: str) -> str:
    """The cluster of a project, named as the seed converter renames clusters."""
    return f'acme-{project_key}-cluster'


class Command(BaseCommand):
    help = 'Build (or rebuild) the public read-only Acme Cloud demo org.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would change without writing anything.',
        )

    def handle(self, *args, **opts):
        index = seed_files.load_index()
        if opts['dry_run']:
            self.stdout.write(self.style.NOTICE(
                f"[dry-run] Would rebuild the Acme Cloud demo org from {len(index['files'])} seed files."
            ))
            return

        captured = seed_files.load_seeds(index=index)
        now = self._now()
        delta = seed_files.whole_day_delta(captured, now)
        # Times move with the day the command runs; the batch id does not.
        seeds = [(name, seed_files.with_stable_batch_id(name, seed_files.shift_seed(doc, delta, index)))
                 for name, doc in captured]

        with transaction.atomic():
            org = self._upsert_org()
            user = self._upsert_user(org, now)
            team = self._upsert_team(org, seeds)

            # Wipe the content. This is what makes nightly reset safe:
            # projects, services, clusters and users are upserted by name
            # so their IDs do not churn, but batches, issues, traces and
            # chats are torn down and loaded again.
            self._wipe_dynamic_content(org)

            projects = self._upsert_topology(org, seeds)
            self._remove_old_structure(org, projects)
            self._upsert_integrations(org, projects)
            self._upsert_ingest_key(org)
            self._upsert_ai_settings(org)
            self._upsert_ai_key(org)
            self._upsert_sentinel_config(org)
            self._upsert_oncall_routing(org)

            batches = self._load_analyses(org, seeds, projects, team)
            issues = self._load_issues(org, seeds, delta, projects, batches, team)
            self._load_traces(org, seeds)
            self._load_chats(org, user, batches)

            self._seed_notifications(org, user, issues)
            self._seed_audit_log(org)

        counts = {
            'projects': Project.objects.filter(organisation=org).count(),
            'services': ProjectService.objects.filter(project__organisation=org).count(),
            'clusters': Cluster.objects.filter(organisation=org).count(),
            'batches': AIAnalyzedBatch.objects.filter(organisation=org).count(),
            'issues': Issue.objects.filter(organisation=org).count(),
            'occurrences': IssueOccurrence.objects.filter(issue__organisation=org).count(),
            'traces': Trace.objects.filter(organisation=org).count(),
            'team members': User.objects.filter(organisation=org, is_demo=False).count(),
            'chat sessions': ChatSession.objects.filter(user=user).count(),
        }
        self.stdout.write(self.style.SUCCESS(
            f"Demo org '{org.name}' rebuilt: " + ', '.join(f'{n} {label}' for label, n in counts.items())
            + f'. Analyses moved by {delta.days} days.'
        ))

    @staticmethod
    def _now():
        """The moment the analyses are placed against."""
        return timezone.now()

    # ── Org / users ────────────────────────────────────────────────────

    def _upsert_org(self) -> Organisations:
        from Organisations.models import OnboardingStatus

        org, _ = Organisations.objects.update_or_create(
            slug=DEMO_ORG_SLUG,
            defaults={
                'name': DEMO_ORG_NAME,
                'website': f'https://{DEMO_MAIL_DOMAIN}',
                'language': 'en',
                'is_demo': True,
            },
        )
        # Mark onboarding as finished so visitors land directly on the
        # dashboard instead of the wizard.
        status, _ = OnboardingStatus.objects.get_or_create(organisation=org)
        if not status.is_completed:
            status.is_completed = True
            status.current_step = 'completed'
            status.completed_at = timezone.now()
            status.completed_steps = [
                'connect_integration', 'create_project',
                'link_service', 'configure_logs',
            ]
            status.save()
        return org

    def _upsert_user(self, org: Organisations, now) -> User:
        user, created = User.objects.get_or_create(
            email=DEMO_USER_EMAIL,
            defaults={
                'username': DEMO_USER_USERNAME,
                'first_name': 'SerOps',
                'last_name': 'Demo',
                'role': 'admin',
                'is_active': True,
                'is_demo': True,
                'organisation': org,
            },
        )
        if not created:
            # Keep mutable fields aligned even on re-runs.
            user.username = DEMO_USER_USERNAME
            # admin role so demo visitors can *see* admin pages (Team,
            # Audit Log, Sentinel, AI settings, etc.). Writes are still
            # blocked by DemoUserMiddleware regardless of role — that
            # middleware is the security boundary here, not RBAC.
            user.role = 'admin'
            user.is_active = True
            user.is_demo = True
            user.organisation = org
            user.save()
        user.set_password(DEMO_USER_PASSWORD)
        # The demo sign-in issues a token without touching last_login, and
        # the Team page shows a member with none as "Pending".
        user.last_login = now
        user.save(update_fields=['password', 'last_login'])
        return user

    def _upsert_team(self, org: Organisations, seeds) -> dict[str, User]:
        """The people who started the seeded investigations, as team members.

        Their names are the invented ones the seed converter gave them.
        They are not the demo identity: ``is_demo`` stays False, because
        the demo sign-in takes the first active ``is_demo`` user of the
        org and must keep finding the demo user. They cannot sign in:
        the password is unusable and the address is on a reserved domain.
        """
        last_run: dict = {}
        for _, doc in seeds:
            inv = doc['investigation']
            if inv.get('requested_by'):
                started = parse_time(inv['created_at'])
                last_run[inv['requested_by']] = max(started, last_run.get(inv['requested_by'], started))

        team: dict[str, User] = {}
        emails = []
        for name in seed_files.requesters(seeds):
            first_name, _, last_name = name.partition(' ')
            alias = name.lower().replace('. ', '.').replace(' ', '.')
            email = f'{alias}@{DEMO_MAIL_DOMAIN}'
            member = User.objects.filter(email=email).first()
            if member is not None and member.organisation_id != org.id:
                # Somebody else's account: never taken over. The
                # investigations of this person load without a requester.
                continue
            if member is None:
                member = User(email=email)
            member.username = alias[:20]
            member.first_name = first_name
            member.last_name = last_name
            member.role = 'user'
            member.is_active = True
            member.is_demo = False
            member.organisation = org
            member.set_unusable_password()
            # Active on the Team page: last seen when they last started an investigation.
            member.last_login = last_run[name]
            member.save()
            team[name] = member
            emails.append(email)

        # A member a previous version of the seed files named and this one does not.
        User.objects.filter(
            organisation=org, is_demo=False, email__endswith=f'@{DEMO_MAIL_DOMAIN}',
        ).exclude(email__in=emails).delete()
        return team

    # ── Projects, services, clusters ───────────────────────────────────

    def _upsert_topology(self, org: Organisations, seeds) -> dict[str, dict]:
        """Projects, their services, environment, cluster and deployment,
        all read from the seed files. Returns, per project key, the rows
        the loaders attach batches to."""
        services = seed_files.project_services(seeds)
        specs: dict[str, dict] = {}
        for _, doc in seeds:
            specs.setdefault(doc['project']['key'], doc['project'])

        projects: dict[str, dict] = {}
        for key, spec in specs.items():
            cluster, _ = Cluster.objects.update_or_create(
                organisation=org, name=cluster_name(key),
                defaults={'description': '', 'provider': 'kubernetes', 'region': '',
                          'kubernetes_context': '', 'is_active': True},
            )
            project, _ = Project.objects.update_or_create(
                name=spec['name'], organisation=org,
                defaults={'description': '', 'cluster': cluster},
            )
            for name in services.get(key, []):
                ProjectService.objects.update_or_create(
                    project=project, name=name,
                    defaults={'service_type': 'application', 'subtype': '', 'description': '', 'status': 'Active'},
                )
            ProjectService.objects.filter(project=project).exclude(name__in=services.get(key, [])).delete()

            # Creating the environment creates its deployment on the
            # project's cluster (Projects/signals.py); the get_or_create
            # below covers an environment that existed before.
            environment, _ = ProjectEnvironment.objects.update_or_create(
                project=project, name=spec['environment'],
                defaults={'display_name': spec['environment'].capitalize(), 'is_active': True,
                          'log_label_value': spec['environment']},
            )
            ProjectEnvironment.objects.filter(project=project).exclude(pk=environment.pk).delete()
            deployment, _ = ProjectDeployment.objects.get_or_create(
                project=project, environment=environment, cluster=cluster, region='', namespace='',
                defaults={'is_active': True},
            )
            ProjectDeployment.objects.filter(project=project).exclude(pk=deployment.pk).delete()
            projects[key] = {'project': project, 'environment': environment,
                             'deployment': deployment, 'cluster': cluster}
        return projects

    def _remove_old_structure(self, org: Organisations, projects: dict[str, dict]) -> None:
        """Drop what an earlier version of this command created and this
        one does not: the hand-written projects and clusters, the
        integrations that pointed at hosts which never existed, and the
        placeholder notification channels (Slack, PagerDuty, OpsGenie)
        no test environment had. The integration rows the demo shows are
        written again, without address or credential, by
        ``_upsert_integrations``."""
        keep_projects = [p['project'].pk for p in projects.values()]
        keep_clusters = [p['cluster'].pk for p in projects.values()]
        Project.objects.filter(organisation=org).exclude(pk__in=keep_projects).delete()
        ObservabilityIntegration.objects.filter(organisation=org).delete()
        # Service bindings (SCMBinding, CICDBinding) go with their integration.
        ProviderIntegration.objects.filter(organisation=org).delete()
        IncidentNotificationChannel.objects.filter(organisation=org).delete()
        Cluster.objects.filter(organisation=org).exclude(pk__in=keep_clusters).delete()
        IngestKey.objects.filter(organisation=org).exclude(name=DEMO_INGEST_KEY_NAME).delete()

    def _upsert_oncall_routing(self, org: Organisations) -> None:
        """One Slack channel and one routing rule for critical issues in
        production. Runs after ``_remove_old_structure``, which deletes the
        organisation's channels, so the channel is written again each run;
        the rule keeps its id. The webhook is ``SEED_DEMO_PLACEHOLDER``:
        ``incident_dispatcher`` never sends to a channel holding it. The
        rule filters on severity and environment only (its service filter
        is compared with the project name)."""
        channel = IncidentNotificationChannel(
            organisation=org, name=DEMO_ONCALL_CHANNEL, kind='slack',
            min_severity='CRITICAL', trigger_events=[], is_active=True,
        )
        channel.set_webhook_url(SEED_DEMO_PLACEHOLDER)
        channel.save()
        rule, _ = NotificationRoutingRule.objects.update_or_create(
            organisation=org, name=DEMO_ONCALL_RULE,
            defaults={
                'is_active': True, 'min_severity': 'CRITICAL',
                'environments': ['production'], 'services': [], 'event_types': [],
            },
        )
        rule.targets.set([channel])

    # ── Integrations: what each environment had connected ─────────────

    def _upsert_integrations(self, org: Organisations, projects: dict[str, dict]) -> None:
        """One row per store an environment really had connected, so the
        Integrations page shows what the analyses read. A row is a type
        and a name: no host, no user name, no password, no token. Nothing
        is called through it: the registry, the health checks and the
        syncs all leave demo organisations out."""
        specs = seed_files.load_integrations()
        for key, rows in specs.items():
            if key not in projects:
                continue
            cluster = projects[key]['cluster']
            for spec in rows.get('observability', []):
                ObservabilityIntegration.objects.create(
                    organisation=org, cluster=cluster, provider=spec['provider'],
                    display_name=spec['display_name'], capabilities=list(spec['capabilities']),
                    topology_mode='kubernetes', is_active=True,
                    host='', username='', password='', extra_config={},
                )
            for spec in rows.get('delivery', []):
                integration = ProviderIntegration(
                    organisation=org, provider_type=spec['provider_type'], name=spec['name'],
                    category=spec['category'], base_url=None, credentials={}, token_hint='',
                    is_active=True,
                )
                integration.capabilities = integration.get_default_capabilities()
                integration.save()

    # ── OTLP ingest key (Item #10) ────────────────────────────────────

    def _upsert_ingest_key(self, org: Organisations) -> None:
        """Ensure one active OTLP IngestKey exists so Settings → Traces
        renders a real row instead of the empty state.

        The plaintext key is thrown away — only the hash is stored
        (GitHub PAT model).
        """
        # Idempotent by name — if a key already exists, leave it alone
        # (its hash is stable across rebuilds).
        if IngestKey.objects.filter(organisation=org, name=DEMO_INGEST_KEY_NAME).exists():
            return
        plaintext = IngestKey.generate_key()
        key = IngestKey(
            organisation=org,
            name=DEMO_INGEST_KEY_NAME,
            is_active=True,
        )
        key.set_key(plaintext)
        key.save()

    # ── AI provider, Sentinel ─────────────────────────────────────────

    def _upsert_ai_settings(self, org: Organisations) -> None:
        """Claude as the primary provider, and no monthly budget: the
        seed holds no spend, so a budget gauge would show an invented cap
        over an empty figure. An earlier seed wrote $100; it is cleared.
        """
        # If the catalogue has no claude row, leave the provider unset.
        default_provider = AIModelProvider.objects.filter(name=DEMO_AI_PROVIDER).first()

        OrganisationAISettings.objects.update_or_create(
            organisation=org,
            defaults={
                'default_provider': default_provider,
                'fallback_provider': None,
                'monthly_budget_usd': None,
                'budget_warn_pct': 80,
                'use_custom_keys': False,
            },
        )

    def _upsert_sentinel_config(self, org: Organisations) -> None:
        """Active mode, the default. Kept right even if a reseed meets a
        row someone switched to shadow mode."""
        SentinelConfig.objects.update_or_create(
            organisation=org, defaults={'active_mode': True},
        )

    def _upsert_ai_key(self, org: Organisations) -> None:
        """Give the demo org a Claude key row so Claude shows as available.

        The chat model picker and Settings → AI list only providers the org
        holds a decryptable key for. The demo used to rely on a real key
        entered by hand, encrypted with the SECRET_KEY of the day; rotating
        SECRET_KEY made it undecryptable and the picker showed "No AI
        provider" from then on. The demo never calls the provider — the
        middleware rejects every write a demo user makes, chat and
        re-analysis included — so it needs no real key. Seeding the
        placeholder here, encrypted with the current SECRET_KEY, re-heals
        the row on every nightly reset.
        """
        provider = AIModelProvider.objects.filter(name=DEMO_AI_PROVIDER).first()
        if provider is None:
            return
        OrganisationAPIKey.objects.update_or_create(
            organisation=org,
            provider=provider,
            defaults={
                'api_key': encrypt_api_key(SEED_DEMO_PLACEHOLDER),
                'base_url': None,
                'extra_config': {},
                'is_active': True,
            },
        )
        # The placeholder row of the provider an earlier seed used.
        OrganisationAPIKey.objects.filter(organisation=org).exclude(provider=provider).delete()

    # ── Wipe / rebuild ─────────────────────────────────────────────────

    def _wipe_dynamic_content(self, org: Organisations) -> None:
        """Drop every content row scoped to the demo org so the rebuild
        starts from a clean slate, including what earlier versions of
        this command created and this one no longer does (alert events,
        pipelines, code changes, AI usage rows). Projects, services,
        clusters and users are handled by the ``_upsert_*`` helpers.
        """
        Notification.objects.filter(user__organisation=org).delete()
        ProjectSubscription.objects.filter(user__organisation=org).delete()
        EscalationRule.objects.filter(organisation=org).delete()
        AuditLog.objects.filter(organisation=org).delete()
        ChatMessage.objects.filter(chat_session__user__organisation=org).delete()
        ChatSession.objects.filter(user__organisation=org).delete()
        AITokenUsage.objects.filter(organisation=org).delete()
        AlertEvent.objects.filter(organisation=org).delete()
        Investigation.objects.filter(organisation=org).delete()
        Trace.objects.filter(organisation=org).delete()
        Issue.objects.filter(organisation=org).delete()
        AIAnalyzedBatch.objects.filter(organisation=org).delete()
        # Deployments cascade from CodeChange, so kill them explicitly
        # first so nothing races the CodeChange delete.
        Deployment.objects.filter(code_change__organisation=org).delete()
        CodeChange.objects.filter(organisation=org).delete()
        Pipeline.objects.filter(organisation=org).delete()
        # Scheduler outcomes written before demo organisations were left out
        # of scheduled runs ("Skipped: no log location", every minute).
        DataRunStatus.objects.filter(project__organisation=org).delete()

    # ── Analyses ───────────────────────────────────────────────────────

    def _load_analyses(self, org, seeds, projects, team) -> dict[str, AIAnalyzedBatch]:
        """One Investigation and one AIAnalyzedBatch per seed file, as
        captured. Returns the batches by seed id."""
        batches: dict[str, AIAnalyzedBatch] = {}
        for name, doc in seeds:
            target = projects[doc['project']['key']]
            captured, inv_doc = doc['batch'], doc['investigation']
            model_used = doc['model']['used']

            inv = Investigation.objects.create(
                organisation=org, requested_by=team.get(inv_doc.get('requested_by')),
                project=target['project'], environment=target['environment'],
                services=inv_doc.get('services') or [],
                window_start=parse_time(inv_doc['window_start']), window_end=parse_time(inv_doc['window_end']),
                hint=inv_doc.get('hint') or '', notify_routing=bool(inv_doc.get('notify_routing')),
                status=inv_doc['status'], counts=inv_doc.get('counts') or {},
                error_code=inv_doc.get('error_code') or '', error=inv_doc.get('error') or '',
                started_at=_time(inv_doc.get('started_at')), finished_at=_time(inv_doc.get('finished_at')),
            )
            # auto_now_add ignores the value on create.
            Investigation.objects.filter(pk=inv.pk).update(created_at=parse_time(inv_doc['created_at']))

            data = dict(captured['data'])
            # The log lines are a sample of what the analysis read (see
            # "Log trim" in the seed README): the page says how many.
            data['logs_kept'] = doc['trim']['logs_kept']
            data['logs_total'] = doc['trim']['logs_total']
            batch = AIAnalyzedBatch.objects.create(
                batch_id=captured['batch_id'],
                timestamp=parse_time(captured['timestamp']),
                project=target['project'], organisation=org,
                environment=target['environment'].name, deployment=target['deployment'],
                investigation=inv, trigger=captured['trigger'],
                sentinel_decision=captured['sentinel_decision'],
                sentinel_triggers=captured.get('sentinel_triggers') or [],
                ai_skipped=bool(captured.get('ai_skipped')),
                issue_count=captured.get('issue_count') or 0,
                data=data,
                logs_analyzed=captured.get('logs_analyzed') or 0,
                indices_covered=captured.get('indices_covered') or [],
                # A size estimate of the batch text, as captured. Not model usage.
                token_count=captured.get('token_count') or 0,
                analysis_text=captured.get('analysis_text'),
                analyzed_at=_time(captured.get('analyzed_at')),
                # The batch row stored the provider name; the page shows
                # the model that answered.
                model_name=model_used,
                analysis_history=[dict(entry, model_name=model_used)
                                  for entry in captured.get('analysis_history') or []],
                logs_raw_count=captured.get('logs_raw_count'),
                logs_after_severity_filter=captured.get('logs_after_severity_filter'),
                logs_unique_patterns=captured.get('logs_unique_patterns'),
                logs_sent_to_ai=captured.get('logs_sent_to_ai'),
            )
            AIAnalyzedBatch.objects.filter(pk=batch.pk).update(created_at=parse_time(captured['created_at']))
            batch.refresh_from_db()
            batches[name] = batch
        return batches

    # ── Issues ─────────────────────────────────────────────────────────

    def _load_issues(self, org, seeds, delta, projects, batches, team) -> list[Issue]:
        """One Issue per issue of the seed files, with one occurrence per
        analysis that raised it.

        The row is written as its last analysis left it. Three values
        follow the seeded set instead of the run (the replaced values
        are in ``demo_seed/replaced-values.json``): ``occurrence_count``
        is the number of seeded analyses that raised the issue,
        ``created_at`` when the first of them wrote it, ``last_seen_at``
        when the last one did.

        The resolution notes come from ``demo_seed/resolutions.json``.
        They are the team's notes, stored in the resolution fields with
        a team member as ``resolved_by``; the AI's own text is untouched.
        """
        docs = dict(seeds)
        resolutions = seed_files.load_resolutions()
        issues: list[Issue] = []
        for entry in seed_files.merge_issues(seeds):
            sightings = entry['sightings']
            first, last = sightings[0], sightings[-1]
            row, last_doc = last['issue'], docs[last['seed']]
            project = projects[last_doc['project']['key']]['project']

            issue = Issue(
                batch=batches[last['seed']], project=project, organisation=org,
                severity=row['severity'], description=row['description'],
                recommendation=row.get('recommendation'), root_cause=row.get('root_cause'),
                reasoning=row.get('reasoning'), confidence=row.get('confidence') or '',
                issue_type=row['issue_type'], scope=row['scope'], component=row.get('component') or '',
                affected_services=row.get('affected_services') or [],
                environment=row.get('environment') or '',
                # Created open: saving a resolved issue queues an embedding
                # of it, which is a call to an AI provider.
                status='OPEN',
                error_class=row.get('error_class') or '', error_target=row.get('error_target') or '',
                correlation_details=row.get('correlation_details') or {},
            )
            issue.fingerprint = Issue.generate_fingerprint(
                issue.issue_type, issue.scope, project.name, issue.component, issue.environment,
                issue.error_class, issue.error_target,
            )
            issue.save()

            # save() derives the correlation fields from the issue text;
            # the captured ones are what the analysis pipeline wrote.
            values = {
                'created_at': parse_time(seed_files.first_seen(first, docs[first['seed']])),
                'last_seen_at': parse_time(row['last_seen_at']),
                'occurrence_count': len(sightings),
                'has_commit_correlation': bool(row.get('has_commit_correlation')),
                'has_metric_correlation': bool(row.get('has_metric_correlation')),
                'has_cicd_correlation': bool(row.get('has_cicd_correlation')),
                'linked_commits': row.get('linked_commits') or [],
                'metric_correlation_type': row.get('metric_correlation_type') or '',
                'metric_anomaly_type': row.get('metric_anomaly_type') or '',
                'correlation_confidence': row.get('correlation_confidence') or '',
                'correlation_details': row.get('correlation_details') or {},
            }
            resolution = resolutions.get(entry['capture_ref'])
            if resolution and not resolution.get('keep_open'):
                values.update(
                    status='RESOLVED',
                    resolved_at=seed_files.shift_iso(resolution['resolved_at'], delta),
                    resolved_by=team.get(last_doc['investigation'].get('requested_by')),
                    resolution_root_cause=resolution['resolution_root_cause'],
                    resolution_fix=resolution['resolution_fix'],
                )
            Issue.objects.filter(pk=issue.pk).update(**values)

            # The batch's issue list reads through occurrences, not
            # Issue.batch: each analysis lists the issue at the severity
            # and type it reported.
            for sighting in sightings:
                occurrence = IssueOccurrence.objects.create(
                    issue=issue, batch=batches[sighting['seed']],
                    severity=sighting['issue']['severity'], issue_type=sighting['issue']['issue_type'],
                )
                IssueOccurrence.objects.filter(pk=occurrence.pk).update(
                    seen_at=parse_time(sighting['issue']['last_seen_at']))
            issue.refresh_from_db()
            issues.append(issue)
        return issues

    # ── Traces ─────────────────────────────────────────────────────────

    @staticmethod
    def _load_traces(org: Organisations, seeds) -> None:
        """Store the trace rows the seed files hold. No span is made up:
        a trace id an analysis cites that has no row in its file stays
        without one, and the pages show that id as text."""
        seen: set[str] = set()
        for _, doc in seeds:
            for item in (doc.get('traces') or {}).get('items') or []:
                if item['trace_id'] in seen:
                    continue
                seen.add(item['trace_id'])
                # A span id that SerOps' redaction masked when the capture
                # was taken (16 digits, taken for a card number) no longer
                # names its span: that trace is left out, not patched.
                if any(not _SPAN_ID.fullmatch(span.get('span_id') or '') for span in item.get('spans') or []):
                    continue
                trace = Trace.objects.create(
                    trace_id=item['trace_id'], organisation=org,
                    root_service_name=item.get('root_service_name') or '',
                    root_operation=(item.get('root_operation') or '')[:255],
                    start_time=parse_time(item['start_time']), end_time=parse_time(item['end_time']),
                    duration_ms=item.get('duration_ms') or 0,
                    span_count=item.get('span_count') or 0,
                    error_span_count=item.get('error_span_count') or 0,
                    status_code=item.get('status_code') or 'UNSET',
                )
                Trace.objects.filter(pk=trace.pk).update(created_at=parse_time(item['start_time']))
                Span.objects.bulk_create([
                    Span(
                        trace=trace, span_id=span['span_id'],
                        parent_span_id=span.get('parent_span_id') or '',
                        service_name=span.get('service_name') or '',
                        operation_name=(span.get('operation_name') or '')[:255],
                        kind=span.get('kind') or 'INTERNAL',
                        start_time=parse_time(span['start_time']), end_time=parse_time(span['end_time']),
                        duration_ms=span.get('duration_ms') or 0,
                        status_code=span.get('status_code') or 'UNSET',
                        status_message=(span.get('status_message') or '')[:500],
                        attributes=span.get('attributes') or {},
                        events=span.get('events') or [],
                        # As the OTLP receiver reads them from the attributes.
                        environment=str(first_present(
                            span.get('attributes') or {}, ENVIRONMENT_ALIASES, default='') or '').strip().lower()[:64],
                        project_name=str(first_present(
                            span.get('attributes') or {}, PROJECT_NAME_ALIASES, default='') or '').strip()[:255],
                    )
                    for span in item.get('spans') or []
                ])

    # ── Chat sessions ─────────────────────────────────────────────────

    @staticmethod
    def _load_chats(org: Organisations, user: User, batches: dict[str, AIAnalyzedBatch]) -> None:
        """Load ``demo_seed/chat/*.json`` when there are any (format in
        ``demo_seed_loader.load_chats``). A session belongs to the demo
        user, so it shows in the visitor's chat history."""
        for chat in seed_files.load_chats():
            batch = batches.get(chat.get('batch'))
            if batch is None:
                continue
            exchanges = seed_files.chat_exchanges(chat)
            base = batch.analyzed_at or batch.timestamp
            session = ChatSession.objects.create(
                chat_id=uuid.uuid4(),
                user=user,
                title=chat.get('title') or '',
                batch_id=batch.batch_id,
                project_id=str(batch.project_id) if batch.project_id else None,
                # is_active=False is how a deleted session is stored; the
                # history list hides those, so seeded sessions stay active.
                is_active=True,
            )
            times = [base + timedelta(seconds=offset) for _, _, offset in exchanges] or [base]
            for (question, answer, _), at in zip(exchanges, times):
                message = ChatMessage.objects.create(
                    chat_session=session, message=question, response=answer,
                    metadata={'ai_model': chat.get('model') or ''},
                )
                ChatMessage.objects.filter(pk=message.pk).update(timestamp=at)
            ChatSession.objects.filter(pk=session.pk).update(created_at=times[0], last_message_at=times[-1])

    # ── Notifications, audit log ──────────────────────────────────────

    def _seed_notifications(self, org: Organisations, user: User, issues: list[Issue]) -> None:
        """One unread notification per open CRITICAL issue so the bell
        icon has an unread badge on load, and one read digest whose
        figures are counted from the issues just loaded.
        """
        still_open = [i for i in issues if i.status == 'OPEN']
        resolved = [i for i in issues if i.status == 'RESOLVED']
        for issue in still_open:
            if issue.severity != 'CRITICAL':
                continue
            Notification.objects.create(
                user=user,
                subject=f'[CRITICAL] {issue.issue_type} on {issue.component}',
                message=issue.description[:200] if issue.description else '',
                notification_type='critical_issue',
                batch_id=issue.batch.batch_id,
                issue=issue,
                is_read=False,
            )
        project_names = sorted({i.project.name for i in issues})
        Notification.objects.create(
            user=user,
            subject=f'Digest: {len(resolved)} issues resolved, {len(still_open)} open',
            message=(
                f'The analyses shown here raised {len(issues)} issues across {", ".join(project_names)}. '
                f'{len(resolved)} are resolved and {len(still_open)} are open'
                + (': ' + ', '.join(sorted(i.component for i in still_open)) if still_open else '') + '.'
            ),
            notification_type='digest',
            is_read=True,
        )

        # Subscribe the demo user to every project so the Notification
        # Preferences page shows rows instead of an empty state.
        for project in Project.objects.filter(organisation=org):
            ProjectSubscription.objects.update_or_create(
                user=user,
                project=project,
                defaults={
                    'notify_critical': True,
                    'notify_warning': True,
                    'notify_info': False,
                },
            )

        # One escalation rule so Settings → Escalation Rules isn't
        # empty. Applies org-wide for CRITICAL severity.
        EscalationRule.objects.update_or_create(
            organisation=org,
            project=None,
            severity='CRITICAL',
            defaults={
                'level_1_delay_minutes': 15,
                'level_2_delay_minutes': 45,
                'is_active': True,
            },
        )

    def _seed_audit_log(self, org: Organisations) -> None:
        """The audit entry each seeded investigation left when it was
        started, with the details the product records for one
        (Data/investigation_views.py). Nothing else is written: the demo
        has no other recorded action.
        """
        for inv in Investigation.objects.filter(organisation=org).select_related('requested_by'):
            entry = AuditLog.objects.create(
                organisation=org,
                user=inv.requested_by,
                action='INVESTIGATION_RUN',
                details={
                    'investigation_id': inv.id, 'project_id': inv.project_id,
                    'window_start': inv.window_start.isoformat(), 'window_end': inv.window_end.isoformat(),
                },
            )
            # created_at is auto_now_add — override in a second pass.
            AuditLog.objects.filter(pk=entry.pk).update(created_at=inv.created_at)


def _time(value):
    return parse_time(value) if value else None
