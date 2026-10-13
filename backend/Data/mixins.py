"""
Shared view mixins for the Data app.

Consolidates what used to be two separately-defined `OrgFilterMixin`
classes (one in ``Data/views.py``, one in ``Data/dashboard_views.py``)
into a single source of truth. Both files now import from here.

The two originals had different but overlapping method sets:
  - the views.py version had ``get_user_projects``, ``get_user_batches``,
    ``get_user_issues``, and a generic ``filter_by_org(qs, model_type)``
  - the dashboard_views.py version had ``get_user_org_id``,
    ``filter_batches_by_org(qs)``, and ``filter_issues_by_org(qs)``

Both had identical ``_get_environment(request)`` helpers. Merging the
two removes the divergence risk — a security fix or new helper method
can no longer accidentally land in only one copy.
"""

from .models import AIAnalyzedBatch, Issue
from Projects.models import Project


class OrgFilterMixin:
    """
    Provide organisation-based filtering for multi-tenant data isolation.

    All methods return an empty queryset for unauthenticated users or
    users without an assigned organisation. Callers should not need
    additional None-guards on the returned queryset.
    """

    # ------------------------------------------------------------------
    # Basic accessors
    # ------------------------------------------------------------------

    @staticmethod
    def get_user_org_id(request):
        """Org ID for cache keys + filtering. None if unauthenticated."""
        if not request.user.is_authenticated:
            return None
        org = getattr(request.user, 'organisation', None)
        return org.id if org else None

    def get_user_projects(self, request):
        """Every project belonging to the caller's org (empty queryset if none)."""
        if not request.user.is_authenticated:
            return Project.objects.none()
        user_org = getattr(request.user, 'organisation', None)
        if not user_org:
            return Project.objects.none()
        return Project.objects.filter(organisation=user_org)

    def get_user_batches(self, request):
        """
        Every batch belonging to the caller's org.

        Uses the direct ``AIAnalyzedBatch.organisation`` FK — no join
        via project. This is intentional: the org filter is a single-
        column index hit, and it correctly includes batches without a
        project (org-scoped batches that skip the project link).
        """
        if not request.user.is_authenticated:
            return AIAnalyzedBatch.objects.none()
        user_org = getattr(request.user, 'organisation', None)
        if not user_org:
            return AIAnalyzedBatch.objects.none()
        return AIAnalyzedBatch.objects.filter(organisation=user_org)

    def get_user_issues(self, request):
        """
        Every issue belonging to the caller's org.

        Uses the direct ``Issue.organisation`` FK. Same reasoning as
        get_user_batches — direct FK is faster and doesn't silently
        skip org-scoped issues that lack a project link.
        """
        if not request.user.is_authenticated:
            return Issue.objects.none()
        user_org = getattr(request.user, 'organisation', None)
        if not user_org:
            return Issue.objects.none()
        return Issue.objects.filter(organisation=user_org)

    # ------------------------------------------------------------------
    # Environment filter (optional query param)
    # ------------------------------------------------------------------

    @staticmethod
    def _get_environment(request):
        """
        Optional environment filter from query params.

        Returns None (no filter) for missing/empty/"all" values —
        that convention is baked into every dashboard endpoint and
        callers rely on it.
        """
        env = request.query_params.get('environment', '').strip().lower()
        return env if env and env != 'all' else None

    # ------------------------------------------------------------------
    # Cluster filter (optional query param)
    # ------------------------------------------------------------------

    @staticmethod
    def _get_cluster_id(request):
        """
        Optional cluster filter from query params. Returns an int, or
        None for missing/empty/"all"/unparseable values.

        Bad values resolve to None rather than raising: the cluster
        picker persists its selection in the browser, so a stale id
        can outlive the cluster it names. Returning None degrades to
        "all clusters" instead of 500-ing the dashboard on a filter
        the user cannot see to clear.
        """
        raw = getattr(request, 'query_params', {})
        raw = raw.get('cluster') if hasattr(raw, 'get') else None
        if not raw or str(raw).strip().lower() == 'all':
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # Generic queryset filter (env-aware)
    # ------------------------------------------------------------------

    def filter_by_org(self, request, queryset, model_type='batch'):
        """
        Filter any queryset by organisation, optional environment, and
        optional cluster.

        ``model_type`` is 'batch' or 'issue' — both models expose a
        direct ``organisation`` FK and an ``environment`` string field,
        so the filter is uniform. Non-matching model_type returns the
        original queryset unchanged (permissive default preserved from
        the original mixin).

        Cluster filter (Item #17 / Q1.4): when ``?cluster=<id>`` is
        present, additionally filter by ``project.cluster_id``. The
        relationship path differs slightly between models:
          * Batch → ``project__cluster_id``
          * Issue → ``batch__project__cluster_id``
        """
        if not request.user.is_authenticated:
            return queryset.none()
        user_org = getattr(request.user, 'organisation', None)
        if not user_org:
            return queryset.none()

        env = self._get_environment(request)

        if model_type in ('batch', 'issue'):
            qs = queryset.filter(organisation=user_org)
            if env:
                qs = qs.filter(environment__iexact=env)
            # Cluster filter — see _get_cluster_id for why bad values
            # degrade to "all clusters" rather than erroring.
            cid = self._get_cluster_id(request)
            if cid is not None:
                if model_type == 'batch':
                    qs = qs.filter(project__cluster_id=cid)
                else:
                    qs = qs.filter(batch__project__cluster_id=cid)
            return qs
        return queryset

    # Aliases kept for dashboard_views.py callers that used the
    # dashboard-flavoured names. Same behaviour as filter_by_org above,
    # just distinct entry points for callers who want an explicit name.

    def filter_batches_by_org(self, request, queryset):
        return self.filter_by_org(request, queryset, model_type='batch')

    def filter_issues_by_org(self, request, queryset):
        return self.filter_by_org(request, queryset, model_type='issue')
