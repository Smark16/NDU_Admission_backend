from django.contrib.contenttypes.models import ContentType
from audit.models import AuditLog

def log_audit_event(user, action, obj=None, description="", request=None):
    """Utility function to log audit events"""
    try:
        ip_address = "127.0.0.1"
        user_agent = ""
        
        if request:
            ip_address = get_client_ip(request)
            user_agent = request.META.get('HTTP_USER_AGENT', '')
        
        content_type = None
        object_id = None
        
        if obj:
            content_type = ContentType.objects.get_for_model(obj)
            object_id = obj.pk
        
        AuditLog.objects.create(
            user=user,
            action=action,
            content_type=content_type,
            object_id=object_id,
            description=description,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    except Exception as e:
        # Log error but don't break the application
        print('Audit log error', e)

def get_client_ip(request):
    """Get client IP address from request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


















