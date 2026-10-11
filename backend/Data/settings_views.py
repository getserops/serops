"""
Settings API Views
Security Settings, Audit Log, Data Usage, and Retention Policy endpoints
"""

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from django.utils import timezone
from django.db.models import Count, Q
from django.http import HttpResponse
from datetime import timedelta
import csv

from .models import AuditLog, RetentionPolicy, AIAnalyzedBatch, Issue
from Users.models import SecuritySettings
from Users.permissions import require_role


class SecuritySettingsView(APIView):
    """Manage organization security settings"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get current security settings"""
        org = request.user.organisation
        if not org:
            return Response({'error': 'No organisation found'}, status=400)
        
        # Get or create settings
        settings, created = SecuritySettings.objects.get_or_create(organisation=org)
        
        return Response({
            'password_policy': {
                'min_length': settings.min_password_length,
                'require_uppercase': settings.require_uppercase,
                'require_lowercase': settings.require_lowercase,
                'require_numbers': settings.require_numbers,
                'require_special_chars': settings.require_special_chars,
                'expiry_days': settings.password_expiry_days,
            },
            'session': {
                'timeout_minutes': settings.session_timeout_minutes,
                'timeout_choices': dict(SecuritySettings.SESSION_TIMEOUT_CHOICES),
            },
            'sso': {
                'enabled': settings.sso_enabled,
                'provider': settings.sso_provider,
                'provider_choices': dict(SecuritySettings.SSO_TYPES),
            }
        })
    
    @require_role('admin')
    def put(self, request):
        """Update security settings (admin only)"""
        
        org = request.user.organisation
        settings, _ = SecuritySettings.objects.get_or_create(organisation=org)
        
        data = request.data
        
        # Update password policy
        if 'password_policy' in data:
            pp = data['password_policy']
            if 'min_length' in pp:
                settings.min_password_length = max(6, min(32, pp['min_length']))
            if 'require_uppercase' in pp:
                settings.require_uppercase = pp['require_uppercase']
            if 'require_lowercase' in pp:
                settings.require_lowercase = pp['require_lowercase']
            if 'require_numbers' in pp:
                settings.require_numbers = pp['require_numbers']
            if 'require_special_chars' in pp:
                settings.require_special_chars = pp['require_special_chars']
            if 'expiry_days' in pp:
                settings.password_expiry_days = max(0, pp['expiry_days'])
        
        # Update session settings
        if 'session' in data:
            if 'timeout_minutes' in data['session']:
                valid_timeouts = [t[0] for t in SecuritySettings.SESSION_TIMEOUT_CHOICES]
                if data['session']['timeout_minutes'] in valid_timeouts:
                    settings.session_timeout_minutes = data['session']['timeout_minutes']
        
        settings.save()
        
        # Log the change
        from .audit import log_settings_change
        log_settings_change(request, 'security_settings', 'updated', 'updated')
        
        return Response({'success': True, 'message': 'Security settings updated'})


class AuditLogView(APIView):
    """View and filter audit logs"""
    permission_classes = [IsAuthenticated]
    
    @require_role('admin')
    def get(self, request):
        """List audit logs with filtering and pagination"""
        
        org = request.user.organisation
        logs = AuditLog.objects.filter(organisation=org)
        
        # Filters
        action = request.query_params.get('action')
        if action:
            logs = logs.filter(action=action)
        
        user_id = request.query_params.get('user_id')
        if user_id:
            logs = logs.filter(user_id=user_id)
        
        date_from = request.query_params.get('date_from')
        if date_from:
            logs = logs.filter(created_at__gte=date_from)
        
        date_to = request.query_params.get('date_to')
        if date_to:
            logs = logs.filter(created_at__lte=date_to)
        
        search = request.query_params.get('search')
        if search:
            logs = logs.filter(details__icontains=search)
        
        # Pagination
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 25))
        
        total = logs.count()
        start = (page - 1) * page_size
        end = start + page_size
        
        logs_page = logs[start:end]
        
        return Response({
            'logs': [{
                'id': log.id,
                'action': log.action,
                'action_display': log.get_action_display(),
                'user': log.user.email if log.user else 'System',
                'details': log.details,
                'ip_address': log.ip_address,
                'created_at': log.created_at.isoformat(),
            } for log in logs_page],
            'pagination': {
                'page': page,
                'page_size': page_size,
                'total': total,
                'total_pages': (total + page_size - 1) // page_size,
            },
            'action_types': dict(AuditLog.ACTION_TYPES),
        })


class AuditLogExportView(APIView):
    """Export audit logs as CSV"""
    permission_classes = [IsAuthenticated]
    
    @require_role('admin')
    def get(self, request):
        """Export audit logs as CSV"""
        
        org = request.user.organisation
        logs = AuditLog.objects.filter(organisation=org)

        # Apply same filters as list view — must match AuditLogView.get
        # so the exported CSV reflects exactly what the admin sees on
        # screen. Missing filters here caused "why does my export have
        # rows for other users?" reports.
        action = request.query_params.get('action')
        if action:
            logs = logs.filter(action=action)

        user_id = request.query_params.get('user_id')
        if user_id:
            logs = logs.filter(user_id=user_id)

        date_from = request.query_params.get('date_from')
        if date_from:
            logs = logs.filter(created_at__gte=date_from)

        date_to = request.query_params.get('date_to')
        if date_to:
            logs = logs.filter(created_at__lte=date_to)

        # Limit export size
        logs = logs[:10000]
        
        # Create CSV response
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="audit_log_{timezone.now().strftime("%Y%m%d")}.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['Timestamp', 'Action', 'User', 'Details', 'IP Address'])
        
        for log in logs:
            writer.writerow([
                log.created_at.isoformat(),
                log.get_action_display(),
                log.user.email if log.user else 'System',
                str(log.details),
                log.ip_address or '',
            ])
        
        # Log the export
        from .audit import log_action
        log_action(request, 'EXPORT_DATA', {'type': 'audit_log', 'count': logs.count()})
        
        return response


class DataUsageView(APIView):
    """Get data usage statistics for the organization"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get data usage breakdown"""
        org = request.user.organisation
        if not org:
            return Response({'error': 'No organisation found'}, status=400)
        
        # Get batch counts - AIAnalyzedBatch.project -> Projects.Project -> organisation
        batches = AIAnalyzedBatch.objects.filter(project__organisation=org)
        total_batches = batches.count()
        
        # Get issue counts - Issue.batch -> AIAnalyzedBatch.project -> Projects.Project -> organisation
        issues = Issue.objects.filter(batch__project__organisation=org)
        total_issues = issues.count()
        
        # Get pipeline counts - direct org FK or via GitlabProject FK
        from providers.models import Pipeline
        pipelines = Pipeline.objects.filter(
            Q(organisation=org) | Q(project__organisation=org)
        ).distinct()
        total_pipelines = pipelines.count()
        
        # Get by project breakdown (Projects.Project with batches)
        from Projects.models import Project
        projects = Project.objects.filter(organisation=org)
        by_project = []
        for project in projects[:20]:  # Limit to top 20
            project_batches = batches.filter(project=project).count()
            project_issues = issues.filter(batch__project=project).count()
            by_project.append({
                'name': project.name,
                'id': project.id,
                'batches': project_batches,
                'issues': project_issues,
            })
        
        # Sort by batch count
        by_project.sort(key=lambda x: x['batches'], reverse=True)
        
        # Get oldest data
        oldest_batch = batches.order_by('created_at').first()
        oldest_date = oldest_batch.created_at.isoformat() if oldest_batch else None
        
        # Get retention preview
        retention_policy, _ = RetentionPolicy.objects.get_or_create(organisation=org)
        cutoff_date = timezone.now() - timedelta(days=retention_policy.retention_days)
        batches_to_delete = batches.filter(created_at__lt=cutoff_date).count()
        
        total_records = total_batches + total_issues + total_pipelines

        return Response({
            'total_records': total_records,
            'totals': {
                'batches': total_batches,
                'issues': total_issues,
                'pipelines': total_pipelines,
            },
            'by_project': by_project,  # Changed from by_service
            'oldest_data': oldest_date,
            'retention_preview': {
                'retention_days': retention_policy.retention_days,
                'batches_to_delete': batches_to_delete,
                'cutoff_date': cutoff_date.isoformat(),
            }
        })


class RetentionPolicyView(APIView):
    """Manage data retention policy"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get current retention policy"""
        org = request.user.organisation
        if not org:
            return Response({'error': 'No organisation found'}, status=400)
        
        policy, _ = RetentionPolicy.objects.get_or_create(organisation=org)
        
        return Response({
            'auto_cleanup_enabled': policy.auto_cleanup_enabled,
            'retention_days': policy.retention_days,
            'retention_choices': dict(RetentionPolicy.RETENTION_CHOICES),
            'cleanup_frequency': policy.cleanup_frequency,
            'frequency_choices': dict(RetentionPolicy.FREQUENCY_CHOICES),
            'audit_log_retention_days': policy.audit_log_retention_days,
            'audit_retention_choices': dict(RetentionPolicy.AUDIT_RETENTION_CHOICES),
            'raw_metrics_retention_days': policy.raw_metrics_retention_days,
            'raw_metrics_retention_choices': dict(
                RetentionPolicy.RAW_METRICS_RETENTION_CHOICES),
            'batch_generation_interval': policy.batch_generation_interval,
            'batch_interval_choices': dict(RetentionPolicy.BATCH_INTERVAL_CHOICES),
            'last_cleanup': {
                'at': policy.last_cleanup_at.isoformat() if policy.last_cleanup_at else None,
                'count': policy.last_cleanup_count,
            },
            'next_cleanup': policy.next_cleanup_at.isoformat() if policy.next_cleanup_at else None,
        })
    
    @require_role('admin')
    def put(self, request):
        """Update retention policy (admin only)"""
        
        org = request.user.organisation
        policy, _ = RetentionPolicy.objects.get_or_create(organisation=org)
        
        data = request.data
        
        if 'auto_cleanup_enabled' in data:
            policy.auto_cleanup_enabled = data['auto_cleanup_enabled']
        
        if 'retention_days' in data:
            valid_days = [d[0] for d in RetentionPolicy.RETENTION_CHOICES]
            if data['retention_days'] in valid_days:
                policy.retention_days = data['retention_days']
        
        if 'cleanup_frequency' in data:
            valid_freq = [f[0] for f in RetentionPolicy.FREQUENCY_CHOICES]
            if data['cleanup_frequency'] in valid_freq:
                policy.cleanup_frequency = data['cleanup_frequency']
        
        if 'raw_metrics_retention_days' in data:
            valid = [d[0] for d in RetentionPolicy.RAW_METRICS_RETENTION_CHOICES]
            if data['raw_metrics_retention_days'] in valid:
                policy.raw_metrics_retention_days = data['raw_metrics_retention_days']

        if 'audit_log_retention_days' in data:
            valid_audit = [d[0] for d in RetentionPolicy.AUDIT_RETENTION_CHOICES]
            if data['audit_log_retention_days'] in valid_audit:
                policy.audit_log_retention_days = data['audit_log_retention_days']

        if 'batch_generation_interval' in data:
            valid_intervals = [i[0] for i in RetentionPolicy.BATCH_INTERVAL_CHOICES]
            if data['batch_generation_interval'] in valid_intervals:
                policy.batch_generation_interval = data['batch_generation_interval']

        # Calculate next cleanup time
        if policy.auto_cleanup_enabled:
            policy.next_cleanup_at = self._calculate_next_cleanup(policy.cleanup_frequency)
        else:
            policy.next_cleanup_at = None
        
        policy.save()

        # Invalidate cached batch interval so tasks pick up the new value
        from .batch_config import invalidate_batch_interval_cache
        invalidate_batch_interval_cache(org.id)

        # Log the change
        from .audit import log_settings_change
        log_settings_change(request, 'retention_policy', 'updated', 'updated')

        return Response({'success': True, 'message': 'Retention policy updated'})
    
    def _calculate_next_cleanup(self, frequency):
        """Calculate next cleanup time based on frequency"""
        now = timezone.now()
        
        if frequency == 'daily':
            # Next midnight
            next_run = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        elif frequency == 'weekly':
            # Next Sunday midnight
            days_until_sunday = (6 - now.weekday()) % 7
            if days_until_sunday == 0:
                days_until_sunday = 7
            next_run = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=days_until_sunday)
        elif frequency == 'monthly':
            # First of next month
            if now.month == 12:
                next_run = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            else:
                next_run = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            next_run = None
        
        return next_run
