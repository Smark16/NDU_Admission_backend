from django.utils.deprecation import MiddlewareMixin
# from django.contrib.contenttypes.models import ContentType
# from audit.models import AuditLog
# from django.utils import timezone
# from rest_framework_simplejwt.authentication import JWTAuthentication
# import json

from django.utils.deprecation import MiddlewareMixin
from django.contrib.auth.middleware import AuthenticationMiddleware as BaseAuthenticationMiddleware


class PatchedAuthenticationMiddleware(BaseAuthenticationMiddleware, MiddlewareMixin):
    """
    Same as Django's AuthenticationMiddleware,
    but it ONLY sets request.user if it hasn't been set already (by JWT).
    This keeps Django admin happy and doesn't overwrite JWT user.
    """
    def process_request(self, request):
        # Only run the original logic if request.user is not already set
        if not hasattr(request, "user") or request.user.is_anonymous:
            super().process_request(request)
    
# class AuditMiddleware(MiddlewareMixin):
#     def process_request(self, request):
#         request._audit_start_time = timezone.now()
#         return None

#     def process_response(self, request, response):
#         if hasattr(request, '_audit_start_time') and request.user.is_authenticated:
#             # Log user activity
#             if request.method in ['POST', 'PUT', 'PATCH', 'DELETE']:
#                 self.log_user_activity(request, response)
        
#         return response

#     def get_client_ip(self, request):
#         """Get client IP address"""
#         x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
#         if x_forwarded_for:
#             ip = x_forwarded_for.split(',')[0]
#         else:
#             ip = request.META.get('REMOTE_ADDR')
#         return ip

# def log_audit_event(user, action, obj=None, description="", request=None):
#     """Utility function to log audit events"""
#     try:
#         ip_address = "127.0.0.1"
#         user_agent = ""
        
#         if request:
#             ip_address = get_client_ip(request)
#             user_agent = request.META.get('HTTP_USER_AGENT', '')
        
#         content_type = None
#         object_id = None
        
#         if obj:
#             content_type = ContentType.objects.get_for_model(obj)
#             object_id = obj.pk
        
#         AuditLog.objects.create(
#             user=user,
#             action=action,
#             content_type=content_type,
#             object_id=object_id,
#             description=description,
#             ip_address=ip_address,
#             user_agent=user_agent,
#         )
#     except Exception as e:
#         # Log error but don't break the application
#         pass

# def get_client_ip(request):
#     """Get client IP address from request"""
#     x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
#     if x_forwarded_for:
#         ip = x_forwarded_for.split(',')[0]
#     else:
#         ip = request.META.get('REMOTE_ADDR')
#     return ip


















