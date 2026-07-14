
from django.urls import path

from .batch_views import (
    AutoCreateSemestersView,
    BatchBulkUploadView,
    BatchTemplateDownloadView,
    CreateBatchView,
    CreateSemesterView,
    CreateSubjectView,
    DeleteProgramBatchView,
    ListProgramBatchesView,
    UpdateProgramBatchView,
)
from .semester_update_view import UpdateSemesterView
from .views import *
from .curriculum_views import (
    BulkUploadCurriculumView,
    CurriculumLineDetailView,
    CurriculumVersionDetailView,
    CurriculumVersionListCreateView,
    CurriculumSuggestionsForSemesterView,
    CurriculumSummaryView,
    ListCreateCurriculumView,
)
from .curriculum_source_views import ProgramCurriculumForkView, ProgramCurriculumSourceView
from .enrollment_views import (
    AdminCreateEnrollmentView,
    AdminEnrollmentDetailView,
    AdminListEnrollmentsView,
    AdminStudentEnrollmentEligibilityView,
    MyAvailableSpecializationsView,
    MyEnrollmentView,
    MyExpectedCoursesView,
    MySelectSpecializationView,
)
from .enrollment_report_views import EnrollmentReportExcelView, EnrollmentReportListView
from .override_views import (
    EnrollmentOverrideListCreate,
    OverrideDetailView,
    StudentCurriculumView,
)

from .specialization_views import (
    ProgramSpecializationBulkImportTemplateView,
    ProgramSpecializationBulkUploadView,
    ProgramSpecializationDetailView,
    ProgramSpecializationListCreateView,
)

from .timetable_views import (
    LecturerMyTimetablePdfView,
    LecturerMyTimetableView,
    RoomTypeListCreateView,
    SemesterTeachingLoadPdfView,
    SemesterTimetableBulkPublishView,
    SemesterTimetablePdfView,
    SemesterTimetableView,
    StudentMyTimetablePdfView,
    StudentMyTimetableView,
    TimetableSessionDetailView,
    VenueBulkUploadView,
    VenueDetailView,
    VenueListCreateView,
    VenueSuggestCodeView,
)
from .attendance_views import (
    AdminAttendanceBatchesView,
    AdminAttendanceBlankPdfView,
    AdminAttendanceCoursesView,
    AdminAttendanceLockView,
    AdminAttendanceMissingView,
    AdminAttendanceReportView,
    AdminAttendanceRosterView,
    AdminAttendanceSaveView,
    AdminAttendanceSessionPdfView,
    AdminAttendanceSessionsView,
    LecturerAttendanceBlankPdfView,
    LecturerAttendanceCheckInQrView,
    LecturerAttendanceCloseCheckInView,
    LecturerAttendanceCoursesView,
    LecturerAttendanceLockView,
    LecturerAttendanceOpenCheckInView,
    LecturerAttendanceRosterView,
    LecturerAttendanceSaveView,
    LecturerAttendanceScheduleView,
    LecturerAttendanceSessionPdfView,
    StudentAttendanceCheckInView,
    StudentAttendanceOpenSessionsView,
    StudentAttendanceSummaryView,
)
from .course_enrollment_views import (
    AdminDeregisterStudentFromCourses,
    AdminRegisterStudentForCourses,
    AssignLecturersToCourseUnit,
    CheckLecturerStatus,
    DetainStudentsInSemester,
    EnrollStudentsInCourseUnit,
    GetAvailableCoursesForRegistration,
    GetAvailableStudentsForCourseUnit,
    GetCourseUnitLecturers,
    GetLecturerCourses,
    GetStudentEnrolledCourses,
    StudentAcademicTrackerView,
    ListCourseUnitEnrollments,
    ListStudentsInSemester,
    PromoteStudentsToNextSemester,
    RemoveLecturerFromCourseUnit,
    RemoveStudentFromCourseUnit,
)
from .course_material_views import (
    LecturerCourseMaterialDetailView,
    LecturerCourseMaterialDownloadView,
    LecturerCourseMaterialListCreateView,
    StudentCourseMaterialDownloadView,
    StudentCourseMaterialListView,
)

try:
    from .program_structure_view import ProgramStructureView
    _structure_view_available = True
except ImportError:
    ProgramStructureView = None
    _structure_view_available = False

urlpatterns = [
    path('list_programs', ListPrograms.as_view()),
    # NEW: programs that have at least one ProgramBatch (see ListProgramsWithBatches in views.py)
    path('list_programs_with_batches', ListProgramsWithBatches.as_view()),
    path('create_programs', CreatePrograms.as_view()),
    path('update_program/<int:pk>', UpdateProgram.as_view()),
    path('delete_program/<int:pk>', DeleteProgram.as_view()),
    path('bulk_upload', HandleBulkUpload.as_view()),
    path('change_status/<int:pk>', ChangeProgramStatus.as_view()),
    path("download_program_sheet", ExportProgramTemplateView.as_view()),
    path('program_statistics', ProgramStats.as_view()),

    path('export_program_data', handleProgramExport.as_view()),
    path("preview_programs", PreviewProgramsFromCSV.as_view()),

    # ----- batch bulk upload -----
    path('batches/template', BatchTemplateDownloadView.as_view(), name='batch_template_download'),
    path('batches/bulk_upload', BatchBulkUploadView.as_view(), name='batch_bulk_upload'),
    path('batches/auto_create_semesters', AutoCreateSemestersView.as_view(), name='auto_create_semesters'),

    # ----- NEW MODULE: program batch & semester management (see batch_views.py) -----
    path('program/<int:program_id>/batches', ListProgramBatchesView.as_view(), name='list_program_batches'),
    path('program/<int:program_id>/batch/create', CreateBatchView.as_view(), name='create_batch'),
    path('batch/<int:batch_id>/update', UpdateProgramBatchView.as_view(), name='update_batch'),
    path('batch/<int:batch_id>/delete', DeleteProgramBatchView.as_view(), name='delete_batch'),
    path('batch/<int:batch_id>/semester/create', CreateSemesterView.as_view(), name='create_semester'),
    path(
        'batch/<int:batch_id>/semester/<int:semester_id>/update',
        UpdateSemesterView.as_view(),
        name='update_semester',
    ),
    path('batch/<int:batch_id>/subject/create', CreateSubjectView.as_view(), name='create_subject'),

    # ----- MODULE: programme curriculum mapping (ProgramCurriculumLine) -----
    path(
        'program/<int:program_id>/curriculum_versions',
        CurriculumVersionListCreateView.as_view(),
        name='program_curriculum_versions',
    ),
    path(
        'program/<int:program_id>/curriculum_source',
        ProgramCurriculumSourceView.as_view(),
        name='program_curriculum_source',
    ),
    path(
        'program/<int:program_id>/curriculum_fork',
        ProgramCurriculumForkView.as_view(),
        name='program_curriculum_fork',
    ),
    path(
        'curriculum_version/<int:pk>',
        CurriculumVersionDetailView.as_view(),
        name='curriculum_version_detail',
    ),
    path(
        'program/<int:program_id>/curriculum/bulk_upload',
        BulkUploadCurriculumView.as_view(),
        name='curriculum_bulk_upload',
    ),
    path(
        'program/<int:program_id>/curriculum/summary',
        CurriculumSummaryView.as_view(),
        name='program_curriculum_summary',
    ),
    path(
        'program/<int:program_id>/curriculum',
        ListCreateCurriculumView.as_view(),
        name='program_curriculum',
    ),
    path(
        'curriculum/<int:pk>',
        CurriculumLineDetailView.as_view(),
        name='curriculum_line_detail',
    ),
    # ----- curriculum suggestions for a positioned semester -----
    path(
        'semester/<int:semester_id>/curriculum_suggestions',
        CurriculumSuggestionsForSemesterView.as_view(),
        name='semester_curriculum_suggestions',
    ),

    # ----- timetable (semester-scoped on ProgramBatch) -----
    path('room_types', RoomTypeListCreateView.as_view(), name='room_type_list_create'),
    path('venues/suggest_code', VenueSuggestCodeView.as_view(), name='venue_suggest_code'),
    path('venues/bulk_upload', VenueBulkUploadView.as_view(), name='venue_bulk_upload'),
    path('venues', VenueListCreateView.as_view(), name='venue_list_create'),
    path('venues/<int:pk>', VenueDetailView.as_view(), name='venue_detail'),
    path(
        'semester/<int:semester_id>/timetable',
        SemesterTimetableView.as_view(),
        name='semester_timetable',
    ),
    path(
        'semester/<int:semester_id>/timetable/pdf',
        SemesterTimetablePdfView.as_view(),
        name='semester_timetable_pdf',
    ),
    path(
        'semester/<int:semester_id>/timetable/teaching_load/pdf',
        SemesterTeachingLoadPdfView.as_view(),
        name='semester_teaching_load_pdf',
    ),
    path(
        'semester/<int:semester_id>/timetable/publish',
        SemesterTimetableBulkPublishView.as_view(),
        name='semester_timetable_publish',
    ),
    path(
        'timetable/sessions/<int:pk>',
        TimetableSessionDetailView.as_view(),
        name='timetable_session_detail',
    ),
    path('student/my_timetable/pdf', StudentMyTimetablePdfView.as_view(), name='student_my_timetable_pdf'),
    path('student/my_timetable', StudentMyTimetableView.as_view(), name='student_my_timetable'),
    path('lecturer/my_timetable/pdf', LecturerMyTimetablePdfView.as_view(), name='lecturer_my_timetable_pdf'),
    path('lecturer/my_timetable', LecturerMyTimetableView.as_view(), name='lecturer_my_timetable'),
    path('lecturer/attendance/courses', LecturerAttendanceCoursesView.as_view(), name='lecturer_attendance_courses'),
    path('lecturer/attendance/schedule', LecturerAttendanceScheduleView.as_view(), name='lecturer_attendance_schedule'),
    path('lecturer/attendance/roster', LecturerAttendanceRosterView.as_view(), name='lecturer_attendance_roster'),
    path('lecturer/attendance/sessions', LecturerAttendanceSaveView.as_view(), name='lecturer_attendance_save'),
    path('lecturer/attendance/check_in/open', LecturerAttendanceOpenCheckInView.as_view(), name='lecturer_attendance_open_check_in'),
    path('lecturer/attendance/check_in/qr', LecturerAttendanceCheckInQrView.as_view(), name='lecturer_attendance_check_in_qr'),
    path('lecturer/attendance/check_in/close', LecturerAttendanceCloseCheckInView.as_view(), name='lecturer_attendance_close_check_in'),
    path('lecturer/attendance/lock', LecturerAttendanceLockView.as_view(), name='lecturer_attendance_lock'),
    path('lecturer/attendance/sessions/<int:session_id>/pdf', LecturerAttendanceSessionPdfView.as_view(), name='lecturer_attendance_session_pdf'),
    path('lecturer/attendance/blank_pdf', LecturerAttendanceBlankPdfView.as_view(), name='lecturer_attendance_blank_pdf'),
    path('student/attendance/sessions', StudentAttendanceOpenSessionsView.as_view(), name='student_attendance_sessions'),
    path('student/attendance/summary', StudentAttendanceSummaryView.as_view(), name='student_attendance_summary'),
    path('student/attendance/check_in', StudentAttendanceCheckInView.as_view(), name='student_attendance_check_in'),
    path('admin/attendance/batches', AdminAttendanceBatchesView.as_view(), name='admin_attendance_batches'),
    path('admin/attendance/courses', AdminAttendanceCoursesView.as_view(), name='admin_attendance_courses'),
    path('admin/attendance/sessions', AdminAttendanceSessionsView.as_view(), name='admin_attendance_sessions'),
    path('admin/attendance/missing', AdminAttendanceMissingView.as_view(), name='admin_attendance_missing'),
    path('admin/attendance/report', AdminAttendanceReportView.as_view(), name='admin_attendance_report'),
    path('admin/attendance/roster', AdminAttendanceRosterView.as_view(), name='admin_attendance_roster'),
    path('admin/attendance/sessions/save', AdminAttendanceSaveView.as_view(), name='admin_attendance_save'),
    path('admin/attendance/lock', AdminAttendanceLockView.as_view(), name='admin_attendance_lock'),
    path('admin/attendance/sessions/<int:session_id>/pdf', AdminAttendanceSessionPdfView.as_view(), name='admin_attendance_session_pdf'),
    path('admin/attendance/blank_pdf', AdminAttendanceBlankPdfView.as_view(), name='admin_attendance_blank_pdf'),

    # ----- programme specialization track management -----
    path(
        'program/<int:program_id>/specializations/bulk_import_template',
        ProgramSpecializationBulkImportTemplateView.as_view(),
        name='program_specializations_bulk_import_template',
    ),
    path(
        'program/<int:program_id>/specializations/bulk_upload',
        ProgramSpecializationBulkUploadView.as_view(),
        name='program_specializations_bulk_upload',
    ),
    path(
        'program/<int:program_id>/specializations',
        ProgramSpecializationListCreateView.as_view(),
        name='program_specializations',
    ),
    path(
        'program/specialization/<int:pk>',
        ProgramSpecializationDetailView.as_view(),
        name='program_specialization_detail',
    ),

    # ----- academic enrollment (commitment fee → access) -----
    path(
        'admin/student/<int:student_id>/enrollment_eligibility',
        AdminStudentEnrollmentEligibilityView.as_view(),
        name='admin_student_enrollment_eligibility',
    ),
    path(
        'admin/student/<int:student_id>/enroll',
        AdminCreateEnrollmentView.as_view(),
        name='admin_create_enrollment',
    ),
    path(
        'admin/enrollments',
        AdminListEnrollmentsView.as_view(),
        name='admin_list_enrollments',
    ),
    path(
        'reports/enrollments',
        EnrollmentReportListView.as_view(),
        name='enrollment_report_list',
    ),
    path(
        'reports/enrollments/export',
        EnrollmentReportExcelView.as_view(),
        name='enrollment_report_export',
    ),
    path(
        'admin/enrollment/<int:pk>',
        AdminEnrollmentDetailView.as_view(),
        name='admin_enrollment_detail',
    ),
    # ----- student curriculum override management (staff) -----
    path(
        'admin/student/<int:student_id>/curriculum',
        StudentCurriculumView.as_view(),
        name='student_curriculum_with_overrides',
    ),
    path(
        'admin/enrollment/<int:enrollment_id>/overrides',
        EnrollmentOverrideListCreate.as_view(),
        name='enrollment_overrides',
    ),
    path(
        'admin/override/<int:pk>',
        OverrideDetailView.as_view(),
        name='override_detail',
    ),

    path(
        'my_enrollment',
        MyEnrollmentView.as_view(),
        name='my_enrollment',
    ),
    path(
        'my_enrollment/specializations',
        MyAvailableSpecializationsView.as_view(),
        name='my_available_specializations',
    ),
    path(
        'my_enrollment/select_specialization',
        MySelectSpecializationView.as_view(),
        name='my_select_specialization',
    ),
    path(
        'my_enrollment/expected_courses',
        MyExpectedCoursesView.as_view(),
        name='my_expected_courses',
    ),
]

if _structure_view_available:
    urlpatterns.append(
        path(
            'program/<int:program_id>/structure',
            ProgramStructureView.as_view(),
            name='program_structure',
        )
    )

urlpatterns.extend(
    [
        path(
            'course_unit/<int:course_unit_id>/enrollments',
            ListCourseUnitEnrollments.as_view(),
            name='list_course_unit_enrollments',
        ),
        path(
            'course_unit/<int:course_unit_id>/available_students',
            GetAvailableStudentsForCourseUnit.as_view(),
            name='available_students_for_course_unit',
        ),
        path(
            'course_unit/<int:course_unit_id>/enroll_students',
            EnrollStudentsInCourseUnit.as_view(),
            name='enroll_students_in_course_unit',
        ),
        path(
            'enrollment/<int:enrollment_id>/remove',
            RemoveStudentFromCourseUnit.as_view(),
            name='remove_student_from_course_unit',
        ),
        path(
            'student/my_courses',
            GetStudentEnrolledCourses.as_view(),
            name='get_student_enrolled_courses',
        ),
        path(
            'student/academic_tracker',
            StudentAcademicTrackerView.as_view(),
            name='student_academic_tracker',
        ),
        path(
            'student/available_courses',
            GetAvailableCoursesForRegistration.as_view(),
            name='get_available_courses_for_registration',
        ),
        path(
            'admin/student/<int:student_id>/register_courses',
            AdminRegisterStudentForCourses.as_view(),
            name='admin_register_student_for_courses',
        ),
        path(
            'admin/student/<int:student_id>/deregister_courses',
            AdminDeregisterStudentFromCourses.as_view(),
            name='admin_deregister_student_from_courses',
        ),
        path(
            'course_unit/<int:course_unit_id>/lecturers',
            GetCourseUnitLecturers.as_view(),
            name='get_course_unit_lecturers',
        ),
        path(
            'course_unit/<int:course_unit_id>/assign_lecturers',
            AssignLecturersToCourseUnit.as_view(),
            name='assign_lecturers_to_course_unit',
        ),
        path(
            'course_unit/<int:course_unit_id>/remove_lecturer',
            RemoveLecturerFromCourseUnit.as_view(),
            name='remove_lecturer_from_course_unit',
        ),
        path(
            'lecturer/check_status',
            CheckLecturerStatus.as_view(),
            name='check_lecturer_status',
        ),
        path(
            'lecturer/my_courses',
            GetLecturerCourses.as_view(),
            name='get_lecturer_courses',
        ),
        path(
            'lecturer/course_unit/<int:course_unit_id>/materials/',
            LecturerCourseMaterialListCreateView.as_view(),
            name='lecturer_course_materials',
        ),
        path(
            'lecturer/materials/<int:material_id>/',
            LecturerCourseMaterialDetailView.as_view(),
            name='lecturer_course_material_detail',
        ),
        path(
            'lecturer/materials/<int:material_id>/download/',
            LecturerCourseMaterialDownloadView.as_view(),
            name='lecturer_course_material_download',
        ),
        path(
            'student/course_unit/<int:course_unit_id>/materials/',
            StudentCourseMaterialListView.as_view(),
            name='student_course_materials',
        ),
        path(
            'student/materials/<int:material_id>/download/',
            StudentCourseMaterialDownloadView.as_view(),
            name='student_course_material_download',
        ),
        path(
            'semester/<int:semester_id>/students',
            ListStudentsInSemester.as_view(),
            name='list_students_in_semester',
        ),
        path(
            'semester/<int:semester_id>/promote_students',
            PromoteStudentsToNextSemester.as_view(),
            name='promote_students_to_next_semester',
        ),
        path(
            'semester/<int:semester_id>/detain_students',
            DetainStudentsInSemester.as_view(),
            name='detain_students_in_semester',
        ),
    ]
)
