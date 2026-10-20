"""
Audit Logging Utility
Helper functions for logging user actions
"""

from .models import AuditLog


def get_client_ip(request):
    """The client's address as seen by the trusted proxy.

    Proxies append to X-Forwarded-For, so its first entries are whatever the
    client sent. Like the login throttle (REST_FRAMEWORK NUM_PROXIES, from
    TRUSTED_PROXY_COUNT), take the entry the outermost trusted proxy added.
    """
    from django.conf import settings
    num_proxies = settings.REST_FRAMEWORK.get('NUM_PROXIES') or 0
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for and num_proxies > 0:
        entries = [e.strip() for e in x_forwarded_for.split(',') if e.strip()]
        if entries:
            return entries[-min(num_proxies, len(entries))]
    return request.META.get('REMOTE_ADDR')


def get_user_agent(request):
    """Extract user agent from request"""
    return request.META.get('HTTP_USER_AGENT', '')[:500]  # Limit length


def log_action(request, action, details=None, user=None, organisation=None):
    """
    Log an action to the audit log.
    
    Args:
        request: Django request object (can be None for system actions)
        action: Action type from AuditLog.ACTION_TYPES
        details: Optional dict with additional details
        user: Override user (otherwise uses request.user)
        organisation: Override organisation (otherwise uses user.organisation)
    """
    if request:
        log_user = user or (request.user if request.user.is_authenticated else None)
        log_org = organisation or (log_user.organisation if log_user else None)
        ip = get_client_ip(request)
        user_agent = get_user_agent(request)
    else:
        log_user = user
        log_org = organisation or (user.organisation if user else None)
        ip = None
        user_agent = None
    
    if not log_org:
        # Can't log without an organisation
        return None
    
    return AuditLog.objects.create(
        organisation=log_org,
        user=log_user,
        action=action,
        details=details or {},
        ip_address=ip,
        user_agent=user_agent
    )


def log_login(request, user, success=True):
    """Log a login attempt"""
    action = 'LOGIN' if success else 'LOGIN_FAILED'
    details = {'email': user.email if user else request.POST.get('email', 'unknown')}
    
    if success and user:
        log_action(request, action, details, user=user)
    elif not success:
        # For failed logins, we might not have a user object
        # Try to find the organisation from the email
        from Users.models import User
        try:
            attempted_user = User.objects.get(email=request.POST.get('email', ''))
            log_action(request, action, details, user=None, organisation=attempted_user.organisation)
        except User.DoesNotExist:
            pass  # Can't log without organisation


def log_logout(request, user=None):
    """Log a logout"""
    log_action(request, 'LOGOUT', user=user)


def log_settings_change(request, setting_name, old_value, new_value):
    """Log a settings change"""
    log_action(request, 'SETTINGS_CHANGE', {
        'setting': setting_name,
        'old_value': str(old_value)[:200],
        'new_value': str(new_value)[:200]
    })


def log_service_action(request, action, service_name, service_id=None, details=None):
    """Log service create/update/delete"""
    log_details = {
        'service_name': service_name,
        'service_id': service_id,
        **(details or {})
    }
    log_action(request, action, log_details)


def log_batch_delete(request, batch_count, is_auto=False, retention_days=None, user=None, organisation=None):
    """Log batch deletion (manual or auto-cleanup)"""
    action = 'BATCH_CLEANUP' if is_auto else 'BATCH_DELETE'
    details = {
        'batch_count': batch_count,
        'type': 'auto' if is_auto else 'manual'
    }
    if retention_days:
        details['retention_days'] = retention_days
    log_action(request, action, details, user=user, organisation=organisation)


def log_team_action(request, action, affected_user_email, role=None):
    """Log team member invite/remove/role change"""
    details = {'affected_user': affected_user_email}
    if role:
        details['role'] = role
    log_action(request, action, details)
