"""
Curated Category → Service → View/Add/Edit/Delete mapping for the AIMS-style
role matrix UI.

Each column value is a Django permission string ``app_label.codename``, or None
when that action does not apply (checkbox disabled in the UI).
"""

from __future__ import annotations

from typing import TypedDict


class ServiceColumns(TypedDict):
    view: str | None
    add: str | None
    edit: str | None
    delete: str | None


class ServiceDef(TypedDict):
    key: str
    label: str
    columns: ServiceColumns


class CategoryDef(TypedDict):
    name: str
    services: list[ServiceDef]


def _crud(app: str, model: str) -> ServiceColumns:
    """Standard Django model perms for a model name (lowercase)."""
    return {
        "view": f"{app}.view_{model}",
        "add": f"{app}.add_{model}",
        "edit": f"{app}.change_{model}",
        "delete": f"{app}.delete_{model}",
    }


def _cols(
    *,
    view: str | None = None,
    add: str | None = None,
    edit: str | None = None,
    delete: str | None = None,
) -> ServiceColumns:
    return {"view": view, "add": add, "edit": edit, "delete": delete}


def _toggle(perm: str) -> ServiceColumns:
    """Single-permission service — View column only (never duplicate on Edit)."""
    return _cols(view=perm)


def _svc(key: str, label: str, columns: ServiceColumns) -> ServiceDef:
    return {"key": key, "label": label, "columns": columns}


# ---------------------------------------------------------------------------
# Catalog — fine-grained, aligned with Steward sidebar menus
# ---------------------------------------------------------------------------

ROLE_SERVICE_CATALOG: list[CategoryDef] = [
    {
        "name": "Admissions",
        "services": [
            _svc("admissions_access", "Admissions module access", _toggle("accounts.access_admissions")),
            _svc("applications", "Applications", _crud("admissions", "application")),
            _svc("application_documents", "Application documents", _crud("admissions", "applicationdocument")),
            _svc("direct_applications", "Direct admission", _toggle("accounts.manage_direct_applications")),
            _svc("intakes", "Admission intakes", _crud("admissions", "batch")),
            _svc("manage_batches", "Manage intakes / batches (admin)", _toggle("accounts.manage_batches")),
            _svc("academic_levels", "Academic levels", _crud("admissions", "academiclevel")),
            _svc("academic_years", "Academic years", _crud("admissions", "academicyear")),
            _svc("olevel_subjects", "O-level subjects", _crud("admissions", "olevelsubject")),
            _svc("alevel_subjects", "A-level subjects", _crud("admissions", "alevelsubject")),
            _svc("email_templates", "Email templates", _crud("admissions", "emailtemplate")),
            _svc("communication_templates", "Communication templates", _toggle("accounts.manage_communication_templates")),
            _svc("offer_letter_templates", "Offer letter templates", _crud("AdmissionLetter", "offerlettertemplate")),
            _svc("admission_reports", "Admission reports", _toggle("AdmissionReports.view_admissionreports")),
            _svc("draft_applications", "Draft applications", _crud("Drafts", "draftapplication")),
        ],
    },
    {
        "name": "Students",
        "services": [
            _svc("admitted_students", "Student directory / Bonafide", _crud("admissions", "admittedstudent")),
            _svc("programme_enrollment", "Programme enrollment (SPE)", _crud("Programs", "studentprogrammeenrollment")),
            _svc("course_enrollment", "Course unit enrolment", _crud("Programs", "studentcourseunitenrollment")),
            _svc("academic_enrollment_admin", "Academic enrollment admin", _toggle("accounts.manage_academic_enrollment")),
            _svc("semester_progression", "Semester progression", _crud("Programs", "studentsemesterprogression")),
            _svc("curriculum_overrides", "Student curriculum overrides", _crud("Programs", "studentcurriculumoverride")),
            _svc("change_requests", "Admission change requests", _crud("admissions", "admissionchangerequest")),
            _svc("manage_change_requests", "Manage change requests", _toggle("admissions.manage_admission_change_requests")),
            _svc("exemptions", "Course exemptions (lines)", _crud("admissions", "exemptionrequestline")),
            _svc("exemption_documents", "Exemption supporting documents", _crud("admissions", "exemptionsupportingdocument")),
            _svc("id_cards", "Student ID cards", _crud("admissions", "studentidcard")),
            _svc("id_card_pdf_templates", "ID card PDF templates", _crud("admissions", "idcardpdftemplate")),
            _svc("manage_id_cards", "Manage ID cards", _toggle("admissions.manage_id_cards")),
            _svc("portal_notifications", "Student portal notifications", _crud("admissions", "portalnotification")),
        ],
    },
    {
        "name": "Academic setup",
        "services": [
            _svc("academics_access", "Academics module access", _cols(view="accounts.access_academics")),
            _svc("programs", "Programmes", _crud("Programs", "program")),
            _svc("program_specializations", "Programme specializations", _crud("Programs", "programspecialization")),
            _svc("curriculum_versions", "Curriculum versions", _crud("Programs", "programcurriculumversion")),
            _svc("curriculum_lines", "Curriculum lines", _crud("Programs", "programcurriculumline")),
            _svc("manage_curriculum", "Manage curriculum", _toggle("accounts.manage_curriculum")),
            _svc("course_catalog", "Course catalog", _crud("Programs", "coursecatalogunit")),
            _svc("manage_course_catalog", "Manage course catalog", _toggle("accounts.manage_course_catalog")),
            _svc("faculties", "Faculties", _crud("admissions", "faculty")),
            _svc("campuses", "Campuses", _crud("accounts", "campus")),
            _svc("venues", "Classrooms / venues", _crud("Programs", "venue")),
            _svc("room_types", "Room types", _crud("Programs", "roomtype")),
        ],
    },
    {
        "name": "Batches & timetable",
        "services": [
            _svc("program_batches", "Programme batches / cohorts", _crud("Programs", "programbatch")),
            _svc("semesters", "Semesters", _crud("Programs", "semester")),
            _svc("course_units", "Course units (batch)", _crud("Programs", "courseunit")),
            _svc("teaching_sections", "Teaching sections", _crud("Programs", "teachingsection")),
            _svc("program_scheduling", "Timetable scheduling", _toggle("accounts.manage_program_scheduling")),
            _svc("timetable_sessions", "Timetable sessions", _crud("Programs", "timetablesession")),
            _svc("section_lecturers", "Section lecturers", _crud("Programs", "courseunitsectionlecturer")),
            _svc("course_materials", "Course materials", _crud("Programs", "coursematerial")),
            _svc("lecture_attendance", "Lecture attendance sessions", _crud("Programs", "lectureattendancesession")),
            _svc("lecture_attendance_records", "Lecture attendance records", _crud("Programs", "lectureattendancerecord")),
            _svc("manage_faculty_attendance", "Manage faculty lecture attendance", _toggle("Programs.manage_faculty_lecture_attendance")),
        ],
    },
    {
        "name": "Examinations",
        "services": [
            _svc("exams_access", "Examinations module access", _cols(view="accounts.access_examinations")),
            _svc("exam_schedule", "Exam schedule / sessions", _crud("examinations", "examsession")),
            _svc("manage_exam_schedule", "Manage exam schedule", _toggle("examinations.manage_exam_schedule")),
            _svc("exam_results", "Course unit results / marks", _crud("examinations", "courseunitresult")),
            _svc("view_all_results", "View all results", _cols(view="examinations.view_all_results")),
            _svc("marks_windows", "Marks entry windows", _crud("examinations", "marksentrywindow")),
            _svc("manage_marks_windows", "Manage marks windows", _toggle("examinations.manage_marks_windows")),
            _svc("retakes", "Exam retakes", _crud("examinations", "examretakeregistration")),
            _svc("manage_retakes", "Manage retakes", _toggle("examinations.manage_retakes")),
            _svc("grade_changes", "Grade / result change requests", _crud("examinations", "resultchangerequest")),
            _svc("assessment_policies", "Assessment policies", _crud("examinations", "assessmentpolicy")),
            _svc("grade_scales", "Grade scales", _crud("examinations", "gradescale")),
            _svc("grade_bands", "Grade bands", _crud("examinations", "gradeband")),
            _svc("award_schemes", "Award classification schemes", _crud("examinations", "awardclassificationscheme")),
            _svc("award_bands", "Award class bands", _crud("examinations", "awardclassband")),
            _svc("exam_cards", "Exam card tokens", _crud("examinations", "examcardtoken")),
        ],
    },
    {
        "name": "Graduation",
        "services": [
            _svc("graduation_access", "Graduation module access", _cols(view="accounts.access_graduation")),
            _svc("grad_sessions", "Graduation sessions", _crud("graduation", "graduationsession")),
            _svc("grad_ceremonies", "Ceremonies", _crud("graduation", "graduationceremony")),
            _svc("manage_ceremonies", "Manage ceremonies", _toggle("graduation.manage_ceremonies")),
            _svc("grad_assignments", "Graduation assignments", _crud("graduation", "graduationassignment")),
            _svc("assign_graduates", "Assign students to ceremony", _toggle("graduation.assign_students")),
            _svc("qualified_lists", "Qualified lists", _cols(view="graduation.view_qualified_lists")),
            _svc("graduation_lists", "Graduation lists", _cols(view="graduation.view_graduation_lists")),
        ],
    },
    {
        "name": "Finance",
        "services": [
            _svc("finance_access", "Finance module access", _cols(view="accounts.access_finance")),
            _svc("reports_access", "Finance / reports access", _cols(view="accounts.access_reports")),
            _svc("tuition_ledger", "Tuition ledger", _cols(view="payments.view_tuitionledger")),
            _svc("tuition_payments", "Tuition payments", _crud("payments", "studenttuitionpayment")),
            _svc("application_payments", "Application payments", _crud("payments", "applicationpayment")),
            _svc("application_fees", "Application fee setup", _crud("payments", "applicationfee")),
            _svc("fee_plans", "Fee plans", _crud("payments", "feeplan")),
            _svc("fee_plan_rules", "Fee plan rules", _crud("payments", "feeplanrule")),
            _svc("fee_heads", "Fee heads", _crud("payments", "feehead")),
            _svc("fee_config", "Configure fee plans", _toggle("accounts.configure_fee_plans")),
            _svc("registration_settings", "Registration settings", _cols(
                view="payments.view_registrationsettings",
                edit="payments.change_registrationsettings",
            )),
            _svc("accounts_clearance", "Accounts registration clearance", _toggle("admissions.clear_accounts_registration")),
            _svc("temp_access_pass", "Temporary access passes", _toggle("admissions.manage_temporary_access_pass")),
            _svc("temp_access_pass_records", "Temporary access pass records", _crud("admissions", "temporaryaccesspass")),
            _svc("payment_reconciliation", "Payment reconciliation", _toggle("accounts.manage_payment_reconciliation")),
            _svc("manual_bank_payment", "Post manual bank payment", _toggle("accounts.post_manual_bank_payment")),
            _svc("manual_bank_change", "Manual bank payment change requests", _crud(
                "payments", "manualbankpaymentchangerequest"
            )),
            _svc("fee_exemptions", "Student fee exemptions", _crud("payments", "studentfeeexemption")),
            _svc("scholarships_view", "View scholarships", _cols(view="accounts.view_scholarships")),
            _svc("scholarships_manage", "Manage scholarships", _toggle("accounts.manage_scholarships")),
            _svc("scholarship_programmes", "Scholarship programmes", _toggle("accounts.manage_scholarship_programmes")),
            _svc("scholarship_students", "Scholarship students / awards", _toggle("accounts.manage_scholarship_students")),
            _svc("scholarship_awards", "Scholarship award records", _crud("payments", "scholarshipaward")),
        ],
    },
    {
        "name": "Hostel",
        "services": [
            _svc("hostel_access", "Hostel module access", _toggle("accounts.access_hostel")),
            _svc("hostels", "Hostels", _crud("hostel", "hostel")),
            _svc("buildings", "Buildings", _crud("hostel", "building")),
            _svc("floors", "Floors", _crud("hostel", "floor")),
            _svc("rooms", "Rooms", _crud("hostel", "room")),
            _svc("beds", "Beds", _crud("hostel", "bed")),
            _svc("hostel_inventory", "Manage inventory", _toggle("hostel.manage_hostel_inventory")),
            _svc("hostel_assign", "Assign hostel / room", _toggle("hostel.assign_hostel")),
            _svc("hostel_allocations", "Allocations / occupancy", _crud("hostel", "hostelallocation")),
            _svc("end_allocation", "End hostel allocation", _toggle("hostel.end_hostel_allocation")),
            _svc("hostel_reports", "Hostel reports", _toggle("hostel.view_hostel_reports")),
        ],
    },
    {
        "name": "Human resources",
        "services": [
            _svc("staff_profiles", "Staff directory / profiles", _crud("staff", "staffprofile")),
            _svc("staff_manage", "Manage staff", _toggle("staff.manage_staff")),
            _svc("staff_contracts", "Staff contracts", _crud("staff", "staffcontract")),
            _svc("staff_bulk", "Import staff", _crud("staff", "bulkuploadstaff")),
            _svc("departments", "Departments", _crud("staff", "department")),
            _svc("department_teams", "Department teams", _crud("staff", "departmentteams")),
            _svc("staff_types", "Staff types", _crud("staff", "stafftype")),
            _svc("position_levels", "Position levels", _crud("staff", "positonlevel")),
            _svc("pay_scales", "Pay scales", _crud("staff", "payscale")),
            _svc("supervision", "Supervision assignments", _crud("staff", "supervisionassignment")),
            _svc("job_openings", "Job openings", _crud("hiring", "jobopening")),
            _svc("job_applications", "Hiring applications", _crud("hiring", "jobapplication")),
            _svc("interviews", "Interviews", _crud("hiring", "interview")),
            _svc("leave_requests", "Leave requests", _crud("leave", "leaverequest")),
            _svc("leave_types", "Leave types", _crud("leave", "leavetype")),
            _svc("leave_policies", "Leave policies", _crud("leave", "leavepolicy")),
            _svc("leave_balances", "Leave balances", _crud("leave", "leavebalance")),
            _svc("public_holidays", "Public holidays", _crud("leave", "publicholiday")),
            _svc("appraisals", "Appraisals", _crud("appraisal", "appraisal")),
            _svc("appraisal_cycles", "Appraisal cycles", _crud("appraisal", "appraisalcycle")),
            _svc("view_team_appraisals", "View team appraisals", _cols(view="staff.view_team_appraisals")),
            _svc("view_all_appraisals", "View all appraisals", _cols(view="staff.view_all_appraisals")),
        ],
    },
    {
        "name": "Settings & system",
        "services": [
            _svc("system_settings", "System settings", _crud("accounts", "systemsettings")),
            _svc("system_settings_access", "Access system settings", _toggle("accounts.access_system_settings")),
            _svc("audit_access", "Audit module access", _cols(view="accounts.access_audit")),
            _svc("audit_log", "Audit log", _cols(view="audit.view_auditlog")),
            _svc("lecturer_portal", "Lecturer portal access", _cols(view="accounts.access_lecturer_portal")),
        ],
    },
    {
        "name": "Users & roles",
        "services": [
            _svc("user_management_access", "User management access", _cols(view="accounts.access_user_management")),
            _svc("users", "Users", _crud("accounts", "user")),
            _svc("assign_roles", "Assign roles to users", _toggle("accounts.assign_roles")),
            _svc("groups", "Roles (Django groups)", _crud("auth", "group")),
            _svc("role_capabilities", "Role capability matrix", _toggle("accounts.manage_role_capabilities")),
            _svc("profiles", "User profiles", _crud("accounts", "profile")),
        ],
    },
]


COLUMN_KEYS = ("view", "add", "edit", "delete")


def iter_catalog_services():
    for category in ROLE_SERVICE_CATALOG:
        for service in category["services"]:
            yield category["name"], service


def catalog_permission_labels() -> set[str]:
    labels: set[str] = set()
    for _, service in iter_catalog_services():
        for key in COLUMN_KEYS:
            label = service["columns"].get(key)
            if label:
                labels.add(label)
    return labels


def service_by_key(key: str) -> ServiceDef | None:
    for _, service in iter_catalog_services():
        if service["key"] == key:
            return service
    return None
