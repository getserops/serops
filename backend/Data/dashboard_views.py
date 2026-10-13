"""
Dashboard Enhancement Views

API endpoints for advanced dashboard metrics:
1. MTTRView - Mean Time To Resolution
2. ServiceHealthView - Service health heatmap data
3. RootCauseStatsView - Root cause category breakdown
4. RecentDeploymentsView - Recent CI/CD pipelines per service
5. CorrelationInsightsView - AI correlation intelligence summary
6. RecentAnalysisFeedView - Latest AI analysis results feed
"""

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.db.models import Count, Avg, Q, F, ExpressionWrapper, fields
from django.core.cache import cache
from datetime import timedelta
from .models import AIAnalyzedBatch, Issue
from notifications.models import Notification
from Projects.models import Project
import logging
import hashlib

logger = logging.getLogger(__name__)

# Phase 2: Cache TTLs enabled for performance optimization
# Different TTLs based on data freshness requirements
CACHE_TTL_DASHBOARD = 60 * 5   # 5 minutes for dashboards (updated frequently)
CACHE_TTL_STATS = 60 * 15      # 15 minutes for stats (slower changing)
CACHE_TTL_CONFIG = 60 * 60     # 1 hour for org/project configs (rarely change)


# OrgFilterMixin moved to Data.mixins so dashboard_views.py and
# views.py share one source of truth.
#
# Note: the previous dashboard-side filter methods filtered via
# ``project__organisation`` (a join through the project table). The
# canonical mixin now filters via the direct ``organisation`` FK on
# Batch/Issue — same results, one column index instead of a join,
# and correctly includes rows without a project link.
from .mixins import OrgFilterMixin  # noqa: E402,F401 — public re-export


@method_decorator(cache_page(CACHE_TTL_STATS), name='dispatch')
class MTTRView(OrgFilterMixin, APIView):
    """
    Calculate Mean Time To Resolution for issues.
    Requires authentication. Filters by user's organization.

    Cached for 15 minutes (CACHE_TTL_STATS) as MTTR changes slowly.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            # Time window (default: last 30 days)
            days = int(request.query_params.get('days', 30))

            # Use org-specific cache key
            org_id = self.get_user_org_id(request)
            cache_key = f"mttr_stats_{days}_org_{org_id}"
            cached_result = cache.get(cache_key)
            if cached_result:
                return Response(cached_result)

            since = timezone.now() - timedelta(days=days)

            # Get resolved issues with resolved_at timestamps
            base_issues = self.filter_issues_by_org(request, Issue.objects.all())
            resolved_issues = base_issues.filter(
                status='RESOLVED',
                resolved_at__isnull=False,
                created_at__gte=since
            ).only('id', 'severity', 'created_at', 'resolved_at').order_by('-resolved_at')[:200]

            # Calculate time deltas per issue
            mttr_data = []
            by_severity = {'CRITICAL': [], 'WARNING': []}

            for issue in resolved_issues:
                delta = issue.resolved_at - issue.created_at
                hours = delta.total_seconds() / 3600

                # Only include reasonable values (> 0 and < 30 days)
                if 0 < hours < 720:
                    mttr_data.append(hours)
                    sev = issue.severity if issue.severity in by_severity else 'WARNING'
                    by_severity[sev].append(hours)

            if not mttr_data:
                result = {
                    'overall_mttr_hours': 0,
                    'by_severity': {},
                    'trend': 'STABLE',
                    'sample_size': 0,
                    'message': 'No resolved issues found'
                }
                cache.set(cache_key, result, CACHE_TTL_STATS)
                return Response(result)

            # Calculate averages
            overall_mttr = sum(mttr_data) / len(mttr_data)

            severity_stats = {}
            for sev, times in by_severity.items():
                if times:
                    severity_stats[sev] = {
                        'avg_hours': round(sum(times) / len(times), 2),
                        'count': len(times)
                    }

            # Simple trend: compare first half (recent) vs second half (older)
            mid = len(mttr_data) // 2
            if mid > 5:
                recent_avg = sum(mttr_data[:mid]) / mid
                older_avg = sum(mttr_data[mid:]) / (len(mttr_data) - mid)
                diff = ((recent_avg - older_avg) / older_avg) * 100 if older_avg else 0

                if diff < -10:
                    trend = 'IMPROVING'
                elif diff > 10:
                    trend = 'DEGRADING'
                else:
                    trend = 'STABLE'
            else:
                trend = 'STABLE'

            result = {
                'overall_mttr_hours': round(overall_mttr, 2),
                'by_severity': severity_stats,
                'trend': trend,
                'sample_size': len(mttr_data)
            }
            cache.set(cache_key, result, CACHE_TTL_STATS)
            return Response(result)

        except Exception as e:
            logger.error(f"Error calculating MTTR: {e}")
            return Response({
                'overall_mttr_hours': 0,
                'by_severity': {},
                'trend': 'UNKNOWN',
                'sample_size': 0,
                'error': str(e)
            })



@method_decorator(cache_page(CACHE_TTL_DASHBOARD), name='dispatch')
class ServiceHealthView(OrgFilterMixin, APIView):
    """
    Service health heatmap data.
    Requires authentication. Filters by user's organization.

    Queries registered services from the Service model and calculates
    health scores based on Issue counts per service.

    Cached for 5 minutes (CACHE_TTL_DASHBOARD) for frequently refreshed dashboards.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        from Services.models import Service
        from Projects.models import ProjectService
        
        try:
            # Time window (default: last 7 days)
            days = int(request.query_params.get('days', 7))
            since = timezone.now() - timedelta(days=days)
            
            # Get user's organization
            user_org = getattr(request.user, 'organisation', None)
            if not user_org:
                return Response({
                    'services': [],
                    'total_services': 0,
                    'message': 'No organization found'
                })
            
            # Item #17 / Q1.4: optionally scope to a single cluster.
            cluster_id = self._get_cluster_id(request)
            cluster_kwargs = (
                {'project__cluster_id': cluster_id} if cluster_id is not None else {}
            )

            # Strategy 1: Get services from the Service model (new architecture)
            org_services = Service.objects.filter(
                project__organisation=user_org, **cluster_kwargs,
            ).select_related('project')[:50]

            # Strategy 2: Also get services from ProjectService (legacy)
            project_services = ProjectService.objects.filter(
                project__organisation=user_org, **cluster_kwargs,
            ).select_related('project')[:50]
            
            services_list = []
            
            # Process Service model entries
            for service in org_services:
                # Get issue stats for this service with SINGLE aggregation query
                # This replaces 4 separate count() queries with 1 aggregate() query
                service_filter = Q(description__icontains=service.name) | \
                                Q(error_class__icontains=service.name) | \
                                Q(component__icontains=service.name)

                stats = Issue.objects.filter(
                    batch__project__organisation=user_org,
                    created_at__gte=since
                ).filter(service_filter).aggregate(
                    total_issues=Count('id'),
                    critical_count=Count('id', filter=Q(severity='CRITICAL')),
                    error_count=Count('id', filter=Q(severity__in=['CRITICAL', 'WARNING'])),
                    resolved_count=Count('id', filter=Q(status='RESOLVED'))
                )

                total_issues = stats['total_issues']
                critical_count = stats['critical_count']
                error_count = stats['error_count']
                resolved_count = stats['resolved_count']
                
                # Calculate health score
                if total_issues == 0:
                    health_score = 100.0  # No issues = healthy
                else:
                    # Base health minus penalties for unresolved issues
                    unresolved = total_issues - resolved_count
                    error_penalty = (unresolved / max(total_issues, 1)) * 60
                    critical_penalty = (critical_count / max(total_issues, 1)) * 30
                    health_score = 100 - error_penalty - critical_penalty
                    health_score = max(0, min(100, health_score))
                
                # Determine status based on health score
                if health_score >= 80:
                    status_val = 'healthy'
                elif health_score >= 50:
                    status_val = 'degraded'
                else:
                    status_val = 'critical'
                
                # Also consider service status field
                if service.status == 'error':
                    status_val = 'critical'
                    health_score = min(health_score, 30)
                elif service.status == 'maintenance':
                    status_val = 'degraded'
                    health_score = min(health_score, 70)
                
                services_list.append({
                    'name': service.name,
                    'health_score': round(health_score, 1),
                    'status': status_val,
                    'total_issues': total_issues,
                    'error_count': error_count,
                    'critical_issues': critical_count,
                    'category': service.category
                })
            
            # Process ProjectService entries (legacy services with GitLab)
            seen_names = {s['name'].lower() for s in services_list}
            
            for ps in project_services:
                service_name = ps.name or (ps.gitlab_project.name if ps.gitlab_project else None)
                if not service_name or service_name.lower() in seen_names:
                    continue
                
                # Get issue stats for this service with SINGLE aggregation query
                service_filter = Q(description__icontains=service_name) | \
                                Q(error_class__icontains=service_name) | \
                                Q(component__icontains=service_name)

                stats = Issue.objects.filter(
                    batch__project__organisation=user_org,
                    created_at__gte=since
                ).filter(service_filter).aggregate(
                    total_issues=Count('id'),
                    critical_count=Count('id', filter=Q(severity='CRITICAL')),
                    error_count=Count('id', filter=Q(severity__in=['CRITICAL', 'WARNING'])),
                    resolved_count=Count('id', filter=Q(status='RESOLVED'))
                )

                total_issues = stats['total_issues']
                critical_count = stats['critical_count']
                error_count = stats['error_count']
                resolved_count = stats['resolved_count']
                
                # Calculate health score
                if total_issues == 0:
                    health_score = 100.0
                else:
                    unresolved = total_issues - resolved_count
                    error_penalty = (unresolved / max(total_issues, 1)) * 60
                    critical_penalty = (critical_count / max(total_issues, 1)) * 30
                    health_score = 100 - error_penalty - critical_penalty
                    health_score = max(0, min(100, health_score))
                
                if health_score >= 80:
                    status_val = 'healthy'
                elif health_score >= 50:
                    status_val = 'degraded'
                else:
                    status_val = 'critical'
                
                # D2 fix: was hard-coded ``'scm'`` for every ProjectService.
                # Real service_type values are 'infrastructure',
                # 'application', 'custom' etc. Using them lets the frontend
                # heatmap group services meaningfully (databases together,
                # apps together, workers together).
                services_list.append({
                    'name': service_name,
                    'health_score': round(health_score, 1),
                    'status': status_val,
                    'total_issues': total_issues,
                    'error_count': error_count,
                    'critical_issues': critical_count,
                    'category': ps.service_type or 'other',
                })
                seen_names.add(service_name.lower())
            
            # Sort by health score (worst first for visibility)
            services_list.sort(key=lambda x: x['health_score'])
            
            return Response({
                'services': services_list[:12],  # Limit to 12 for grid
                'total_services': len(services_list)
            })
            
        except Exception as e:
            logger.error(f"Error getting service health: {e}")
            return Response({
                'services': [],
                'total_services': 0,
                'error': str(e)
            })




@method_decorator(cache_page(CACHE_TTL_STATS), name='dispatch')
class RootCauseStatsView(OrgFilterMixin, APIView):
    """
    Root cause category breakdown.
    Categorizes issues into Infrastructure, Code, Configuration, etc.
    Requires authentication. Filters by user's organization for data isolation.

    Cached for 15 minutes (CACHE_TTL_STATS) as root cause stats change slowly.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            # Time window (default: last 30 days)
            days = int(request.query_params.get('days', 30))
            since = timezone.now() - timedelta(days=days)
            
            # Get issues with root causes from Issue model - FILTERED BY ORG
            base_issues = self.filter_issues_by_org(request, Issue.objects.all())
            issues = base_issues.filter(
                created_at__gte=since,
                root_cause__isnull=False
            ).exclude(root_cause='')[:1000]
            
            categories = {
                'Code': 0,
                'Infrastructure': 0,
                'Configuration': 0,
                'Dependency': 0,
                'Unknown': 0
            }
            
            # Keywords for categorization
            code_keywords = ['bug', 'function', 'syntax', 'logic', 'exception', 'error', 'code', 'null', 'undefined']
            infra_keywords = ['memory', 'cpu', 'disk', 'timeout', 'crash', 'resource', 'capacity', 'network', 'connection']
            config_keywords = ['config', 'setting', 'env', 'permission', 'variable', 'parameter']
            dependency_keywords = ['dependency', 'package', 'library', 'version', 'module', 'import']
            
            for issue in issues:
                # root_cause can be dict or string
                root_cause = issue.root_cause
                if isinstance(root_cause, dict):
                    # Extract text from dict (e.g. {'description': '...'})
                    root_cause_text = str(root_cause.get('description', '')) + ' ' + str(root_cause)
                else:
                    root_cause_text = str(root_cause) if root_cause else ''
                
                if not root_cause_text:
                    categories['Unknown'] += 1
                    continue
                
                root_cause_lower = root_cause_text.lower()
                
                categorized = False
                if any(kw in root_cause_lower for kw in infra_keywords):
                    categories['Infrastructure'] += 1
                    categorized = True
                elif any(kw in root_cause_lower for kw in code_keywords):
                    categories['Code'] += 1
                    categorized = True
                elif any(kw in root_cause_lower for kw in config_keywords):
                    categories['Configuration'] += 1
                    categorized = True
                elif any(kw in root_cause_lower for kw in dependency_keywords):
                    categories['Dependency'] += 1
                    categorized = True
                
                if not categorized:
                    categories['Unknown'] += 1
            
            total = sum(categories.values())
            
            if total == 0:
                return Response({
                    'breakdown': [],
                    'total_issues': 0,
                    'message': 'No root cause data found'
                })
            
            # Calculate percentages
            breakdown = []
            for category, count in categories.items():
                if count > 0:
                    percentage = (count / total * 100)
                    breakdown.append({
                        'category': category,
                        'count': count,
                        'percentage': round(percentage, 1)
                    })
            
            # Sort by count (descending)
            breakdown.sort(key=lambda x: x['count'], reverse=True)
            
            return Response({
                'breakdown': breakdown,
                'total_issues': total
            })
            
        except Exception as e:
            logger.error(f"Error getting root cause stats: {e}")
            return Response({
                'breakdown': [],
                'total_issues': 0,
                'error': str(e)
            })



class RecentDeploymentsView(OrgFilterMixin, APIView):
    """
    Recent CI/CD deployments per service.
    Returns the latest pipelines for each service with CI/CD configured.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        from providers.models import Pipeline, GitlabProject
        from Projects.models import ProjectService, SCMBinding

        try:
            # Use org-specific cache key
            org_id = self.get_user_org_id(request)
            # CACHE DISABLED

            user_org = getattr(request.user, 'organisation', None)
            if not user_org:
                return Response({'services': [], 'total_services': 0})

            # D1 fix: old query filtered on ``gitlab_project__isnull=False``
            # which only matched the legacy GitlabProject FK. Post-Batch
            # 47-55 rework, services connect to repos via ``SCMBinding``
            # (repository_id) — legacy field is unset on new-style
            # services. Include both paths so deployments show for
            # everyone.
            services = ProjectService.objects.filter(
                project__organisation=user_org,
            ).filter(
                Q(gitlab_project__isnull=False)
                | Q(scm_binding__isnull=False)
            ).select_related('gitlab_project', 'project', 'scm_binding').distinct()

            # Item #17 / Q1.4 — cluster filter.
            cluster_id = self._get_cluster_id(request)
            if cluster_id is not None:
                services = services.filter(project__cluster_id=cluster_id)

            deployments = []

            for service in services[:10]:  # Limit to 10 services
                gitlab_project = service.gitlab_project
                # New-style services use SCMBinding.repository_id which
                # matches Pipeline.external_project_id. Legacy uses
                # ``project=gitlab_project``. Try both.
                pipeline_q = Q()
                repo_display = None
                if gitlab_project:
                    pipeline_q |= Q(project=gitlab_project)
                    repo_display = gitlab_project.name
                scm_binding = getattr(service, 'scm_binding', None)
                if scm_binding and scm_binding.repository_id:
                    pipeline_q |= Q(external_project_id=scm_binding.repository_id)
                    repo_display = repo_display or scm_binding.repository_name or scm_binding.repository_id
                if not pipeline_q:
                    continue

                pipelines = Pipeline.objects.filter(
                    pipeline_q, organisation=user_org,
                ).order_by('-created_at')[:3]
                
                if not pipelines.exists():
                    # No pipelines yet, still show service
                    deployments.append({
                        'service_id': service.id,
                        'service_name': service.name or repo_display or 'Unknown',
                        'project_name': service.project.name if service.project else 'Unknown',
                        'provider': 'gitlab',
                        'latest_pipeline': None,
                        'recent_pipelines': [],
                        'success_rate': None
                    })
                    continue
                
                # Calculate success rate from recent pipelines
                recent_list = []
                success_count = 0
                total_count = 0
                
                for p in pipelines:
                    status_lower = p.status.lower() if p.status else 'unknown'
                    is_success = status_lower in ['success', 'passed', 'completed']
                    if status_lower not in ['pending', 'running', 'created']:
                        total_count += 1
                        if is_success:
                            success_count += 1
                    
                    recent_list.append({
                        'id': p.pipeline_id,
                        'status': p.status,
                        'branch': p.branch,
                        'environment': p.environment,
                        'created_at': p.created_at.isoformat() if p.created_at else None
                    })
                
                success_rate = round((success_count / total_count) * 100) if total_count > 0 else None
                
                deployments.append({
                    'service_id': service.id,
                    'service_name': service.name or repo_display or 'Unknown',
                    'project_name': service.project.name if service.project else 'Unknown',
                    'provider': pipelines[0].cicd_provider if pipelines else 'unknown',
                    'latest_pipeline': recent_list[0] if recent_list else None,
                    'recent_pipelines': recent_list,
                    'success_rate': success_rate
                })
            
            # Sort by most recent pipeline first
            deployments.sort(
                key=lambda x: x['latest_pipeline']['created_at'] if x.get('latest_pipeline') else '',
                reverse=True
            )
            
            result = {
                'services': deployments,
                'total_services': len(deployments)
            }
            # cache.set(cache_key, result, CACHE_TTL)
            return Response(result)
            
        except Exception as e:
            logger.error(f"Error getting recent deployments: {e}")
            return Response({
                'services': [],
                'total_services': 0,
                'error': str(e)
            })


@method_decorator(cache_page(CACHE_TTL_DASHBOARD), name='dispatch')
class CorrelationInsightsView(OrgFilterMixin, APIView):
    """
    AI Correlation Intelligence summary.
    Shows how many issues have been correlated with deployments (commit links)
    and metric spikes (memory/CPU), which is the core differentiator of SerOps.

    Cached for 5 minutes.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            days = int(request.query_params.get('days', 7))
            since = timezone.now() - timedelta(days=days)

            base_issues = self.filter_issues_by_org(request, Issue.objects.all())
            recent = base_issues.filter(created_at__gte=since)

            stats = recent.aggregate(
                total=Count('id'),
                with_commits=Count('id', filter=Q(has_commit_correlation=True)),
                with_metrics=Count('id', filter=Q(has_metric_correlation=True)),
                memory_corr=Count('id', filter=Q(metric_correlation_type='memory')),
                cpu_corr=Count('id', filter=Q(metric_correlation_type='cpu')),
                # v5 engine-driven aggregates
                anomaly_spike=Count('id', filter=Q(metric_anomaly_type='spike')),
                anomaly_sustained=Count('id', filter=Q(metric_anomaly_type='sustained_high')),
                high_confidence=Count('id', filter=Q(correlation_confidence='HIGH')),
                # v6 CI/CD correlations
                cicd_corr=Count('id', filter=Q(has_cicd_correlation=True)),
            )

            total = stats['total'] or 0
            with_commits = stats['with_commits'] or 0
            with_metrics = stats['with_metrics'] or 0

            # Top correlated components (issues with any correlation)
            top_components = recent.filter(
                Q(has_commit_correlation=True) | Q(has_metric_correlation=True) | Q(has_cicd_correlation=True)
            ).exclude(
                component=''
            ).values('component').annotate(
                count=Count('id')
            ).order_by('-count')[:5]

            return Response({
                'total_issues': total,
                'commit_correlations': with_commits,
                'metric_correlations': with_metrics,
                'metric_breakdown': {
                    'memory': stats['memory_corr'] or 0,
                    'cpu': stats['cpu_corr'] or 0,
                },
                'anomaly_type_breakdown': {
                    'spike': stats['anomaly_spike'] or 0,
                    'sustained_high': stats['anomaly_sustained'] or 0,
                },
                'high_confidence_count': stats['high_confidence'] or 0,
                'cicd_correlations': stats['cicd_corr'] or 0,
                'correlation_rate': round(
                    ((with_commits + with_metrics) / max(total, 1)) * 100, 1
                ),
                'top_correlated_components': list(top_components),
                'period_days': days,
            })

        except Exception as e:
            logger.error(f"Error getting correlation insights: {e}")
            return Response({
                'total_issues': 0,
                'commit_correlations': 0,
                'metric_correlations': 0,
                'metric_breakdown': {'memory': 0, 'cpu': 0},
                'correlation_rate': 0,
                'top_correlated_components': [],
                'period_days': 7,
                'error': str(e)
            })


@method_decorator(cache_page(CACHE_TTL_DASHBOARD), name='dispatch')
class RecentAnalysisFeedView(OrgFilterMixin, APIView):
    """
    Latest AI analysis results feed.
    Returns the most recent batch analyses with summary text, severity counts,
    and environment info for the dashboard feed widget.

    Cached for 5 minutes.
    """
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _extract_summary(analysis_text):
        """
        Extract a human-readable summary from analysis_text.
        The field may be a JSON/dict string (structured AI output) or plain text.
        """
        import ast
        import json

        if not analysis_text:
            return ''

        text = str(analysis_text).strip()

        # Try to parse as structured data (dict/JSON)
        parsed = None
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            try:
                parsed = ast.literal_eval(text)
            except (ValueError, SyntaxError):
                pass

        if isinstance(parsed, dict):
            # Strategy 1: Build summary from structured fields
            parts = []
            summary_data = parsed.get('summary', {})
            health = summary_data.get('overall_health', '')
            if health:
                parts.append(f"Health: {health}")

            # Get first issue description as the key finding
            issues = parsed.get('correlated_issues', [])
            if issues and isinstance(issues, list):
                first = issues[0] if issues else {}
                desc = first.get('description', '')
                if desc:
                    # Truncate to first sentence
                    sentence = desc.split('.')[0].strip()
                    parts.append(sentence)

            # Get top recommendation if no issue description
            if len(parts) <= 1:
                recs = parsed.get('recommendations', [])
                if recs and isinstance(recs, list):
                    first_rec = recs[0]
                    action = first_rec.get('action', '') if isinstance(first_rec, dict) else str(first_rec)
                    if action:
                        sentence = action.split('.')[0].strip()
                        parts.append(sentence)

            result = '. '.join(parts)
            if result and not result.endswith('.'):
                result += '.'
            return result[:200] if result else 'Analysis completed.'

        # Plain text: extract first sentence
        sentence = text.split('.')[0].strip()
        if len(sentence) > 200:
            sentence = sentence[:197] + '...'
        elif sentence and not sentence.endswith('.'):
            sentence += '.'
        return sentence

    def get(self, request):
        try:
            limit = min(int(request.query_params.get('limit', 5)), 10)

            base_batches = self.filter_batches_by_org(request, AIAnalyzedBatch.objects.all())

            batches = base_batches.filter(
                analysis_text__isnull=False,
            ).exclude(
                analysis_text__exact='',
            ).order_by('-analyzed_at')[:limit]

            feed = []
            # Get issue counts in a single query
            batch_ids = [b.id for b in batches]
            issue_stats = Issue.objects.filter(
                batch_id__in=batch_ids
            ).values('batch_id').annotate(
                total=Count('id'),
                critical=Count('id', filter=Q(severity='CRITICAL')),
                warning=Count('id', filter=Q(severity='WARNING')),
            )
            stats_map = {s['batch_id']: s for s in issue_stats}

            for batch in batches:
                summary = self._extract_summary(batch.analysis_text)
                s = stats_map.get(batch.id, {})

                feed.append({
                    'batch_id': batch.batch_id,
                    'analyzed_at': batch.analyzed_at.isoformat() if batch.analyzed_at else None,
                    'environment': batch.environment or 'unknown',
                    'model_name': batch.model_name or '',
                    'summary': summary,
                    'issue_count': s.get('total', 0),
                    'critical_count': s.get('critical', 0),
                    'warning_count': s.get('warning', 0),
                })

            return Response({
                'feed': feed,
                'total_analyses': base_batches.filter(
                    analysis_text__isnull=False
                ).exclude(analysis_text__exact='').count(),
            })

        except Exception as e:
            logger.error(f"Error getting analysis feed: {e}")
            return Response({
                'feed': [],
                'total_analyses': 0,
                'error': str(e)
            })


class SentinelStatsView(OrgFilterMixin, APIView):
    """Sentinel decision distribution and AI savings stats."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            org_id = self.get_user_org_id(request)
            days = int(request.query_params.get('days', 7))
            environment = request.query_params.get('environment')

            since = timezone.now() - timedelta(days=days)
            qs = AIAnalyzedBatch.objects.filter(timestamp__gte=since)
            if org_id:
                qs = qs.filter(organisation_id=org_id)
            if environment and environment != 'all':
                qs = qs.filter(environment__iexact=environment)
            # Scope the batch counts to the selected cluster so this
            # widget agrees with the rest of the dashboard. The cost
            # *rate* below stays org-wide on purpose — see
            # _derive_cost_rate.
            cluster_id = self._get_cluster_id(request)
            if cluster_id is not None:
                qs = qs.filter(project__cluster_id=cluster_id)

            total = qs.count()
            decisions = qs.values('sentinel_decision').annotate(count=Count('id'))
            decision_map = {d['sentinel_decision']: d['count'] for d in decisions}

            skipped = qs.filter(ai_skipped=True).count()
            analyzed = total - skipped

            # Estimate savings (avg tokens per batch * skipped)
            avg_tokens = qs.filter(ai_skipped=False, token_count__gt=0).aggregate(
                avg=Avg('token_count')
            )['avg'] or 0
            estimated_tokens_saved = int(avg_tokens * skipped)

            # Convert tokens saved → USD saved using THIS org's actual
            # cost-per-token over the same window. We prefer a measured
            # rate over a list-price estimate because the org may be
            # using a mix of cheap and expensive models. Falls back to
            # 0.0 when there is no usage data yet (greenfield orgs).
            cost_per_token, ai_spend_usd = self._derive_cost_rate(org_id, since, environment)
            estimated_cost_saved_usd = round(cost_per_token * estimated_tokens_saved, 4)

            return Response({
                'period_days': days,
                'total_batches': total,
                'decisions': {
                    'alert': decision_map.get('alert', 0),
                    'quiet': decision_map.get('quiet', 0),
                    'first': decision_map.get('first', 0),
                    'shadow': decision_map.get('shadow', 0),
                },
                'ai_analyzed': analyzed,
                'ai_skipped': skipped,
                'skip_rate_percent': round((skipped / total * 100) if total else 0, 1),
                'estimated_tokens_saved': estimated_tokens_saved,
                # Hero metric for the dashboard widget. Both values are
                # derived from this org's own usage so the savings claim
                # is defensible rather than a marketing estimate.
                'estimated_cost_saved_usd': estimated_cost_saved_usd,
                'ai_spend_usd': round(float(ai_spend_usd), 4),
            })
        except Exception as e:
            logger.error(f"Error getting sentinel stats: {e}")
            return Response({
                'period_days': days if 'days' in dir() else 7,
                'total_batches': 0,
                'decisions': {'alert': 0, 'quiet': 0, 'first': 0, 'shadow': 0},
                'ai_analyzed': 0,
                'ai_skipped': 0,
                'skip_rate_percent': 0,
                'estimated_tokens_saved': 0,
                'estimated_cost_saved_usd': 0,
                'ai_spend_usd': 0,
                'error': str(e)
            })

    @staticmethod
    def _derive_cost_rate(org_id, since, environment):
        """Compute (cost_per_token_usd, total_spend_usd) from the org's
        own recent AI token usage. Returns (0.0, 0.0) when there is no
        usage data — the hero widget then shows $0 saved rather than
        an invented figure."""
        from ai_model.models import AITokenUsage
        from django.db.models import Sum

        qs = AITokenUsage.objects.filter(timestamp__gte=since)
        if org_id:
            qs = qs.filter(organisation_id=org_id)
        # AITokenUsage doesn't carry environment directly; the batch FK
        # does, but cost is per-call and the rate is the same regardless
        # of environment, so we skip environment filtering here.

        agg = qs.aggregate(tokens=Sum('tokens_total'), cost=Sum('cost_usd'))
        total_tokens = agg['tokens'] or 0
        total_cost = float(agg['cost'] or 0)
        if total_tokens <= 0:
            return 0.0, total_cost
        return total_cost / total_tokens, total_cost
