from django.urls import path

from .exam_card_views import ExamCardVerifyView, StudentExamCardView
from .phase3_views import (
    BulkPublishView,
    ImportCourseMarksView,
    ResultsReportView,
    StudentTranscriptView,
    VerifyCourseMarksView,
)
from .phase4_views import (
    CreateResultChangeRequestView,
    ResultChangeRequestDetailView,
    ResultChangeRequestListView,
    UnlockPublishedResultView,
)
from .phase2_views import (
    CourseExamSessionsView,
    CourseRetakeRegistrationsView,
    CourseSittingListView,
    ExamRetakeDetailView,
    ExamSessionDetailView,
    ExamSessionSittingListView,
    StudentMyExamScheduleView,
)
from .policy_views import (
    ActivePolicyView,
    AssessmentPolicyDetailView,
    AssessmentPolicyListCreateView,
)
from .award_classification_views import (
    ActiveAwardSchemeView,
    AwardClassPreviewView,
    AwardSchemeActivateView,
    AwardSchemeDetailView,
    AwardSchemeListCreateView,
)
from .grade_scale_views import (
    ActiveGradeScaleView,
    GradeScaleActivateView,
    GradeScaleDetailView,
    GradeScaleListCreateView,
)
from .views import (
    LecturerCourseMarksView,
    PublishCourseMarksView,
    StaffExaminationCoursesView,
    StudentMyResultsView,
)

urlpatterns = [
    path("policy/", ActivePolicyView.as_view(), name="examinations-policy"),
    path("policies/", AssessmentPolicyListCreateView.as_view(), name="examinations-policies"),
    path(
        "policies/<int:policy_id>/",
        AssessmentPolicyDetailView.as_view(),
        name="examinations-policy-detail",
    ),
    path("grade-scale/", ActiveGradeScaleView.as_view(), name="examinations-grade-scale"),
    path("grade-scales/", GradeScaleListCreateView.as_view(), name="examinations-grade-scales"),
    path(
        "grade-scales/<int:scale_id>/",
        GradeScaleDetailView.as_view(),
        name="examinations-grade-scale-detail",
    ),
    path(
        "grade-scales/<int:scale_id>/activate/",
        GradeScaleActivateView.as_view(),
        name="examinations-grade-scale-activate",
    ),
    path("award-scheme/", ActiveAwardSchemeView.as_view(), name="examinations-award-scheme"),
    path("award-schemes/", AwardSchemeListCreateView.as_view(), name="examinations-award-schemes"),
    path(
        "award-schemes/<int:scheme_id>/",
        AwardSchemeDetailView.as_view(),
        name="examinations-award-scheme-detail",
    ),
    path(
        "award-schemes/<int:scheme_id>/activate/",
        AwardSchemeActivateView.as_view(),
        name="examinations-award-scheme-activate",
    ),
    path(
        "award-class/preview/",
        AwardClassPreviewView.as_view(),
        name="examinations-award-class-preview",
    ),
    path("staff/courses/", StaffExaminationCoursesView.as_view(), name="staff-examination-courses"),
    path(
        "lecturer/courses/<int:course_unit_id>/marks/",
        LecturerCourseMarksView.as_view(),
        name="lecturer-course-marks",
    ),
    path(
        "lecturer/courses/<int:course_unit_id>/verify/",
        VerifyCourseMarksView.as_view(),
        name="verify-course-marks",
    ),
    path(
        "lecturer/courses/<int:course_unit_id>/publish/",
        PublishCourseMarksView.as_view(),
        name="publish-course-marks",
    ),
    path(
        "courses/<int:course_unit_id>/import-marks/",
        ImportCourseMarksView.as_view(),
        name="import-course-marks",
    ),
    path("bulk-publish/", BulkPublishView.as_view(), name="bulk-publish"),
    path("reports/summary/", ResultsReportView.as_view(), name="results-report"),
    path("student/transcript/", StudentTranscriptView.as_view(), name="student-transcript"),
    path(
        "students/<int:student_id>/transcript/",
        StudentTranscriptView.as_view(),
        name="staff-student-transcript",
    ),
    path("change-requests/", ResultChangeRequestListView.as_view(), name="change-requests-list"),
    path(
        "results/<int:result_id>/change-request/",
        CreateResultChangeRequestView.as_view(),
        name="create-change-request",
    ),
    path(
        "change-requests/<int:request_id>/",
        ResultChangeRequestDetailView.as_view(),
        name="change-request-detail",
    ),
    path(
        "results/<int:result_id>/unlock/",
        UnlockPublishedResultView.as_view(),
        name="unlock-published-result",
    ),
    path("student/my-results/", StudentMyResultsView.as_view(), name="student-my-results"),
    path("student/exam-card/", StudentExamCardView.as_view(), name="student-exam-card"),
    path(
        "exam-card/verify/<uuid:verification_code>/",
        ExamCardVerifyView.as_view(),
        name="exam-card-verify",
    ),
    path("student/my-exam-schedule/", StudentMyExamScheduleView.as_view(), name="student-my-exam-schedule"),
    path(
        "courses/<int:course_unit_id>/exam-sessions/",
        CourseExamSessionsView.as_view(),
        name="course-exam-sessions",
    ),
    path(
        "courses/<int:course_unit_id>/sitting-list/",
        CourseSittingListView.as_view(),
        name="course-sitting-list",
    ),
    path(
        "courses/<int:course_unit_id>/retakes/",
        CourseRetakeRegistrationsView.as_view(),
        name="course-retake-registrations",
    ),
    path(
        "exam-sessions/<int:session_id>/",
        ExamSessionDetailView.as_view(),
        name="exam-session-detail",
    ),
    path(
        "exam-sessions/<int:session_id>/sitting-list/",
        ExamSessionSittingListView.as_view(),
        name="exam-session-sitting-list",
    ),
    path(
        "retakes/<int:registration_id>/",
        ExamRetakeDetailView.as_view(),
        name="exam-retake-detail",
    ),
]
