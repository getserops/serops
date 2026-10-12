"""
Integration Models — Per-Org Observability Provider Configuration.

A single ObservabilityIntegration model supports both log and metric
providers, optionally sharing credentials (e.g. Datadog for both).
"""

import json
import logging

from cryptography.fernet import InvalidToken
from django.db import models
from django.db.models import Q
from Organisations.models import Organisations as Organisation
from providers.encryption import decrypt_value, encrypt_value, get_fernet

logger = logging.getLogger(__name__)


# ``extra_config`` keys that hold credentials. Their values are stored
# Fernet-encrypted, decrypted only in ``get_config()`` for the adapter, and
# never returned by the API — the serializers report which ones are set.
SECRET_EXTRA_CONFIG_KEYS = frozenset({
    'api_key', 'app_key', 'bearer_token', 'token', 'client_secret',
    'credentials_json',
})


def _is_encrypted(value: str) -> bool:
    # Uses Fernet directly: ``decrypt_value`` logs an error on every miss,
    # and a miss here is the normal case for a freshly entered secret.
    try:
        get_fernet().decrypt(value.encode('utf-8'))
    except (InvalidToken, ValueError, TypeError):
        return False
    return True


def encrypt_extra_config_secrets(extra_config: dict) -> dict:
    """Return ``extra_config`` with every secret value encrypted.

    Values that are already encrypted are left as they are, so saving a
    loaded row twice does not double-encrypt it. A dict value (a GCP
    service-account key pasted as JSON) is serialised first.
    """
    result = dict(extra_config or {})
    for key in SECRET_EXTRA_CONFIG_KEYS & result.keys():
        value = result[key]
        if isinstance(value, dict):
            value = json.dumps(value)
        if not isinstance(value, str) or not value:
            result.pop(key)
            continue
        result[key] = value if _is_encrypted(value) else encrypt_value(value)
    return result


# Maps provider code → which capabilities it can serve and their adapter classes.
ADAPTER_MAP = {
    # Log-only providers
    'elasticsearch': {
        'logs': 'integrations.adapters.elasticsearch.ElasticsearchLogProvider',
    },
    'opensearch': {
        'logs': 'integrations.adapters.opensearch.OpenSearchLogProvider',
    },
    'loki': {
        'logs': 'integrations.adapters.loki.LokiLogProvider',
    },
    'splunk': {
        'logs': 'integrations.adapters.splunk.SplunkLogProvider',
    },
    # Metric-only providers
    'prometheus': {
        'metrics': 'integrations.adapters.prometheus.PrometheusMetricProvider',
    },
    'victoriametrics': {
        'metrics': 'integrations.adapters.victoriametrics.VictoriaMetricsMetricProvider',
    },
    'mimir': {
        'metrics': 'integrations.adapters.mimir.MimirMetricProvider',
    },
    # Dual-capability providers
    'datadog': {
        'logs': 'integrations.adapters.datadog_logs.DatadogLogProvider',
        'metrics': 'integrations.adapters.datadog_metrics.DatadogMetricProvider',
        'traces': 'integrations.adapters.datadog_traces.DatadogTraceAdapter',
    },
    'cloudwatch': {
        'logs': 'integrations.adapters.cloudwatch_logs.CloudWatchLogProvider',
        'metrics': 'integrations.adapters.cloudwatch_metrics.CloudWatchMetricProvider',
    },
    'gcp': {
        'logs': 'integrations.adapters.gcp_logging.GcpCloudLoggingProvider',
        'metrics': 'integrations.adapters.gcp_monitoring.GcpCloudMonitoringProvider',
    },
    'azure': {
        'logs': 'integrations.adapters.azure_logs.AzureLogAnalyticsProvider',
        'metrics': 'integrations.adapters.azure_metrics.AzureMonitorProvider',
    },
    # Trace-only providers (pull adapters — for orgs that already ship
    # traces to Jaeger/Zipkin and don't want to switch to OTLP).
    'jaeger': {
        'traces': 'integrations.adapters.jaeger_traces.JaegerTraceAdapter',
    },
    'zipkin': {
        'traces': 'integrations.adapters.zipkin_traces.ZipkinTraceAdapter',
    },
    'tempo': {
        'traces': 'integrations.adapters.tempo_traces.TempoTraceAdapter',
    },
}


def _available_capabilities(provider: str) -> list:
    """Return the capabilities a provider supports (e.g. ['logs', 'metrics'])."""
    return list(ADAPTER_MAP.get(provider, {}).keys())


# ---------------------------------------------------------------------------
# Cluster — Item #17. A K8s (or bare-metal) cluster owned by an org.
# ---------------------------------------------------------------------------


class Cluster(models.Model):
    """
    A physical / logical cluster that produces observability data.

    An org may register many clusters — e.g. ``prod-eks``,
    ``staging-gke``, ``dev-kind``. Each ``ObservabilityIntegration``
    can optionally point at one cluster, so a user with per-cluster
    Prometheus / Loki / etc. can scope them correctly. Integrations
    with ``cluster = None`` are "unscoped" — they serve any cluster
    (backward-compat for existing single-cluster installs).

    Security:
    * ``organisation`` FK is CASCADE-deleted with the org.
    * ``kubernetes_context`` is a hint for humans / operators — we
      never shell out to kubectl using this string; it's stored as
      metadata for CLI users to correlate.
    """

    PROVIDER_CHOICES = [
        ('kubernetes', 'Generic Kubernetes'),
        ('eks', 'AWS EKS'),
        ('gke', 'Google GKE'),
        ('aks', 'Azure AKS'),
        ('openshift', 'OpenShift'),
        ('rke', 'Rancher RKE'),
        ('kind', 'kind (local)'),
        ('minikube', 'Minikube (local)'),
        ('bare_metal', 'Bare metal / VM (no K8s)'),
        ('other', 'Other'),
    ]

    organisation = models.ForeignKey(
        Organisation,
        on_delete=models.CASCADE,
        related_name='clusters',
    )
    name = models.CharField(
        max_length=100,
        help_text='Human-readable label (e.g. "prod-eks", "staging-gke"). '
                  'Unique per organisation.',
    )
    description = models.TextField(blank=True, default='')
    provider = models.CharField(
        max_length=32, choices=PROVIDER_CHOICES, default='kubernetes',
    )
    region = models.CharField(
        max_length=64, blank=True, default='',
        help_text='Optional cloud region (e.g. "us-west-2", "europe-west1").',
    )
    kubernetes_context = models.CharField(
        max_length=255, blank=True, default='',
        help_text='Optional kubectl context name — for humans, not used '
                  'by SerOps to connect (SerOps queries via Prometheus / '
                  'Loki / etc. as configured on the ObservabilityIntegration).',
    )
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'integrations_cluster'
        verbose_name = 'Cluster'
        verbose_name_plural = 'Clusters'
        constraints = [
            models.UniqueConstraint(
                fields=['organisation', 'name'],
                name='unique_cluster_name_per_org',
            ),
        ]
        indexes = [
            models.Index(fields=['organisation', 'is_active'], name='cluster_org_active_idx'),
        ]
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.get_provider_display()})'


class ObservabilityIntegration(models.Model):
    """
    Per-organisation observability integration.

    Replaces the separate LogIntegration / MetricIntegration models.
    A single Datadog record can serve both logs and metrics via the
    ``capabilities`` JSON field.
    """

    PROVIDER_CHOICES = [
        # Log-only
        ('elasticsearch', 'Elasticsearch'),
        ('opensearch', 'OpenSearch'),
        ('loki', 'Grafana Loki'),
        ('splunk', 'Splunk'),
        # Metric-only
        ('prometheus', 'Prometheus'),
        ('victoriametrics', 'VictoriaMetrics'),
        ('mimir', 'Grafana Mimir'),
        # Dual / triple
        ('datadog', 'Datadog'),
        ('cloudwatch', 'AWS CloudWatch'),
        ('gcp', 'Google Cloud Operations'),
        ('azure', 'Azure Monitor'),
        # Trace-only
        ('jaeger', 'Jaeger'),
        ('zipkin', 'Zipkin'),
        ('tempo', 'Grafana Tempo'),
    ]

    organisation = models.ForeignKey(
        Organisation,
        on_delete=models.CASCADE,
        related_name='observability_integrations',
    )
    # Optional cluster scope. NULL = "unscoped" — serves any cluster.
    # Distinguishes per-cluster Prometheus / Loki / etc. from a
    # single-cluster install where the integration is org-wide.
    cluster = models.ForeignKey(
        Cluster,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='observability_integrations',
        help_text='Which cluster this integration serves. Leave blank '
                  'to serve every cluster (single-cluster install).',
    )
    provider = models.CharField(max_length=50, choices=PROVIDER_CHOICES)
    display_name = models.CharField(max_length=100)
    capabilities = models.JSONField(
        default=list,
        help_text='Enabled capabilities, e.g. ["logs"], ["metrics"], or ["logs","metrics"].',
    )
    is_active = models.BooleanField(default=True)

    # Topology mode controls which metric queries the adapter builds.
    # - `vm`         → node/host-level metrics (`node_cpu_seconds_total`,
    #                  `node_memory_MemTotal_bytes`, ...). Correct for
    #                  bare-metal, VMs, EC2 instances, single-tenant hosts.
    # - `kubernetes` → container-level metrics aggregated by
    #                  `service_name` (`container_cpu_usage_seconds_total`,
    #                  `container_memory_working_set_bytes`, ...). Correct
    #                  for EKS/GKE/AKS clusters where pods are ephemeral
    #                  and workload-level rollups are what you care about.
    # Only affects metric providers; log providers ignore it.
    TOPOLOGY_MODE_CHOICES = [
        ('vm', 'VM / bare-metal (host-level metrics)'),
        ('kubernetes', 'Kubernetes (container-level metrics aggregated by service)'),
    ]
    topology_mode = models.CharField(
        max_length=16,
        choices=TOPOLOGY_MODE_CHOICES,
        default='vm',
        help_text='Metric-query topology. Set to `kubernetes` for EKS/GKE/AKS integrations.',
    )

    # Adapter class paths — auto-set from provider + capabilities on save.
    log_adapter_class = models.CharField(max_length=255, blank=True, default='')
    metric_adapter_class = models.CharField(max_length=255, blank=True, default='')
    trace_adapter_class = models.CharField(max_length=255, blank=True, default='')

    # Shared connection config
    host = models.CharField(max_length=500, blank=True, help_text='Provider host URL')
    username = models.CharField(max_length=255, blank=True)
    password = models.CharField(max_length=1000, blank=True, help_text='Encrypted at rest via Fernet')
    extra_config = models.JSONField(
        default=dict,
        blank=True,
        help_text='Additional provider-specific config (api_key, region, etc.)',
    )

    # Lifecycle controls
    timeout_seconds = models.IntegerField(default=30)
    max_retries = models.IntegerField(default=3)
    rate_limit_per_minute = models.IntegerField(default=60)

    # Priority tier for multi-source failover (Batch 48 — universal
    # deployment model). When ``_best_integration`` finds multiple
    # candidates with equal scope-match, ``primary`` wins. On adapter
    # error the pipeline retries the next-tier integration matching
    # the same scope. Three tiers cover "main + backup + emergency"
    # — extending to N is easy but three matches every real-world
    # topology I've seen (Prom primary + Datadog fallback +
    # CloudWatch tertiary is the classic HA setup).
    PRIORITY_TIER_CHOICES = [
        ('primary', 'Primary'),
        ('fallback', 'Fallback'),
        ('tertiary', 'Tertiary'),
    ]
    priority_tier = models.CharField(
        max_length=16,
        choices=PRIORITY_TIER_CHOICES,
        default='primary',
        help_text='Failover tier when multiple integrations match the same scope. '
                  'Primary is tried first; adapter error → try fallback → tertiary.',
    )

    # Health tracking
    last_health_check = models.DateTimeField(null=True, blank=True)
    last_health_status = models.BooleanField(null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Observability Integration'
        verbose_name_plural = 'Observability Integrations'
        # Uniqueness sliced by priority_tier (Batch 48) so users can
        # register the same-cluster same-provider integration once per
        # tier: e.g. Prom @ prod-eks primary + Prom @ prod-eks fallback
        # = 2 legitimate rows. Two constraints because SQL treats NULL
        # as distinct — the first covers cluster-scoped, the second
        # the unscoped fallback shape.
        constraints = [
            models.UniqueConstraint(
                fields=['organisation', 'provider', 'cluster', 'priority_tier'],
                condition=Q(cluster__isnull=False),
                name='unique_integration_per_cluster_tier',
            ),
            models.UniqueConstraint(
                fields=['organisation', 'provider', 'priority_tier'],
                condition=Q(cluster__isnull=True),
                name='unique_unscoped_integration_tier',
            ),
        ]
        ordering = ['-created_at']

    def __str__(self):
        caps = ', '.join(self.capabilities) if self.capabilities else 'none'
        return f'{self.organisation.name} → {self.get_provider_display()} ({caps})'

    def set_password(self, raw_password: str):
        """Encrypt and store a plaintext password."""
        if raw_password:
            self.password = encrypt_value(raw_password)
        else:
            self.password = ''

    def get_password(self) -> str:
        """Decrypt and return the stored password."""
        if not self.password:
            return ''
        try:
            return decrypt_value(self.password)
        except Exception:
            logger.warning('Failed to decrypt password for integration %s — returning empty', self.pk)
            return ''

    def save(self, *args, **kwargs):
        """Encrypt secret ``extra_config`` values and auto-populate adapter
        class paths from provider + capabilities."""
        self.extra_config = encrypt_extra_config_secrets(self.extra_config)
        adapters = ADAPTER_MAP.get(self.provider, {})
        if 'logs' in (self.capabilities or []):
            self.log_adapter_class = adapters.get('logs', '')
        else:
            self.log_adapter_class = ''
        if 'metrics' in (self.capabilities or []):
            self.metric_adapter_class = adapters.get('metrics', '')
        else:
            self.metric_adapter_class = ''
        if 'traces' in (self.capabilities or []):
            self.trace_adapter_class = adapters.get('traces', '')
        else:
            self.trace_adapter_class = ''
        super().save(*args, **kwargs)

    def get_config(self) -> dict:
        """Build config dict for adapter initialisation (password is decrypted).

        Includes ``topology_mode`` so metric adapters know whether to
        build VM-style or Kubernetes-style queries.
        """
        config = {
            'host': self.host,
            'username': self.username,
            'password': self.get_password(),
            'timeout_seconds': self.timeout_seconds,
            'max_retries': self.max_retries,
            'rate_limit_per_minute': self.rate_limit_per_minute,
            'topology_mode': self.topology_mode,
        }
        for key, value in (self.extra_config or {}).items():
            if key in SECRET_EXTRA_CONFIG_KEYS:
                try:
                    value = decrypt_value(value)
                except Exception:
                    logger.warning(
                        'Failed to decrypt %s for integration %s — omitting it',
                        key, self.pk,
                    )
                    continue
            config[key] = value
        return config

    def secret_fields_set(self) -> list:
        """Names of the secret ``extra_config`` keys that hold a value."""
        return sorted(SECRET_EXTRA_CONFIG_KEYS & (self.extra_config or {}).keys())


class IntegrationScope(models.Model):
    """Full scope tags for an ObservabilityIntegration (Batch 48).

    Universal-topology rework — replaces the "cluster-scope only" model
    (Batch 17) with the four orthogonal dimensions real enterprise
    topologies use:

      * ``cluster``     — mirrors ``ObservabilityIntegration.cluster``
                          for the transition; single source of truth
                          in future refactors will move here.
      * ``environment`` — free-text env name (production, staging, dev,
                          preview). Not an FK because ProjectEnvironment
                          is per-project — an integration scoped to
                          "production" applies across all projects with
                          that env name.
      * ``region``      — free-text region label (us-east-1, dc1, eu).
      * ``namespace``   — K8s namespace within the scoped cluster.

    Match precedence when ``_best_integration`` scores candidates:
    ``cluster > environment > region > namespace``. Ties broken by
    ``ObservabilityIntegration.priority_tier``.

    Constraints:
      * ``namespace`` requires ``cluster`` (namespaces exist within
        clusters — enforced by CheckConstraint at DB level).
      * 1:1 with ObservabilityIntegration.

    Data migration seeds one row per existing integration with only
    the ``cluster`` field populated (mirroring today's state). Users
    edit via the UI later to add env/region/namespace tags.
    """

    integration = models.OneToOneField(
        ObservabilityIntegration,
        on_delete=models.CASCADE,
        related_name='scope',
        primary_key=True,
    )
    cluster = models.ForeignKey(
        Cluster,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='integration_scopes',
        help_text='Optional cluster to serve. Mirrors ObservabilityIntegration.cluster '
                  'during the transition.',
    )
    environment = models.CharField(
        max_length=64, blank=True, default='',
        help_text='Free-text env name (e.g. "production"). Matches across projects '
                  'by name. Empty = wildcard.',
    )
    region = models.CharField(
        max_length=64, blank=True, default='',
        help_text='Free-text region label. Empty = wildcard.',
    )
    namespace = models.CharField(
        max_length=128, blank=True, default='',
        help_text='K8s namespace. Requires cluster set. Empty = wildcard.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'integration_scope'
        verbose_name = 'Integration Scope'
        verbose_name_plural = 'Integration Scopes'
        constraints = [
            # Same "namespace requires cluster" invariant as
            # ProjectDeployment — the two sides of the match MUST use
            # the same rule for match-scoring to work reliably.
            models.CheckConstraint(
                check=models.Q(namespace='') | models.Q(cluster__isnull=False),
                name='scope_namespace_requires_cluster',
            ),
        ]

    def __str__(self):
        parts = []
        if self.cluster_id:
            parts.append(f'cluster={self.cluster.name}')
        if self.environment:
            parts.append(f'env={self.environment}')
        if self.region:
            parts.append(f'region={self.region}')
        if self.namespace:
            parts.append(f'ns={self.namespace}')
        return ' · '.join(parts) if parts else 'unscoped'

    def fingerprint(self) -> tuple:
        """Comparable tuple for de-dup checks + uniqueness enforcement.

        (org_id, provider, cluster_id_or_none, env, region, namespace, priority_tier).
        Uniqueness is not enforced at the DB level on this table (would
        need cross-table constraint); the serializer enforces it at
        write time.
        """
        return (
            self.integration.organisation_id,
            self.integration.provider,
            self.cluster_id,
            self.environment,
            self.region,
            self.namespace,
            self.integration.priority_tier,
        )
