from django.urls import path

from .views import (
    CeremonyDetailView,
    CeremonyListCreateView,
    GraduationPrintListView,
    QualifiedStudentsView,
    SessionAssignmentsView,
    SessionDetailView,
    SessionListCreateView,
)

urlpatterns = [
    path("qualified/", QualifiedStudentsView.as_view(), name="graduation-qualified"),
    path("ceremonies/", CeremonyListCreateView.as_view(), name="graduation-ceremonies"),
    path("ceremonies/<int:ceremony_id>/", CeremonyDetailView.as_view(), name="graduation-ceremony-detail"),
    path(
        "ceremonies/<int:ceremony_id>/sessions/",
        SessionListCreateView.as_view(),
        name="graduation-session-create",
    ),
    path("sessions/<int:session_id>/", SessionDetailView.as_view(), name="graduation-session-detail"),
    path(
        "sessions/<int:session_id>/assignments/",
        SessionAssignmentsView.as_view(),
        name="graduation-session-assignments",
    ),
    path(
        "sessions/<int:session_id>/print-list/",
        GraduationPrintListView.as_view(),
        name="graduation-print-list",
    ),
]
