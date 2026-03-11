from django.utils.deprecation import MiddlewareMixin
from django.utils.deprecation import MiddlewareMixin
from django.contrib.auth.middleware import AuthenticationMiddleware as BaseAuthenticationMiddleware


class PatchedAuthenticationMiddleware(BaseAuthenticationMiddleware, MiddlewareMixin):
    def process_request(self, request):
        # Only run the original logic if request.user is not already set
        if not hasattr(request, "user") or request.user.is_anonymous:
            super().process_request(request)

















