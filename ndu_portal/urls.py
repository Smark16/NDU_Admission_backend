from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
# from django.shortcuts import redirect

from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

urlpatterns = [
    # auth
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api-auth/', include('rest_framework.urls')),

    path('admin/', admin.site.urls),
    path('api/accounts/', include('accounts.urls')),
    path('api/admissions/', include('admissions.urls')),
    path('api/payments/', include('payments.urls')),
    path('api/audit/', include('audit.urls')),
    path('api/program/', include('Programs.urls')),
    path('api/offer_letter/', include('OfferLetter.AdmissionLetter.urls')),
    path('api/admission_reports/', include('OfferLetter.AdmissionReports.urls'))
]

if settings.DEBUG:
    import debug_toolbar
    
    urlpatterns += [
        path('__debug__/', include(debug_toolbar.urls)),
    ] 

    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
