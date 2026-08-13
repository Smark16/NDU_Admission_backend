from django.urls import path

from . import admin_views, moodle_views

urlpatterns = [
    # Super Admin (JWT)
    path("moodle/config", admin_views.MoodleConfigView.as_view(), name="moodle_config"),
    path(
        "moodle/config/rotate-key",
        admin_views.MoodleRotateKeyView.as_view(),
        name="moodle_rotate_key",
    ),
    # Moodle service (X-API-Key)
    path(
        "moodle/auth/verify",
        moodle_views.MoodleAuthVerifyView.as_view(),
        name="moodle_auth_verify",
    ),
    path(
        "moodle/students/<str:reg_no>/finance-status",
        moodle_views.MoodleFinanceStatusView.as_view(),
        name="moodle_finance_status",
    ),
    path(
        "moodle/semesters/current",
        moodle_views.MoodleCurrentSemestersView.as_view(),
        name="moodle_semesters_current",
    ),
    path(
        "moodle/course-units",
        moodle_views.MoodleCourseUnitsView.as_view(),
        name="moodle_course_units",
    ),
    path(
        "moodle/course-units/<int:course_unit_id>/enrolled-students",
        moodle_views.MoodleEnrolledStudentsView.as_view(),
        name="moodle_enrolled_students",
    ),
]
