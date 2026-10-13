import ast
import json
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import permission_classes
from Data.serializers import AIAnalyzedBatchSerializer, AIAnalyzedBatchListSerializer
from rest_framework.response import Response
from rest_framework import status
import logging
from .models import AIAnalyzedBatch, Issue
from integrations.registry import IntegrationRegistry
from django.db.models import Count, Q, Case, When, Value, IntegerField
from django.conf import settings
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from datetime import timedelta
from django.utils import timezone
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from Projects.models import Project
from .audit import log_batch_delete
from Users.permissions import require_role


logger = logging.getLogger(__name__)
# Legacy Elasticsearch index - no longer required as we use provider-agnostic integrations
elastic_index = getattr(settings, 'ELASTICSEARCH_DEFAULT_INDEX', 'logs-*')


class BatchReanalyzeView(APIView):
    """
    Re-analyze one or more batches with a specific AI model.
    Stores results in analysis_history for comparison.
    """
    permission_classes = [IsAuthenticated]
    
    @swagger_auto_schema(
        operation_description="Re-analyze batches with a specific AI model",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['batch_ids', 'model'],
            properties={
                'batch_ids': openapi.Schema(
                    type=openapi.TYPE_ARRAY,
                    items=openapi.Schema(type=openapi.TYPE_STRING),
                    description='List of batch IDs to analyze'
                ),
                'model': openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description='AI model provider name (e.g. gemini, deepseek, claude)'
                ),
                'mode': openapi.Schema(
                    type=openapi.TYPE_STRING,
                    enum=['compare', 'primary'],
                    description=(
                        "'compare' (default) appends to analysis_history "
                        "for the Compare view; 'primary' promotes the "
                        "result to the batch's primary analysis and "
                        "updates Issues via fingerprint dedup."
                    ),
                ),
            }
        ),
        responses={
            200: 'Analysis queued successfully',
            400: 'Invalid request',
            404: 'Batch not found'
        }
    )
    @require_role('user')  # Viewers cannot trigger analysis
    def post(self, request):
        """
        Re-analyze batches with a specified AI model.
        
        Request body:
            - batch_ids: List of batch IDs to re-analyze
            - model: AI model provider name (any active provider)
        """
        try:
            batch_ids = request.data.get('batch_ids', [])
            model = request.data.get('model', 'gemini').lower()
            # RCA audit finding #11 (2026-09-20): 'compare' is the
            # historical default (writes to analysis_history only, for
            # the Compare view); 'primary' promotes the new result to
            # the primary analysis and updates Issues.
            mode = str(request.data.get('mode', 'compare')).lower()
            if mode not in ('compare', 'primary'):
                return Response(
                    {'error': "mode must be 'compare' or 'primary'"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if not batch_ids:
                return Response(
                    {'error': 'batch_ids is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            from org_settings.models import AIModelProvider
            if not AIModelProvider.objects.filter(name=model, is_active=True).exists():
                return Response(
                    {'error': f"Model '{model}' is not available. Check active AI providers."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Validate all batches exist and belong to caller's org.
            # Org filter is on the queryset, not a post-fetch check —
            # a future refactor cannot silently open cross-org access.
            batches = []
            user_org = getattr(request.user, 'organisation', None)
            qs = AIAnalyzedBatch.objects.all()
            if not request.user.is_superuser:
                qs = qs.filter(organisation=user_org) if user_org else qs.none()

            for batch_id in batch_ids:
                batch = qs.filter(batch_id=batch_id).first()
                if batch is None:
                    # Same 404 for "doesn't exist" and "other org" — no
                    # enumeration oracle.
                    return Response(
                        {'error': f'Batch {batch_id} not found'},
                        status=status.HTTP_404_NOT_FOUND,
                    )
                batches.append(batch)

            # Queue re-analysis for each batch
            from ai_model.tasks import reanalyze_batch_with_model

            queued_ids = []
            for batch in batches:
                reanalyze_batch_with_model.delay(batch.batch_id, model, mode=mode)
                queued_ids.append(batch.batch_id)
                logger.info(
                    "Queued re-analysis (%s) for batch %s with model %s",
                    mode, batch.batch_id, model,
                )

            return Response({
                'status': 'queued',
                'message': (
                    f'{"Primary re-analysis" if mode == "primary" else "Comparison analysis"}'
                    f' queued for {len(queued_ids)} batch(es) with model {model}'
                ),
                'batch_ids': queued_ids,
                'model': model,
                'mode': mode,
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.exception("Error queuing re-analysis")
            return Response(
                {'error': 'Failed to queue re-analysis', 'details': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class BatchAnalysisHistoryView(APIView):
    """
    Get analysis history for a batch to enable comparison between models.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request, batch_id):
        """
        Get all analysis results for a specific batch.
        """
        try:
            # Org-scoped fetch (filter on queryset, not post-fetch check).
            qs = AIAnalyzedBatch.objects.all()
            if not request.user.is_superuser:
                user_org = getattr(request.user, 'organisation', None)
                qs = qs.filter(organisation=user_org) if user_org else qs.none()
            batch = qs.filter(batch_id=batch_id).first()
            if batch is None:
                return Response(
                    {'error': f'Batch {batch_id} not found'},
                    status=status.HTTP_404_NOT_FOUND,
                )

            history = batch.get_analysis_history()
            
            return Response({
                'batch_id': batch_id,
                'current_model': batch.model_name,
                'analyzed_at': batch.analyzed_at.isoformat() if batch.analyzed_at else None,
                'analysis_count': len(history),
                'analysis_history': history
            }, status=status.HTTP_200_OK)
            
        except AIAnalyzedBatch.DoesNotExist:
            return Response(
                {'error': f'Batch {batch_id} not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.exception(f"Error getting analysis history for batch {batch_id}")
            return Response(
                {'error': 'Failed to get analysis history', 'details': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class BatchPromoteAnalysisView(APIView):
    """Promote one ``analysis_history`` entry to primary.

    RCA audit finding #11 (2026-09-20). Called by the "Promote to
    primary" button on each history card in the Compare view. Fast,
    synchronous — no AI call.

    POST /api/data/batches/<batch_id>/promote-analysis/
        {"analyzed_at": "2026-09-20T05:16:32.417Z"}
    """
    permission_classes = [IsAuthenticated]

    @require_role('user')  # Viewers cannot mutate primary analyses
    def post(self, request, batch_id):
        analyzed_at = request.data.get('analyzed_at')
        if not analyzed_at:
            return Response(
                {'error': 'analyzed_at is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        qs = AIAnalyzedBatch.objects.all()
        if not request.user.is_superuser:
            user_org = getattr(request.user, 'organisation', None)
            qs = qs.filter(organisation=user_org) if user_org else qs.none()
        batch = qs.filter(batch_id=batch_id).first()
        if batch is None:
            return Response(
                {'error': f'Batch {batch_id} not found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        from ai_model.tasks import promote_history_entry_to_primary
        try:
            summary = promote_history_entry_to_primary(batch, analyzed_at)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.exception('Failed to promote history entry')
            return Response(
                {'error': 'Failed to promote analysis', 'details': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({
            'status': 'promoted',
            'batch_id': batch_id,
            'analyzed_at': analyzed_at,
            **summary,
        }, status=status.HTTP_200_OK)


# OrgFilterMixin moved to Data.mixins so Data/views.py and
# Data/dashboard_views.py share one source of truth (used to be
# two divergent copies with the same name).
from .mixins import OrgFilterMixin  # noqa: E402,F401 — public re-export


class HostDiscoveryView(APIView):
    """
    Discover hosts via the configured MetricProvider for the user's organisation.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """
        Get available hosts for filtering metrics.
        
        Query params:
            - project: Project slug (optional, defaults to user's first project)
            - environment: Environment filter (optional)
        """
        project_slug = request.query_params.get('project')
        environment = request.query_params.get('environment')

        # Get user's organization
        user_org = getattr(request.user, 'organisation', None)

        if not user_org:
            return Response({'hosts': [], 'error': 'No organization found'})
        
        # Get project
        if project_slug:
            project = Project.objects.filter(
                name__iexact=project_slug,
                organisation=user_org
            ).first()
        else:
            # Default to first project
            project = Project.objects.filter(organisation=user_org).first()
        
        if not project:
            return Response({'hosts': [], 'message': 'No project found'})
        
        try:
            provider = IntegrationRegistry.get_metric_provider_for_org(user_org)
            logger.info(f"Using metric provider: {provider.__class__.__name__}")
            
            org_label = user_org.name.lower().replace(' ', '-') if user_org.name else str(user_org.id)
            project_label = project.name.lower().replace(' ', '-') if project.name else str(project.id)
            
            hosts = provider.discover_hosts(
                org=org_label,
                project=project_label,
                environment=environment
            )
            
            # HostInfo to dict
            host_dicts = [
                {
                    'instance': h.labels.get('instance', h.hostname),
                    'environment': h.environment,
                    'hostname': h.hostname
                }
                for h in hosts
            ]
            return Response({'hosts': host_dicts})
        except Exception as e:
            logger.error(f"Error discovering hosts: {e}")
            return Response({
                'hosts': [],
                'error': 'Host discovery failed', 
                'fallback': True
            })


class MetricCorrelationView(APIView):
    """
    Get metric-issue correlations for a batch.
    Returns stored correlation engine results from batch.data['correlation_results'].
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, batch_id):
        """
        Get correlations between metric anomalies and issues.

        Returns the real correlation engine output stored during batch analysis,
        optionally filtered by metric_type query param.
        """
        metric_type = request.query_params.get('metric_type', '')

        try:
            # Org-scoped fetch — impossible to accidentally return another
            # org's batch. Superusers bypass the org filter (needed for
            # internal debugging on the demo host).
            qs = AIAnalyzedBatch.objects.all()
            if not request.user.is_superuser:
                user_org = getattr(request.user, 'organisation', None)
                qs = qs.filter(organisation=user_org) if user_org else qs.none()
            batch = qs.filter(batch_id=batch_id).first()
            if batch is None:
                # Same 404 response whether the batch doesn't exist or
                # belongs to another org — no cross-org enumeration oracle.
                return Response(
                    {'correlations': [], 'error': 'Batch not found'},
                    status=status.HTTP_404_NOT_FOUND
                )

            stored = (batch.data or {}).get('correlation_results', {})
            correlations = stored.get('correlations', {})

            # If metric_type filter specified, return only that slice
            if metric_type:
                deploy_corrs = [
                    c for c in correlations.get('deployment_to_metric_spike', [])
                    if c.get('metric_type') == metric_type
                ]
                spike_corrs = [
                    c for c in correlations.get('metric_spike_to_errors', [])
                    if metric_type.lower() in (c.get('metric', '') or '').lower()
                ]
                return Response({
                    'correlations': {
                        'deployment_to_metric_spike': deploy_corrs,
                        'metric_spike_to_errors': spike_corrs,
                    },
                    'summary': stored.get('summary', {}),
                })

            return Response({
                'correlations': correlations,
                'summary': stored.get('summary', {}),
            })
        except AIAnalyzedBatch.DoesNotExist:
            return Response(
                {'correlations': [], 'error': 'Batch not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error getting correlations: {e}")
            return Response(
                {'correlations': [], 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class FluentdLogView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Retrieve logs for the authenticated user's organisation.
        Query parameters:
        - index: Index pattern to search (default: org's configured index)
        - size:  Number of results (default 10000)
        """
        try:
            logger.debug("Getting logs via LogProvider")

            user_org = getattr(request.user, 'organisation', None)
            if not user_org:
                return Response(
                    {'error': 'User has no organisation'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            index = request.query_params.get('index', elastic_index)
            size = int(request.query_params.get('size', 10000))

            # Resolve per-org log provider
            provider = IntegrationRegistry.get_log_provider_for_org(user_org)

            # Build query (LogProvider expects dict)
            query = {
                "query": {
                    "match_all": {}
                },
                "size": size,
                "sort": [
                    {
                        "@timestamp": {
                            "order": "desc"
                        }
                    }
                ]
            }

            # Fetch via provider
            log_entries = provider.search(index, query, size=size)

            # Convert to legacy ES response format
            hits = [entry.to_legacy_dict() for entry in log_entries]

            response = {
                'took': 0,
                'timed_out': False,
                '_shards': {'total': 1, 'successful': 1, 'skipped': 0, 'failed': 0},
                'hits': {
                    'total': {'value': len(hits), 'relation': 'eq'},
                    'max_score': 1.0,
                    'hits': hits
                }
            }

            logger.info(f"Successfully fetched {len(hits)} logs from index {index} via provider")
            return Response(response, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception(f"Error fetching logs from index {index}")
            return Response(
                {'error': 'Log retrieval failed', 'details': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        

class LogBatchView(OrgFilterMixin, APIView):
    """
    Retrieve log batches with their analysis.
    Requires authentication. Filters batches by user's organization.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """
        Retrieve log batches with their analysis
        Optional query parameters:
        - limit: Number of batches to return (default 20)
        - offset: Starting point for pagination (default 0)
        - with_analysis: Include analysis results (default True)
        - order_by: Field to order by (default '-timestamp')
        """
        try:
            logger.debug('Retrieving batches with pagination and filtering...')
            
            # Pagination parameters
            limit = int(request.query_params.get('limit', 5))
            offset = int(request.query_params.get('offset', 0))
            with_analysis = request.query_params.get('with_analysis', 'true').lower() == 'true'
            order_by = request.query_params.get('order_by', '-timestamp')
            
            # Apply ordering
            valid_fields = ['timestamp', 'created_at', 'analyzed_at', 'batch_id', 'logs_analyzed']
            order_field = order_by.lstrip('-')
            
            if order_field not in valid_fields:
                order_by = '-timestamp'  # Default ordering
            
            # Filter batches by user's organization
            base_queryset = self.filter_by_org(request, AIAnalyzedBatch.objects.all(), 'batch')
            
            # Environment filter - filter by environment if specified
            environment = request.query_params.get('environment', None)
            if environment and environment.lower() != 'all':
                base_queryset = base_queryset.filter(environment=environment.lower())
                logger.debug(f"Filtering batches by environment: {environment}")
            
            # Project filter - filter by project name if specified
            project_name = request.query_params.get('project', None)
            if project_name and project_name.lower() != 'all':
                base_queryset = base_queryset.filter(project__name__iexact=project_name)
                logger.debug(f"Filtering batches by project: {project_name}")

            # Cluster filter (Item #19) — when the cluster picker is
            # set, show only batches from projects assigned to that
            # cluster. Silently ignore invalid ids so a stale picker
            # value never 500s the dashboard.
            cluster_id = request.query_params.get('cluster')
            if cluster_id:
                try:
                    base_queryset = base_queryset.filter(project__cluster_id=int(cluster_id))
                except (TypeError, ValueError):
                    pass

            # Composed-filter dimensions (Batch 54 completion, L2 fix
            # 2026-09-09). Batches carry a deployment FK (Batch 49); we
            # match on it directly OR on its scope fields so a saved
            # region/namespace filter narrows correctly. Ignore invalid
            # ids the same way we do for cluster — the front-end may
            # persist stale values in localStorage.
            deployment_id = request.query_params.get('deployment')
            if deployment_id:
                try:
                    base_queryset = base_queryset.filter(deployment_id=int(deployment_id))
                except (TypeError, ValueError):
                    pass

            region = request.query_params.get('region', '').strip()
            if region:
                base_queryset = base_queryset.filter(deployment__region=region)

            namespace = request.query_params.get('namespace', '').strip()
            if namespace:
                base_queryset = base_queryset.filter(deployment__namespace=namespace)

            # Search filter - search across batch_id and project name
            search = request.query_params.get('search', '').strip()
            if search:
                from django.db.models import Q
                base_queryset = base_queryset.filter(
                    Q(batch_id__icontains=search) |
                    Q(project__name__icontains=search)
                )
                logger.debug(f"Searching batches for: {search}")

            # Get total count for pagination info
            total_count = base_queryset.count()
            
            # Get batches with pagination
            # Defer 'data' field to avoid loading heavy logs payload
            batches = base_queryset.defer('data').order_by(order_by)[offset:offset+limit]
            serializer = AIAnalyzedBatchListSerializer(batches, many=True)
            
            response_data = serializer.data
            
            # If analysis is NOT requested, remove it from the response
            # (The serializer includes it by default now)
            if not with_analysis:
                for batch_data in response_data:
                    batch_data.pop('analysis', None)
            
            # Add pagination metadata
            pagination_data = {
                'results': response_data,
                'pagination': {
                    'total': total_count,
                    'limit': limit,
                    'offset': offset,
                    'next_offset': offset + limit if offset + limit < total_count else None,
                    'previous_offset': offset - limit if offset > 0 else None,
                }
            }
            
            logger.info(f"Successfully retrieved {len(batches)} batches (offset: {offset}, limit: {limit})")
            return Response(pagination_data, status=status.HTTP_200_OK)
            
        except ValueError as e:
            logger.error(f"Invalid parameter value: {str(e)}")
            return Response(
                {'error': 'Invalid parameter value', 'details': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.exception("Error retrieving log batches")
            return Response(
                {'error': 'Failed to retrieve log batches', 'details': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        

class NodeMemoryRawView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            user_org = getattr(request.user, 'organisation', None)
            if not user_org:
                return Response(
                    {'error': 'User has no organisation'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Per-org metric provider (respects org's configured backend)
            provider = IntegrationRegistry.get_metric_provider_for_org(user_org)

            from datetime import timedelta
            from django.utils import timezone
            end_time = timezone.now()
            start_time = end_time - timedelta(days=30)

            # Org-scoped labels — prevents cross-org data leakage
            org_label = user_org.name.lower().replace(' ', '-') if user_org.name else str(user_org.id)
            org_labels = {'organisation_name': org_label}

            # Helper to map TimeSeries to view format
            def _map_to_view(series_list, table_name):
                mapped = []
                for ts in series_list:
                    try:
                        sid = int(ts.labels.get('series_id', 0))
                    except (ValueError, TypeError):
                        sid = 0

                    for p in ts.points:
                        mapped.append({
                            'time': p.timestamp,
                            'value': p.value,
                            'series_id': sid,
                            'source_table': table_name
                        })
                return mapped

            # Fetch metrics with org labels
            total_ts = provider.query_range('node_memory_MemTotal_bytes', org_labels, start_time, end_time)
            free_ts = provider.query_range('node_memory_MemFree_bytes', org_labels, start_time, end_time)
            avail_ts = provider.query_range('node_memory_MemAvailable_bytes', org_labels, start_time, end_time)

            total = _map_to_view(total_ts, 'node_memory_MemTotal_bytes')
            free = _map_to_view(free_ts, 'node_memory_MemFree_bytes')
            available = _map_to_view(avail_ts, 'node_memory_MemAvailable_bytes')

            combined_results = total + free + available
            combined_results.sort(key=lambda x: x['time'], reverse=True)

            response_data = {
                'data': combined_results[:200],
                'metadata': {
                    'total_records': len(combined_results),
                    'metrics_count': {
                        'total': len(total),
                        'free': len(free),
                        'available': len(available)
                    },
                    'time_range': {
                        'oldest': combined_results[-1]['time'].isoformat() if combined_results else None,
                        'newest': combined_results[0]['time'].isoformat() if combined_results else None
                    }
                }
            }

            return Response(response_data, status=200)

        except Exception as e:
            logger.error(f"Error fetching memory data: {str(e)}")
            return Response(
                {'error': 'Failed to retrieve memory data', 'details': str(e)},
                status=500
            )
        

class BatchDetailView(OrgFilterMixin, APIView):
    """
    Retrieve detailed information for a specific batch.
    Requires authentication. Only returns batches from user's organization.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request, batch_id):
        """
        Retrieve detailed information for a specific batch

        Args:
            batch_id: The unique identifier of the batch
        """
        try:
            logger.debug(f'Retrieving details for batch {batch_id}')

            # Org-scoped fetch — the org filter is baked into the queryset
            # itself, not applied as a post-fetch check. This means a
            # future refactor cannot forget the check without also
            # explicitly removing the .filter() call. Superusers bypass
            # (needed for internal debugging on the demo host).
            qs = AIAnalyzedBatch.objects.all()
            if not request.user.is_superuser:
                user_org = getattr(request.user, 'organisation', None)
                qs = qs.filter(organisation=user_org) if user_org else qs.none()
            batch = qs.filter(batch_id=batch_id).first()
            if batch is None:
                # Same 404 response whether the batch doesn't exist or
                # belongs to another org — no cross-org enumeration oracle.
                logger.info(
                    "Batch %s not found for user %s (or not in their org)",
                    batch_id, request.user.id,
                )
                return Response(
                    {'error': f'Batch {batch_id} not found'},
                    status=status.HTTP_404_NOT_FOUND
                )

            serializer = AIAnalyzedBatchSerializer(batch)
            
            # Prepare detailed response
            response_data = serializer.data
            response_data.update({
                'analysis': batch.get_analysis_results(),
                'metrics_summary': {
                    'total_logs': batch.logs_analyzed,
                    'unique_issues': batch.issue_count,
                    'token_count': batch.token_count,
                    'indices': batch.indices_covered,
                },
                'timing': {
                    'created_at': batch.created_at.isoformat(),
                    'analyzed_at': batch.analyzed_at.isoformat() if batch.analyzed_at else None,
                    'batch_timestamp': batch.timestamp.isoformat(),
                }
            })
            
            logger.info(f"Successfully retrieved details for batch {batch_id}")
            return Response(response_data, status=status.HTTP_200_OK)
            
        except AIAnalyzedBatch.DoesNotExist:
            logger.error(f"Batch {batch_id} not found")
            return Response(
                {'error': f'Batch {batch_id} not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.exception(f"Error retrieving batch {batch_id}")
            return Response(
                {'error': 'Failed to retrieve batch details', 'details': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


#recommendation stats
class RecommendationStatsView(OrgFilterMixin, APIView):
    """
    Calculate recommendation statistics.
    Requires authentication. Filters by user's organization for data isolation.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """
        Extract and count recommendations from the Issue model directly.
        """
        try:
            logger.info('Starting recommendation statistics calculation from database...')
            
            # Filter by user's organization
            base_issues = self.filter_by_org(request, Issue.objects.all(), 'issue')
            base_batches = self.filter_by_org(request, AIAnalyzedBatch.objects.all(), 'batch')
            
            from django.db.models import Q, Count

            # Issues with non-empty recommendations
            issues_with_recs = base_issues.exclude(
                recommendation__isnull=True
            ).exclude(
                recommendation__exact=''
            )

            # Classify by issue severity: CRITICAL = immediate action needed,
            # WARNING/INFO/other = long-term improvements.
            # This is more reliable than text matching across different AI models.
            immediate_count = issues_with_recs.filter(
                severity='CRITICAL'
            ).count()

            total_recommendations = issues_with_recs.count()
            long_term_count = total_recommendations - immediate_count

            stats = {
                'IMMEDIATE': {'count': immediate_count},
                'LONG_TERM': {'count': long_term_count},
                'total_batches': base_batches.count(),
                'batches_with_recommendations': issues_with_recs.values('batch').distinct().count(),
                'total_recommendations': total_recommendations,
                'parsed_structures': []
            }

            # Calculate percentages
            total_valid = stats['IMMEDIATE']['count'] + stats['LONG_TERM']['count']
            immediate_percentage = round((stats['IMMEDIATE']['count'] / total_valid * 100), 2) if total_valid > 0 else 0.0
            long_term_percentage = round((stats['LONG_TERM']['count'] / total_valid * 100), 2) if total_valid > 0 else 0.0

            response_data = {
                'statistics': {
                    'immediate': {
                        'count': stats['IMMEDIATE']['count'],
                        'percentage': immediate_percentage
                    },
                    'long_term': {
                        'count': stats['LONG_TERM']['count'],
                        'percentage': long_term_percentage
                    },
                    'summary': {
                        'total_batches': stats['total_batches'],
                        'batches_with_recommendations': stats['batches_with_recommendations'],
                        'total_recommendations': stats['total_recommendations']
                    }
                }
            }

            logger.info(
                f"Recommendation stats - Immediate: {stats['IMMEDIATE']['count']}, "
                f"Long Term: {stats['LONG_TERM']['count']}, "
                f"Total recommendations: {stats['total_recommendations']}"
            )

            return Response(response_data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception("Fatal error in recommendation stats calculation")
            return Response(
                {'error': 'Internal server error', 'details': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )






#issues stats
class IssueStatsView(OrgFilterMixin, APIView):
    """
    Calculate statistics for issues by severity.
    Requires authentication. Filters by user's organization for data isolation.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """
        Calculate statistics for issues by severity (CRITICAL, WARNING)
        using the normalized Issue model.
        """
        try:
            logger.info('Starting issue statistics calculation from database...')
            
            # Filter issues by user's organization
            base_issues = self.filter_by_org(request, Issue.objects.all(), 'issue')
            base_batches = self.filter_by_org(request, AIAnalyzedBatch.objects.all(), 'batch')
            
            # Aggregate counts by severity
            stats_data = base_issues.values('severity').annotate(count=Count('id'))
            
            # Convert to dictionary
            stats_dict = {item['severity']: item['count'] for item in stats_data}
            
            critical_count = stats_dict.get('CRITICAL', 0)
            warning_count = stats_dict.get('WARNING', 0)
            info_count = stats_dict.get('INFO', 0)

            total_issues = base_issues.count()
            batches_with_issues = base_issues.values('batch').distinct().count()
            total_batches = base_batches.count()

            # Percentages divide by ``total_issues`` (D3 fix). Previously
            # the denominator was ``critical + warning`` only, which
            # hid INFO / other severities from the frontend pie chart —
            # e.g. 2C + 2W + 2I would render as 50/50 CRITICAL/WARNING
            # even though a third of issues were INFO. Now percentages
            # sum to 100% across all displayed buckets.
            other_count = total_issues - (critical_count + warning_count + info_count)

            def _pct(count):
                return round((count / total_issues * 100), 2) if total_issues > 0 else 0.0

            response_data = {
                'statistics': {
                    'critical': {'count': critical_count, 'percentage': _pct(critical_count)},
                    'warning': {'count': warning_count, 'percentage': _pct(warning_count)},
                    'info': {'count': info_count, 'percentage': _pct(info_count)},
                    'other': {'count': other_count, 'percentage': _pct(other_count)},
                    'summary': {
                        'total_batches': total_batches,
                        'batches_with_issues': batches_with_issues,
                        'total_issues': total_issues
                    }
                }
            }

            # Add unknown severities if any (any bucket outside our
            # named 4). Retained for backwards-compat with clients
            # that already inspected this field.
            unknown_severities = {
                k: v for k, v in stats_dict.items()
                if k not in ['CRITICAL', 'WARNING', 'INFO']
            }
            if unknown_severities:
                response_data['unknown_severities'] = unknown_severities

            logger.info(
                f"Issue stats - CRITICAL: {critical_count}, "
                f"WARNING: {warning_count}, "
                f"Total batches: {total_batches}, "
                f"Batches with issues: {batches_with_issues}, "
                f"Total issues: {total_issues}"
            )

            return Response(response_data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception("Fatal error in issue stats calculation")
            return Response(
                {'error': 'Internal server error', 'details': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )





def _apply_issue_search(queryset, search_term):
    """Apply text search across description, component, and root_cause."""
    if search_term:
        queryset = queryset.filter(
            Q(description__icontains=search_term) |
            Q(component__icontains=search_term) |
            Q(root_cause__icontains=search_term) |
            Q(error_target__icontains=search_term)
        )
    return queryset


def _apply_issue_sorting(queryset, sort_by, sort_dir):
    """Apply sorting with semantic severity ordering."""
    sort_mapping = {
        'timestamp': 'batch__timestamp',
        'description': 'description',
        'created_at': 'created_at',
        'last_seen_at': 'last_seen_at',
        'count': 'occurrence_count',
        'component': 'component',
        'type': 'issue_type',
        'status': 'status',
    }

    if sort_by == 'severity':
        # Semantic severity ordering: CRITICAL=0, WARNING=1, INFO=2, UNKNOWN=3
        queryset = queryset.annotate(
            severity_order=Case(
                When(severity='CRITICAL', then=Value(0)),
                When(severity='WARNING', then=Value(1)),
                When(severity='INFO', then=Value(2)),
                default=Value(3),
                output_field=IntegerField(),
            )
        )
        order_field = '-severity_order' if sort_dir == 'asc' else 'severity_order'
        return queryset.order_by(order_field, '-created_at')

    model_sort_field = sort_mapping.get(sort_by, 'created_at')
    if sort_dir == 'desc':
        model_sort_field = f'-{model_sort_field}'

    return queryset.order_by(model_sort_field)


def _build_issue_summary(base_queryset, include_batch_count=False, cache_key=None):
    """Build summary stats with severity/status distributions in a single query.

    Uses cache (30s TTL) when cache_key is provided to avoid expensive aggregate
    queries on every page load — critical for remote DB with high per-query latency.
    """
    if cache_key:
        from django.core.cache import cache
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    # Single aggregate query for all summary stats (avoids multiple round-trips)
    agg = base_queryset.aggregate(
        # Severity counts
        sev_critical=Count('id', filter=Q(severity='CRITICAL')),
        sev_warning=Count('id', filter=Q(severity='WARNING')),
        sev_info=Count('id', filter=Q(severity='INFO')),
        sev_unknown=Count('id', filter=Q(severity='UNKNOWN')),
        # Status counts
        st_open=Count('id', filter=Q(status='OPEN')),
        st_muted=Count('id', filter=Q(status='MUTED')),
        st_resolved=Count('id', filter=Q(status='RESOLVED')),
        # Total + distinct batches
        total=Count('id'),
        batch_count=Count('batch', distinct=True),
    )

    severity_distribution = {}
    for key, label in [('sev_critical', 'CRITICAL'), ('sev_warning', 'WARNING'),
                       ('sev_info', 'INFO'), ('sev_unknown', 'UNKNOWN')]:
        if agg[key]:
            severity_distribution[label] = agg[key]

    status_distribution = {}
    for key, label in [('st_open', 'OPEN'), ('st_muted', 'MUTED'), ('st_resolved', 'RESOLVED')]:
        if agg[key]:
            status_distribution[label] = agg[key]

    result = {
        'severity_distribution': severity_distribution,
        'status_distribution': status_distribution,
    }
    if include_batch_count:
        result['batches_with_issues'] = agg['batch_count']

    if cache_key:
        cache.set(cache_key, result, timeout=30)

    return result


class IssueListView(OrgFilterMixin, APIView):
    """
    Retrieve all issues across batches with pagination.
    Requires authentication. Filters issues by user's organization.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Retrieve all issues across batches with pagination using the normalized Issue model.
        """
        try:
            logger.info('Retrieving issues from database with pagination and filtering...')

            # Parse pagination and filter parameters
            page = int(request.query_params.get('page', 1))
            page_size = int(request.query_params.get('page_size', 20))
            severity_filter = request.query_params.get('severity', 'ALL').upper()
            status_filter = request.query_params.get('status', 'ALL').upper()
            sort_by = request.query_params.get('sort_by', 'severity').lower()
            sort_dir = request.query_params.get('sort_dir', 'desc').lower()
            search = request.query_params.get('search', '').strip()

            # Base queryset - filtered by organization
            base_queryset = self.filter_by_org(request, Issue.objects.all(), 'issue')

            # Build summary from unfiltered base queryset — single aggregate query
            # Cached for 30s per org to reduce DB round-trips (critical for remote DB)
            user_org = getattr(request.user, 'organisation', None)
            org_id = user_org.id if user_org else 0
            summary = _build_issue_summary(
                base_queryset, include_batch_count=True,
                cache_key=f'issue_summary:org:{org_id}'
            )
            summary['filter_applied'] = severity_filter

            queryset = base_queryset.select_related('batch').defer(
                'batch__data',
                'batch__analysis_text',
                'batch__analysis_history',
                'batch__indices_covered'
            )

            # Determine if filters are applied (affects total count)
            has_filters = (severity_filter != 'ALL' or status_filter != 'ALL' or search)

            # Apply Severity Filter
            if severity_filter != 'ALL':
                queryset = queryset.filter(severity=severity_filter)

            # Apply Status Filter
            if status_filter != 'ALL':
                queryset = queryset.filter(status=status_filter)

            # Apply Cluster Filter (Item #19) — issues live on batches
            # live on projects live on clusters. Silently ignore bad ids.
            cluster_id = request.query_params.get('cluster')
            if cluster_id:
                try:
                    queryset = queryset.filter(batch__project__cluster_id=int(cluster_id))
                    has_filters = True
                except (TypeError, ValueError):
                    pass

            # Composed-filter dimensions (Batch 54 completion / L2 fix).
            # Reach into batch.deployment for region/namespace since
            # issues don't carry those directly.
            deployment_id = request.query_params.get('deployment')
            if deployment_id:
                try:
                    queryset = queryset.filter(batch__deployment_id=int(deployment_id))
                    has_filters = True
                except (TypeError, ValueError):
                    pass

            region = request.query_params.get('region', '').strip()
            if region:
                queryset = queryset.filter(batch__deployment__region=region)
                has_filters = True

            namespace = request.query_params.get('namespace', '').strip()
            if namespace:
                queryset = queryset.filter(batch__deployment__namespace=namespace)
                has_filters = True

            # Apply Text Search
            queryset = _apply_issue_search(queryset, search)

            # Get total count — reuse summary total when unfiltered to skip extra COUNT query
            if has_filters:
                total_issues = queryset.count()
            else:
                total_issues = sum(summary.get('severity_distribution', {}).values())

            # Apply Sorting (semantic severity order)
            queryset = _apply_issue_sorting(queryset, sort_by, sort_dir)

            # Manual pagination (avoids Paginator's separate COUNT query)
            total_pages = max(1, (total_issues + page_size - 1) // page_size)
            page = min(page, total_pages)
            offset = (page - 1) * page_size
            issues_list = list(queryset[offset:offset + page_size])

            # Serialize
            from Data.serializers import IssueSerializer
            serializer = IssueSerializer(issues_list, many=True)

            response_data = {
                'results': serializer.data,
                'pagination': {
                    'total_issues': total_issues,
                    'page': page,
                    'page_size': page_size,
                    'total_pages': total_pages,
                    'next_page': page + 1 if page < total_pages else None,
                    'previous_page': page - 1 if page > 1 else None,
                },
                'summary': summary,
            }

            logger.info(f"Successfully retrieved {len(serializer.data)} issues (page {page}/{total_pages})")
            return Response(response_data, status=status.HTTP_200_OK)

        except ValueError as e:
            logger.error(f"Invalid parameter value: {str(e)}")
            return Response({'error': 'Invalid parameter', 'details': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception("Error retrieving issues")
            return Response({'error': 'Failed to retrieve issues', 'details': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class BatchIssuesView(OrgFilterMixin, APIView):
    """
    Retrieve all issues for a specific batch with pagination.
    Requires authentication. Only returns batches from user's organization.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request, batch_id):
        """
        Retrieve all issues for a specific batch with pagination using the Issue model.
        Falls back to parsing analysis_text for legacy batches without Issue records.
        """
        try:
            logger.info(f'Retrieving issues for batch {batch_id} from database...')
            
            # Check if batch exists and belongs to user's org
            try:
                batch = AIAnalyzedBatch.objects.defer('data', 'indices_covered').get(batch_id=batch_id)

                # Verify batch belongs to user's organization.
                # Prefer the direct AIAnalyzedBatch.organisation FK (added
                # for multi-tenant isolation); fall back to the legacy
                # batch.project.organisation only when the direct FK is
                # unset. Previously we ONLY checked the indirect path,
                # and any batch whose ``project`` was None (there are
                # many — batches created before a project existed, or
                # via ad-hoc analyse endpoints) fell through as 404.
                if not request.user.is_superuser:
                    user_org = getattr(request.user, 'organisation', None)
                    batch_org = (
                        getattr(batch, 'organisation', None)
                        or (getattr(batch.project, 'organisation', None) if batch.project else None)
                    )
                    if user_org != batch_org:
                        logger.warning(f"User {request.user.id} attempted to access batch {batch_id} from different org")
                        return Response({'error': f'Batch with ID {batch_id} not found'}, status=status.HTTP_404_NOT_FOUND)
                        
            except AIAnalyzedBatch.DoesNotExist:
                return Response({'error': f'Batch with ID {batch_id} not found'}, status=status.HTTP_404_NOT_FOUND)
            
            # Parse pagination and filter parameters
            page = int(request.query_params.get('page', 1))
            page_size = int(request.query_params.get('page_size', 20))
            severity_filter = request.query_params.get('severity', 'ALL').upper()
            status_filter = request.query_params.get('status', 'ALL').upper()
            sort_by = request.query_params.get('sort_by', 'severity').lower()
            sort_dir = request.query_params.get('sort_dir', 'desc').lower()
            search = request.query_params.get('search', '').strip()

            # Query Issues for this batch (defer heavy batch fields for serialization)
            # Via occurrences, not the batch FK. That FK holds only the issue's
            # most recent sighting, so every batch except the newest to have
            # seen an issue silently dropped it from this list — measured at 17
            # of 25 batches under-reporting, two showing none at all.
            queryset = Issue.objects.filter(occurrences__batch=batch).distinct().select_related('batch').defer(
                'batch__data', 'batch__analysis_text', 'batch__analysis_history', 'batch__indices_covered'
            )

            # If no Issue records found, fallback to parsing analysis_text (legacy batches)
            if not queryset.exists() and batch.analysis_text:
                logger.info(f'No Issue records found for batch {batch_id}, falling back to analysis_text')
                return self._get_issues_from_analysis_text(batch, severity_filter, page, page_size)

            # Build summary from unfiltered batch queryset (before filters)
            summary = _build_issue_summary(queryset)
            summary['batches_with_issues'] = 1 if queryset.exists() else 0
            summary['filter_applied'] = severity_filter

            # Apply Severity Filter
            if severity_filter != 'ALL':
                queryset = queryset.filter(severity=severity_filter)

            # Apply Status Filter
            if status_filter != 'ALL':
                queryset = queryset.filter(status=status_filter)

            # Apply Text Search
            queryset = _apply_issue_search(queryset, search)

            # Apply Sorting (semantic severity order)
            queryset = _apply_issue_sorting(queryset, sort_by, sort_dir)

            # Pagination
            paginator = Paginator(queryset, page_size)
            try:
                issues_page = paginator.page(page)
            except (PageNotAnInteger, EmptyPage):
                issues_page = paginator.page(1)

            # Serialize
            from Data.serializers import IssueSerializer
            serializer = IssueSerializer(issues_page, many=True)

            response_data = {
                'results': serializer.data,
                'pagination': {
                    'total_issues': paginator.count,
                    'page': page,
                    'page_size': page_size,
                    'total_pages': paginator.num_pages,
                    'next_page': page + 1 if issues_page.has_next() else None,
                    'previous_page': page - 1 if issues_page.has_previous() else None,
                },
                'summary': summary,
            }

            return Response(response_data, status=status.HTTP_200_OK)

        except ValueError as e:
            return Response({'error': 'Invalid parameter', 'details': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception(f"Error retrieving issues for batch {batch_id}")
            return Response({'error': 'Internal server error', 'details': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def _get_issues_from_analysis_text(self, batch, severity_filter, page, page_size):
        """Fallback: Extract issues from analysis_text JSON for legacy batches."""
        import ast
        
        try:
            # Parse analysis_text (could be JSON string or Python dict repr)
            if isinstance(batch.analysis_text, str):
                try:
                    import json
                    analysis = json.loads(batch.analysis_text)
                except json.JSONDecodeError:
                    analysis = ast.literal_eval(batch.analysis_text)
            else:
                analysis = batch.analysis_text
            
            correlated_issues = analysis.get('correlated_issues', [])
            
            # Convert to serializer-compatible format
            issues_data = []
            for i, issue in enumerate(correlated_issues):
                severity = issue.get('severity', 'UNKNOWN').upper()
                
                # Apply severity filter
                if severity_filter != 'ALL' and severity != severity_filter:
                    continue
                
                issues_data.append({
                    'id': i + 1,  # Fake ID for legacy issues
                    'batch': batch.id,
                    'batch_id_str': batch.batch_id,
                    'batch_timestamp': batch.timestamp.isoformat() if batch.timestamp else None,
                    'severity': severity,
                    'description': issue.get('description', ''),
                    'recommendation': issue.get('recommended_action', ''),
                    'root_cause': issue.get('root_cause', '') if isinstance(issue.get('root_cause'), str) else issue.get('root_cause', {}).get('description', ''),
                    'created_at': batch.created_at.isoformat() if batch.created_at else None,
                    # v2 fields with defaults
                    'issue_type': issue.get('issue_type', issue.get('error_type', 'OTHER')),
                    'scope': issue.get('scope', 'SERVICE'),
                    'component': issue.get('component', issue.get('service', '')),
                    'environment': batch.environment or '',
                    'status': 'OPEN',
                    'occurrence_count': 1,
                    'muted_until': None,
                    'last_seen_at': None,
                })
            
            # Simple pagination
            total = len(issues_data)
            start = (page - 1) * page_size
            end = start + page_size
            paginated = issues_data[start:end]
            
            # Build summary from parsed issues (before pagination)
            severity_counts = {}
            status_counts = {}
            for iss in issues_data:
                sev = iss.get('severity', 'UNKNOWN')
                severity_counts[sev] = severity_counts.get(sev, 0) + 1
                st = iss.get('status', 'OPEN')
                status_counts[st] = status_counts.get(st, 0) + 1

            return Response({
                'results': paginated,
                'pagination': {
                    'total_issues': total,
                    'page': page,
                    'page_size': page_size,
                    'total_pages': (total + page_size - 1) // page_size if total > 0 else 1,
                    'next_page': page + 1 if end < total else None,
                    'previous_page': page - 1 if page > 1 else None,
                },
                'summary': {
                    'severity_distribution': severity_counts,
                    'status_distribution': status_counts,
                    'batches_with_issues': 1 if total > 0 else 0,
                    'filter_applied': severity_filter,
                    'legacy_fallback': True,
                }
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.exception(f"Error parsing analysis_text for batch {batch.batch_id}")
            return Response({
                'results': [],
                'pagination': {'total_issues': 0, 'page': 1, 'page_size': page_size, 'total_pages': 1},
                'error': f'Failed to parse legacy analysis: {str(e)}'
            }, status=status.HTTP_200_OK)


class IssueActionsView(OrgFilterMixin, APIView):
    """
    Handle manual issue actions: resolve, mute, reopen.
    Requires authentication. Only allows actions on issues from user's organization.
    """
    permission_classes = [IsAuthenticated]
    
    def _get_issue(self, request, issue_id):
        """Get issue, org-scoped.

        Org filter lives on the queryset — no post-fetch check that a
        refactor could silently drop. Same 404 for "doesn't exist"
        and "wrong org" so there's no enumeration oracle.
        """
        qs = Issue.objects.all()
        if not request.user.is_superuser:
            user_org = getattr(request.user, 'organisation', None)
            qs = qs.filter(organisation=user_org) if user_org else qs.none()
        issue = qs.filter(id=issue_id).first()
        if issue is None:
            return None, Response(
                {'error': 'Issue not found'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return issue, None
    
    @require_role('user')
    def post(self, request, issue_id, action):
        """
        Handle issue action based on URL parameter.

        Actions:
            - resolve: Set status to RESOLVED
            - mute: Set status to MUTED, muted_until = now + days
            - reopen: Set status to OPEN
        """
        issue, error_response = self._get_issue(request, issue_id)
        if error_response:
            return error_response
        
        try:
            if action == 'resolve':
                issue.status = 'RESOLVED'
                issue.resolved_at = timezone.now()
                issue.save(update_fields=['status', 'resolved_at'])
                logger.info(f"Issue {issue_id} resolved by user {request.user.id}")

            elif action == 'mute':
                days = int(request.data.get('days', 7))
                if days <= 0:
                    # Forever mute
                    issue.muted_until = None
                else:
                    issue.muted_until = timezone.now() + timedelta(days=days)
                issue.status = 'MUTED'
                issue.save(update_fields=['status', 'muted_until'])
                logger.info(f"Issue {issue_id} muted for {days} days by user {request.user.id}")

            elif action == 'reopen':
                issue.status = 'OPEN'
                issue.muted_until = None
                issue.resolved_at = None
                issue.save(update_fields=['status', 'muted_until', 'resolved_at'])
                logger.info(f"Issue {issue_id} reopened by user {request.user.id}")
                
            else:
                return Response(
                    {'error': f'Unknown action: {action}. Valid actions: resolve, mute, reopen'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Invalidate cached issue summary for this org
            user_org = getattr(request.user, 'organisation', None)
            if user_org:
                from django.core.cache import cache
                cache.delete(f'issue_summary:org:{user_org.id}')

            # Return updated issue
            from Data.serializers import IssueSerializer
            serializer = IssueSerializer(issue)
            return Response(serializer.data, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.exception(f"Error performing action {action} on issue {issue_id}")
            return Response(
                {'error': f'Failed to {action} issue', 'details': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class IssueBulkActionsView(OrgFilterMixin, APIView):
    """
    Perform bulk actions on multiple issues at once.
    Accepts POST with { issue_ids: [...], action: "resolve"|"mute"|"reopen", days?: N }
    """
    permission_classes = [IsAuthenticated]

    @require_role('user')
    def post(self, request):
        issue_ids = request.data.get('issue_ids', [])
        action = request.data.get('action', '').lower()
        days = int(request.data.get('days', 7))

        if not issue_ids:
            return Response(
                {'error': 'issue_ids is required and must not be empty'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if action not in ('resolve', 'mute', 'reopen'):
            return Response(
                {'error': f'Invalid action: {action}. Valid actions: resolve, mute, reopen'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Filter to only issues belonging to user's org
        user_issues = self.filter_by_org(request, Issue.objects.all(), 'issue')
        matching = user_issues.filter(id__in=issue_ids)

        # Reject if any requested IDs don't belong to the user's org
        if matching.count() != len(issue_ids):
            return Response(
                {'error': 'One or more issue IDs not found or not accessible'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            if action == 'resolve':
                updated = matching.update(status='RESOLVED', resolved_at=timezone.now())
            elif action == 'mute':
                muted_until = None
                if days > 0:
                    muted_until = timezone.now() + timedelta(days=days)
                updated = matching.update(status='MUTED', muted_until=muted_until)
            elif action == 'reopen':
                updated = matching.update(status='OPEN', muted_until=None, resolved_at=None)

            # Invalidate cached issue summary
            user_org = getattr(request.user, 'organisation', None)
            if user_org:
                from django.core.cache import cache
                cache.delete(f'issue_summary:org:{user_org.id}')

            logger.info(f"Bulk {action} on {updated} issues by user {request.user.id}")
            return Response({'updated': updated}, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception(f"Error performing bulk {action}")
            return Response(
                {'error': f'Failed to bulk {action}', 'details': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# cpu metrics
class NodeCPURawView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            logger.info("Fetching CPU metrics")

            user_org = getattr(request.user, 'organisation', None)
            if not user_org:
                return Response(
                    {'error': 'User has no organisation'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            from django.utils import timezone
            from datetime import timedelta

            # Per-org metric provider
            provider = IntegrationRegistry.get_metric_provider_for_org(user_org)

            time_threshold = timezone.now() - timedelta(hours=24)

            # Org-scoped labels
            org_label = user_org.name.lower().replace(' ', '-') if user_org.name else str(user_org.id)
            org_labels = {'organisation_name': org_label}

            # Fetch CPU metrics with org labels
            cpu_ts = provider.query_range(
                'node_cpu_seconds_total',
                org_labels,
                time_threshold,
                timezone.now()
            )

            results = []
            for ts in cpu_ts:
                try:
                    sid = int(ts.labels.get('series_id', 0))
                except (ValueError, TypeError):
                    sid = 0

                for p in ts.points:
                    results.append({
                        'time': p.timestamp,
                        'value': p.value,
                        'series_id': sid,
                        'source_table': 'node_cpu_seconds_total'
                    })

            results.sort(key=lambda x: x['time'], reverse=True)
            results = results[:200]

            logger.info(f"CPU records found: {len(results)}")

            if not results:
                logger.warning("No CPU data found")
                return Response(
                    {'warning': 'No CPU data available'},
                    status=200
                )

            response_data = {
                'data': results,
                'metadata': {
                    'total_records': len(results),
                    'time_range': {
                        'oldest': results[-1]['time'].isoformat() if results else None,
                        'newest': results[0]['time'].isoformat() if results else None
                    }
                }
            }

            return Response(response_data, status=200)

        except Exception as e:
            logger.error(f"Critical error: {str(e)}", exc_info=True)
            return Response(
                {
                    'error': 'Database error',
                    'details': str(e)
                },
                status=500
            )
        



class SimilarIssuesView(OrgFilterMixin, APIView):
    """
    GET /api/data/issues/<id>/similar/  — Item #27.

    Returns up to N (default 5) similar past resolved issues for a
    given issue, ranked by embedding cosine similarity. Org-scoped
    via the 404-oracle pattern.

    Response ``results`` is empty when the issue has no embedding
    (still being computed, or embedding failed) — callers don't
    need to distinguish "no matches" from "no embedding".
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, issue_id):
        qs = Issue.objects.all()
        if not request.user.is_superuser:
            user_org = getattr(request.user, 'organisation', None)
            qs = qs.filter(organisation=user_org) if user_org else qs.none()
        issue = qs.filter(pk=issue_id).first()
        if issue is None:
            return Response({'error': f'Issue {issue_id} not found'}, status=404)

        try:
            top_k = min(int(request.query_params.get('limit', 5)), 20)
        except (TypeError, ValueError):
            top_k = 5

        matches = issue.find_similar(top_k=top_k)
        results = [
            {
                'id': m['issue'].pk,
                'similarity': m['similarity'],
                'issue_type': m['issue'].issue_type,
                'component': m['issue'].component,
                'severity': m['issue'].severity,
                'root_cause': (m['issue'].root_cause or '')[:500],
                'recommendation': (m['issue'].recommendation or '')[:500],
                'description': (m['issue'].description or '')[:300],
                'resolved_at': m['issue'].resolved_at.isoformat() if m['issue'].resolved_at else None,
            }
            for m in matches
        ]
        return Response({'issue_id': issue.pk, 'results': results})


class BatchPostmortemView(OrgFilterMixin, APIView):
    """
    POST /api/data/batches/<batch_id>/postmortem/  — Item #28.

    Generate a post-mortem markdown draft for a completed batch,
    seeded with the batch's top issues, deploys in the window, and
    similar past resolved incidents (via Item #27).

    Response::

        {"batch_id": "...", "markdown": "# Post-mortem: ...", "generated_at": "..."}

    The markdown is a *draft*: the AI writes placeholder timeline
    entries + question prompts the SRE fills in. Frontend renders
    it in a modal with copy-to-clipboard.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, batch_id):
        qs = AIAnalyzedBatch.objects.all()
        if not request.user.is_superuser:
            user_org = getattr(request.user, 'organisation', None)
            qs = qs.filter(organisation=user_org) if user_org else qs.none()
        batch = qs.filter(batch_id=batch_id).first()
        if batch is None:
            return Response({'error': f'Batch {batch_id} not found'}, status=404)

        try:
            from ai_model.postmortem import generate_postmortem_draft
            markdown = generate_postmortem_draft(batch)
        except Exception as exc:
            logger.exception('postmortem generation failed for batch %s: %s',
                             batch_id, exc)
            return Response(
                {'error': 'Failed to generate post-mortem'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({
            'batch_id': batch_id,
            'markdown': markdown,
            'generated_at': timezone.now().isoformat(),
        })


class BatchTimelineView(OrgFilterMixin, APIView):
    """
    Unified event timeline for a batch — Item #12 flagship endpoint.

    Returns a chronologically-sorted list of events across all 5 data
    sources (logs, metrics, code, cicd, traces). See
    ``Data.unified_timeline`` for the shape.

    Org-scoped via the same 404-oracle pattern as BatchDetailView.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, batch_id):
        qs = AIAnalyzedBatch.objects.all()
        if not request.user.is_superuser:
            user_org = getattr(request.user, 'organisation', None)
            qs = qs.filter(organisation=user_org) if user_org else qs.none()
        batch = qs.filter(batch_id=batch_id).first()
        if batch is None:
            return Response(
                {'error': f'Batch {batch_id} not found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Q5-4: pagination — ``limit`` (server-bounded) + ``offset`` on
        # the merged timeline. ``max_events`` is preserved as an alias
        # for ``limit`` for backwards compatibility with the pre-Q5
        # frontend + any external scripts. Old callers who pass only
        # ``max_events`` get their same 200-event page; new callers can
        # walk paginated pages and read the pre-slice ``total_events``
        # to know when to stop.
        _params = request.query_params
        _raw_limit = _params.get('limit') or _params.get('max_events') or 200
        try:
            limit = min(max(int(_raw_limit), 1), 500)
        except (TypeError, ValueError):
            limit = 200
        try:
            offset = max(int(_params.get('offset', 0)), 0)
        except (TypeError, ValueError):
            offset = 0

        from Data.unified_timeline import (
            build_causal_pairs,
            build_unified_timeline_with_total,
        )
        events, total_events = build_unified_timeline_with_total(
            batch, max_events=limit, offset=offset,
        )
        # Causal pairs are engine-backed (correlation_results) rather
        # than a frontend heuristic — the chart draws arrows that
        # match what the correlation engine + AI narrative say
        # (Batch 42, no more source-of-truth drift).
        causal_pairs = build_causal_pairs(batch, events)
        return Response({
            'batch_id': batch_id,
            'event_count': len(events),
            'events': events,
            'causal_pairs': causal_pairs,
            'pagination': {
                'total_events': total_events,
                'offset': offset,
                'limit': limit,
                'has_more': (offset + len(events)) < total_events,
            },
        })


class DeleteOldBatchesView(APIView):
    """Delete old batches. Admin only for security."""
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_description="Delete all AIAnalyzedBatch objects older than a custom number of days.",
        manual_parameters=[
            openapi.Parameter(
                'days',
                openapi.IN_QUERY,
                description="Number of days (must be a positive integer, default: 30). Deletes batches older than this.",
                type=openapi.TYPE_INTEGER,
                required=False
            )
        ],
        responses={
            200: openapi.Response(
                description="Batches deleted successfully",
                examples={
                    "application/json": {
                        "deleted_batches": 5,
                        "message": "Deleted 5 batches older than 30 day(s)."
                    }
                }
            ),
            400: openapi.Response(
                description="Invalid parameter",
                examples={
                    "application/json": {
                        "error": "Invalid 'days' parameter. Must be a positive integer."
                    }
                }
            ),
            500: openapi.Response(
                description="Internal server error",
                examples={
                    "application/json": {
                        "error": "Failed to delete old batches",
                        "details": "Error details here"
                    }
                }
            ),
        }
    )
    @require_role('admin')  # Only admins can delete data
    def delete(self, request):
        """
        Delete all AIAnalyzedBatch objects older than a custom number of days.
        Use ?days=N (N must be a positive integer, default: 30)
        """
        try:
            days_param = request.query_params.get('days', '30')
            try:
                days = int(days_param)
                if days < 1:
                    raise ValueError
            except ValueError:
                return Response(
                    {"error": "Invalid 'days' parameter. Must be a positive integer."},
                    status=400
                )

            threshold = timezone.now() - timedelta(days=days)
            old_batches = AIAnalyzedBatch.objects.filter(created_at__lt=threshold)
            count = old_batches.count()
            
            # Log the deletion
            if count > 0:
                log_batch_delete(request, batch_count=count, retention_days=days)
            
            old_batches.delete()
            return Response(
                {
                    "deleted_batches": count,
                    "message": f"Deleted {count} batches older than {days} day(s)."
                },
                status=200
            )
        except Exception as e:
            logger.error(f"Error deleting old batches: {str(e)}")
            return Response(
                {"error": "Failed to delete old batches", "details": str(e)},
                status=500
            )


class SystemHealthView(OrgFilterMixin, APIView):
    """
    Calculate system health score (0-100) based on recent issues.
    Requires authentication. Only counts issues from user's organization.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """
        Calculate system health score (0-100) based on recent issues.
        Uses ratio-based scoring that scales with system size:
        - Resolution ratio: what % of issues are resolved (higher = healthier)
        - Critical ratio: what % of open issues are critical (higher = worse)
        Period: Last 24 hours by default.
        """
        try:
            import math

            # Time window: last 24 hours — used for resolved-in-window
            # bonus + activity-freshness hints only. Health itself now
            # reflects the CURRENT open state (bug fixed 2027-03):
            # previously we filtered ``recent_issues`` to only issues
            # ``created_at__gte=last_24h``, so an org with 9 open
            # critical issues from three days ago returned total=0
            # and health_score=100. Users trusted a green 100% while
            # actual reliability was on fire.
            last_24h = timezone.now() - timedelta(hours=24)

            base_queryset = self.filter_by_org(request, Issue.objects.all(), 'issue')

            # Currently-open issues drive the score.
            open_qs = base_queryset.filter(status='OPEN')
            recent_qs = base_queryset.filter(created_at__gte=last_24h)

            open_stats = open_qs.aggregate(
                open_count=Count('id'),
                critical=Count('id', filter=Q(severity='CRITICAL')),
                warning=Count('id', filter=Q(severity='WARNING')),
            )
            recent_stats = recent_qs.aggregate(
                total=Count('id'),
                resolved=Count('id', filter=Q(status='RESOLVED')),
            )

            open_count = open_stats['open_count']
            critical_count = open_stats['critical']
            warning_count = open_stats['warning']
            resolved_count = recent_stats['resolved']
            total = recent_stats['total']  # kept for API response compat

            if open_count == 0:
                # No open issues → healthy. A resolved-in-last-24h
                # bonus is implicit (they've been cleared).
                health_score = 100
            else:
                # Base 100, subtract per open issue by severity, cap
                # at 0. Weights tuned so a single critical drags
                # health into "Degraded" and three criticals push
                # into "Critical".
                penalty = (
                    critical_count * 20
                    + warning_count * 6
                    + max(0, open_count - critical_count - warning_count) * 2
                )
                # Small bonus for freshly-resolved work in the last
                # 24h (rewarded, but never enough to hide open pain).
                recovery_bonus = min(10, resolved_count * 2)
                health_score = round(max(0, min(100, 100 - penalty + recovery_bonus)))

            status_label = "Healthy"
            if health_score < 60:
                status_label = "Critical"
            elif health_score < 85:
                status_label = "Degraded"

            return Response({
                "health_score": health_score,
                "status": status_label,
                "metrics": {
                    "critical_last_24h": critical_count,
                    "warning_last_24h": warning_count,
                    "resolved_last_24h": resolved_count,
                    "open_last_24h": open_count
                }
            })
        except Exception as e:
            logger.error(f"Error calculating health score: {str(e)}")
            return Response({"error": str(e)}, status=500)


class ServiceReliabilityView(OrgFilterMixin, APIView):
    """
    Return top failing services/components based on issue count.
    Requires authentication. Filters by user's organization for data isolation.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            # Filter by user's organization
            base_issues = self.filter_by_org(request, Issue.objects.all(), 'issue')

            # Get top 5 failing components by component name
            top_components = base_issues.exclude(
                component__isnull=True
            ).exclude(
                component__exact=''
            ).values('component').annotate(
                count=Count('id')
            ).order_by('-count')[:5]

            # Format for frontend
            result = [
                {'name': item['component'], 'count': item['count']}
                for item in top_components
            ]

            return Response(result)

        except Exception as e:
            logger.error(f"Error getting service reliability: {str(e)}")
            return Response({"error": str(e)}, status=500)


class TrendAnalysisView(OrgFilterMixin, APIView):
    """
    Return daily issue counts for the last 7 days.
    Requires authentication. Filters by user's organization for data isolation.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            from django.db.models.functions import TruncDate

            # Today and the six days before it. The previous window ran
            # from seven days ago to yesterday, so today never showed.
            end_date = timezone.now()
            first_day = end_date.date() - timedelta(days=6)

            # Filter by user's organization
            base_issues = self.filter_by_org(request, Issue.objects.all(), 'issue')

            # Single query: group by date, aggregate critical + warning counts
            daily_data = base_issues.filter(
                created_at__date__gte=first_day,
                created_at__lte=end_date
            ).annotate(
                day=TruncDate('created_at')
            ).values('day').annotate(
                critical=Count('id', filter=Q(severity='CRITICAL')),
                warning=Count('id', filter=Q(severity='WARNING'))
            ).order_by('day')

            # Build a dict for quick lookup
            data_by_date = {
                item['day'].strftime("%Y-%m-%d"): item
                for item in daily_data
            }

            # Fill all 7 days (including days with zero issues)
            daily_stats = []
            for i in range(7):
                day = (first_day + timedelta(days=i)).strftime("%Y-%m-%d")
                entry = data_by_date.get(day)
                daily_stats.append({
                    "date": day,
                    "critical": entry['critical'] if entry else 0,
                    "warning": entry['warning'] if entry else 0
                })

            return Response(daily_stats)

        except Exception as e:
            logger.error(f"Error calculating trends: {str(e)}")
            return Response({"error": str(e)}, status=500)