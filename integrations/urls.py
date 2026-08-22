from django.urls import path

from . import admin_views, moodle_attendance_views, moodle_launch_views, moodle_views

urlpatterns = [
    # Super Admin (JWT)
    path("moodle/config", admin_views.MoodleConfigView.as_view(), name="moodle_config"),
    path(
        "moodle/config/rotate-key",
        admin_views.MoodleRotateKeyView.as_view(),
        name="moodle_rotate_key",
    ),
    # Student portal (JWT) — signed LMS launch
    path(
        "moodle/launch",
        moodle_launch_views.StudentMoodleLaunchView.as_view(),
        name="moodle_student_launch",
    ),
    # Moodle service (X-API-Key)
    path(
        "moodle/auth/verify",
        moodle_views.MoodleAuthVerifyView.as_view(),
        name="moodle_auth_verify",
    ),
    path(
        "moodle/students/<str:reg_no>/profile",
        moodle_views.MoodleStudentProfileView.as_view(),
        name="moodle_student_profile",
    ),
    path(
        "moodle/students/<str:reg_no>/finance-status",
        moodle_views.MoodleFinanceStatusView.as_view(),
        name="moodle_finance_status",
    ),
    path(
        "moodle/students/<str:reg_no>/registered-courses",
        moodle_views.MoodleRegisteredCoursesView.as_view(),
        name="moodle_registered_courses",
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
        "moodle/shared-course-units",
        moodle_views.MoodleSharedCourseUnitsView.as_view(),
        name="moodle_shared_course_units",
    ),
    path(
        "moodle/course-units/<int:course_unit_id>/enrolled-students",
        moodle_views.MoodleEnrolledStudentsView.as_view(),
        name="moodle_enrolled_students",
    ),
    path(
        "moodle/course-units/<int:course_unit_id>/attendance/sessions",
        moodle_attendance_views.MoodleAttendanceSessionsView.as_view(),
        name="moodle_attendance_sessions",
    ),
    path(
        "moodle/attendance/sessions/<int:session_id>",
        moodle_attendance_views.MoodleAttendanceSessionDetailView.as_view(),
        name="moodle_attendance_session_detail",
    ),
    path(
        "moodle/attendance/sessions/<int:session_id>/records",
        moodle_attendance_views.MoodleAttendanceRecordsView.as_view(),
        name="moodle_attendance_records",
    ),
    path(
        "moodle/students/<str:reg_no>/attendance",
        moodle_attendance_views.MoodleStudentAttendanceView.as_view(),
        name="moodle_student_attendance",
    ),
]
