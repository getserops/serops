from rest_framework import serializers
from .models import AIAnalyzedBatch, Issue

class IssueSerializer(serializers.ModelSerializer):
    batch_timestamp = serializers.DateTimeField(source='batch.timestamp', read_only=True)
    batch_id_str = serializers.CharField(source='batch.batch_id', read_only=True)
    issue_type_display = serializers.CharField(source='get_issue_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    error_class_display = serializers.CharField(source='get_error_class_display', read_only=True)
    confidence_display = serializers.CharField(source='get_confidence_display', read_only=True)
    project_name = serializers.CharField(source='project.name', read_only=True, default=None)
    resolved_by_name = serializers.SerializerMethodField()

    # Correlation summary (computed from pre-computed model fields)
    correlation_summary = serializers.SerializerMethodField()

    # "Informed by past resolutions" — the AI prompt for this batch was
    # primed with resolved-issue context. Surface a short digest so the
    # UI can show "Informed by N past resolutions" with a tooltip.
    informed_by = serializers.SerializerMethodField()

    # Related distributed traces — surfaces the top-slow + top-error
    # spans from the issue's originating batch. Empty dict when the
    # batch has no trace snapshot (org has no trace source, or the
    # batch predates #10.5). Lets the Issue detail page render a
    # "Related traces" card without a follow-up request.
    related_traces = serializers.SerializerMethodField()

    class Meta:
        model = Issue
        fields = [
            'id', 'batch', 'batch_id_str', 'batch_timestamp',
            'severity', 'description', 'recommendation', 'root_cause',
            # AI evidence chain + confidence
            'reasoning', 'confidence', 'confidence_display',
            'created_at',
            # v2 deduplication fields
            'issue_type', 'issue_type_display', 'scope', 'component', 'affected_services', 'environment',
            'status', 'status_display', 'occurrence_count', 'muted_until', 'last_seen_at',
            'acknowledged_at', 'project', 'project_name',
            # v3 AI classification fields
            'error_class', 'error_class_display', 'error_target',
            # v4 Pre-computed correlation fields (from model)
            'has_commit_correlation', 'has_metric_correlation',
            'linked_commits', 'metric_correlation_type',
            # v5 Engine-driven correlation fields
            'correlation_confidence', 'metric_anomaly_type', 'correlation_details',
            'has_cicd_correlation',
            'correlation_summary',
            'informed_by',
            # Resolution: who, when, and what the team says happened
            'resolved_at', 'resolved_by_name', 'resolution_root_cause', 'resolution_fix',
            'related_traces',
        ]
        # Issues are written by the analysis pipeline, never through this
        # serializer: their batch and project are output only.
        read_only_fields = ['batch', 'project']
    
    def get_resolved_by_name(self, obj):
        user = obj.resolved_by
        if not user:
            return None
        return f'{user.first_name} {user.last_name}'.strip() or user.email

    def get_correlation_summary(self, obj):
        """Build correlation summary from pre-computed model fields."""
        summary = []

        # Use pre-computed linked_commits from model
        if obj.has_commit_correlation and obj.linked_commits:
            first_commit = obj.linked_commits[0] if obj.linked_commits else {}
            sha = first_commit.get('sha', '')[:8] if isinstance(first_commit, dict) else str(first_commit)[:8]
            if sha:
                entry = {'type': 'commit', 'value': sha}
                if obj.correlation_confidence:
                    entry['confidence'] = obj.correlation_confidence
                summary.append(entry)

        # Use pre-computed metric correlation from model
        if obj.has_metric_correlation and obj.metric_correlation_type:
            entry = {
                'type': 'metric',
                'value': obj.metric_correlation_type,
                'anomaly_type': obj.metric_anomaly_type or '',
            }
            if obj.correlation_confidence:
                entry['confidence'] = obj.correlation_confidence
            # Include peak value and duration from correlation_details
            metric_detail = (obj.correlation_details or {}).get('metric_anomaly', {})
            if metric_detail:
                if metric_detail.get('peak_value') is not None:
                    entry['peak_value'] = metric_detail['peak_value']
                if metric_detail.get('duration_seconds'):
                    entry['duration_seconds'] = metric_detail['duration_seconds']
            summary.append(entry)

        # CI/CD pipeline failure correlation
        if obj.has_cicd_correlation:
            cicd_detail = (obj.correlation_details or {}).get('cicd_correlation', {})
            entry = {
                'type': 'cicd',
                'value': cicd_detail.get('job_name', 'pipeline'),
                'pipeline_id': cicd_detail.get('pipeline_id', ''),
            }
            if cicd_detail.get('confidence'):
                entry['confidence'] = cicd_detail['confidence']
            summary.append(entry)

        return summary

    def get_related_traces(self, obj):
        """Compact trace digest for the Issue detail page.

        Prefers the issue's OWN service (obj.component) when picking
        top-slow / top-error spans — those are the ones most likely to
        be causally related to *this* issue rather than to some
        unrelated spike in the same batch. Falls back to the batch-
        level top-N when no service match is found.

        Returns::

            {
                "trace_count": int,
                "span_count": int,
                "error_span_count": int,
                "top_slow": [{trace_id, service_name, operation_name, duration_ms}, ...],
                "top_errors": [{trace_id, service_name, operation_name, status_message}, ...]
            }

        Or ``{"trace_count": 0, ...}`` when the batch has no snapshot.
        """
        empty = {
            'trace_count': 0, 'span_count': 0, 'error_span_count': 0,
            'top_slow': [], 'top_errors': [],
        }
        batch = getattr(obj, 'batch', None)
        if batch is None or not isinstance(getattr(batch, 'data', None), dict):
            return empty
        traces = batch.data.get('traces')
        if not isinstance(traces, dict) or not traces.get('span_count'):
            return empty

        # Prefer spans in this issue's service, if we know it.
        issue_service = (obj.component or '').strip().lower()

        def _filter_to_service(items):
            if not issue_service:
                return items
            matching = [
                s for s in items
                if str(s.get('service_name') or '').lower() == issue_service
            ]
            return matching or items   # fall back to full set

        top_slow = _filter_to_service(traces.get('top_slow') or [])[:3]
        top_errors = _filter_to_service(traces.get('top_errors') or [])[:3]

        return {
            'trace_count': int(traces.get('trace_count') or 0),
            'span_count': int(traces.get('span_count') or 0),
            'error_span_count': int(traces.get('error_span_count') or 0),
            'top_slow': top_slow,
            'top_errors': top_errors,
        }

    def get_informed_by(self, obj):
        """Compact digest of the resolved issues that fed this batch's prompt.

        Returns a dict with the count and a small array of {id, issue_type,
        component, resolved_at} entries. Empty dict when the batch did not
        reference any past resolutions, which lets the frontend render the
        panel conditionally without a follow-up request.
        """
        ids = (getattr(obj.batch, 'referenced_resolution_ids', None) or [])
        if not ids:
            return {'count': 0, 'items': []}
        referenced = Issue.objects.filter(pk__in=ids).only(
            'id', 'issue_type', 'component', 'resolved_at',
        ).order_by('-resolved_at')
        items = [
            {
                'id': r.id,
                'issue_type': r.issue_type,
                'component': r.component,
                'resolved_at': r.resolved_at.isoformat() if r.resolved_at else None,
            }
            for r in referenced
        ]
        return {'count': len(items), 'items': items}


class AIAnalyzedBatchSerializer(serializers.ModelSerializer):
    issues = IssueSerializer(many=True, read_only=True)

    class Meta:
        model = AIAnalyzedBatch
        fields = [
            'id',
            'batch_id',
            'timestamp',
            'issue_count',
            'data',
            'logs_analyzed',
            'created_at',
            'indices_covered',
            'token_count',
            'analysis_text',
            'analyzed_at',
            'model_name',
            'sentinel_decision',
            'sentinel_triggers',
            'ai_skipped',
            'logs_raw_count',
            'logs_after_severity_filter',
            'logs_unique_patterns',
            'logs_sent_to_ai',
            'trigger',
            'investigation',
            'project',
            'deployment',
            'issues'  # Include nested issues
        ]
        read_only_fields = [
            'id',
            'created_at',
            'analyzed_at',
            'token_count',
            'sentinel_decision',
            'sentinel_triggers',
            'ai_skipped',
            'logs_raw_count',
            'logs_after_severity_filter',
            'logs_unique_patterns',
            'logs_sent_to_ai',
            'trigger',
            'investigation',
            'project',
            'deployment',
        ]

class AIAnalyzedBatchListSerializer(serializers.ModelSerializer):
    analysis = serializers.SerializerMethodField()
    project_name = serializers.CharField(source='project.name', read_only=True, default=None)

    class Meta:
        model = AIAnalyzedBatch
        fields = [
            'id',
            'batch_id',
            'timestamp',
            'issue_count',
            # 'data' excluded for performance
            'logs_analyzed',
            'created_at',
            'indices_covered',
            'token_count',
            'analysis',  # Calculated field
            'analyzed_at',
            'model_name',
            'environment',  # Environment field for badge display
            'project_name',  # Project name for display
            'sentinel_decision',
            'sentinel_triggers',
            'ai_skipped',
            'logs_raw_count',
            'logs_after_severity_filter',
            'logs_unique_patterns',
            'logs_sent_to_ai',
            'trigger',
        ]

    def get_analysis(self, obj):
        # Prefer the dedicated field, fallback to data only if not present and data loaded
        if obj.analysis_text:
             try:
                import json
                import ast
                # If it's already a dict, return it
                if isinstance(obj.analysis_text, dict):
                    return obj.analysis_text
                # Try to parse as JSON
                try:
                    return json.loads(obj.analysis_text)
                except (json.JSONDecodeError, TypeError):
                    # Fallback to ast for Python repr strings
                    try:
                        return ast.literal_eval(obj.analysis_text)
                    except (ValueError, SyntaxError):
                        return {}
             except Exception:
                 return {}
        
        # Fallback to extracting from data if we absolutely must
        # But for list view we likely want to avoid this if it triggers a load
        # Checking if 'data' is deferred
        if 'data' not in obj.get_deferred_fields():
             return obj.get_analysis_results()
        
        return {}


def serialize_metrics(metrics_dict):
    """JSON-safe copy of a metrics payload, for storage on ``batch.data``.

    Only the time-series entries need converting — their ``time`` is a real
    ``datetime`` while it is in the pipeline and must become an ISO string to
    survive a JSONField. Everything else is passed through untouched.

    The non-series keys are the reason this is not a one-liner.
    ``fetch_metrics_with_provider`` also returns ``container_lifecycle``, which
    is a dict (``{'terminated': [...], 'restarts': {...}}``), and scalars like
    ``memory_usage_percent`` when a provider pre-computes them. The previous
    version assumed every value was a list of point dicts and did ``{**item}``
    over it, so a dict value iterated to its KEYS and tried to unpack a string:
    ``TypeError: 'str' object is not a mapping``.

    That raised on every Kubernetes batch, and the caller's broad ``except``
    turned it into ``serialized_metrics = {}`` — losing the raw metrics
    silently. Measured before this fix: 20 of the last 20 batches had
    ``data['metrics'] == {}`` while ``metrics_summary`` held 45 CPU and 45
    memory points. Two things broke downstream: the batch metrics chart read an
    always-empty key, and ``metrics_count`` was permanently 0, which feeds the
    batch-creation gates — so a metrics-only incident (CPU spike, no error
    logs, no traces) produced no batch at all.
    """
    serialized = {}
    for key, values in (metrics_dict or {}).items():
        if not isinstance(values, list):
            # container_lifecycle and friends: already JSON-safe, pass through.
            serialized[key] = values
            continue
        serialized[key] = [
            _serialize_metric_point(item) for item in values
        ]
    return serialized


def _serialize_metric_point(item):
    """One time-series point, with ``time`` coerced to an ISO string.

    Tolerates a non-dict entry rather than raising: losing the whole metrics
    payload because one list held something unexpected is the failure mode this
    function already caused once.
    """
    if not isinstance(item, dict):
        return item
    time_value = item.get('time')
    return {
        **item,
        'time': time_value.isoformat() if hasattr(time_value, 'isoformat') else time_value,
    }


class MemorySerializer(serializers.Serializer):
    time = serializers.DateTimeField()
    value = serializers.FloatField()
    series_id = serializers.IntegerField()
    source_table = serializers.CharField()