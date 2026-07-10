from django.urls import include, path

urlpatterns = [
    path("staff/", include("hr.staff.urls")),
    path("hiring/", include("hr.hiring.urls")),
    path("leave/", include("hr.leave.urls")),
    path("appraisal/", include("hr.appraisal.urls")),
]
