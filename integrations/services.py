"""Domain helpers for Moodle integration endpoints."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from django.contrib.auth import authenticate, get_user_model
from django.db.models import Q

from admissions.models import AdmittedStudent
from admissions.student_accounts import student_portal_username
from payments.student_portal_finance import student_finance_totals

from .models import MoodleApiAccessLog, MoodleIntegrationConfig
from .moodle_sso import split_full_name

User = get_user_model()


def log_moodle_access(
    *,
    endpoint: str,
    http_status: int,
    key_prefix: str = "",
    detail: str = "",
) -> None:
    try:
        MoodleApiAccessLog.objects.create(
            endpoint=endpoint[:120],
            key_prefix=(key_prefix or "")[:16],
            http_status=http_status,
            detail=(detail or "")[:255],
        )
    except Exception:
        pass


def resolve_student_by_lookup(lookup: str) -> AdmittedStudent | None:
    key = (lookup or "").strip()
    if not key:
        return None
    return (
        AdmittedStudent.objects.filter(is_admitted=True)
        .filter(Q(reg_no__iexact=key) | Q(student_id__iexact=key))
        .select_related(
            "admitted_program",
            "admitted_campus",
            "student_user",
            "application",
            "intended_program_batch",
            "programme_enrollment",
            "programme_enrollment__program_batch",
        )
        .first()
    )


def verify_student_credentials(username: str, password: str) -> tuple[User | None, AdmittedStudent | None]:
    """
    Authenticate Steward credentials for Moodle.
    Accepts portal username or registration number.
    """
    uname = (username or "").strip()
    pwd = password or ""
    if not uname or not pwd:
        return None, None

    user = authenticate(username=uname, password=pwd)
    student = None
    if user is None:
        student = resolve_student_by_lookup(uname)
        if student and student.student_user_id:
            portal_username = student.student_user.username
            user = authenticate(username=portal_username, password=pwd)

    if user is None:
        return None, None

    if student is None:
        student = (
            AdmittedStudent.objects.filter(is_admitted=True, student_user=user)
            .select_related(
                "admitted_program",
                "admitted_campus",
                "application",
                "intended_program_batch",
                "programme_enrollment",
                "programme_enrollment__program_batch",
            )
            .first()
        )
        if student is None:
            student = resolve_student_by_lookup(user.username)

    return user, student


def academic_batch_payload(student: AdmittedStudent) -> dict:
    """Enrollment cohort first, then intended batch. Additive LMS fields only."""
    from Programs.program_batch_resolution import format_program_batch_display

    batch = None
    try:
        enrollment = student.programme_enrollment
    except Exception:
        enrollment = None
    if enrollment is not None and enrollment.program_batch_id:
        batch = enrollment.program_batch
    if batch is None:
        batch = getattr(student, "intended_program_batch", None)
    if batch is None or not getattr(batch, "pk", None):
        return {"academic_batch_id": None, "academic_batch": None}
    return {
        "academic_batch_id": batch.pk,
        "academic_batch": format_program_batch_display(batch),
    }


def student_profile_payload(student: AdmittedStudent, user: User | None = None) -> dict:
    app = getattr(student, "application", None)
    reg_no = (student.reg_no or "").strip()
    username = (user.username if user else "") or student_portal_username(reg_no)
    firstname, lastname = split_full_name(student.full_name or "")
    payload = {
        "reg_no": reg_no,
        "student_id": student.student_id or "",
        "username": username,
        "firstname": firstname,
        "lastname": lastname,
        "full_name": student.full_name or "",
        "email": (getattr(app, "email", None) or getattr(user, "email", None) or "") if (app or user) else "",
        "programme": student.admitted_program.name if student.admitted_program_id else None,
        "campus": student.admitted_campus.name if student.admitted_campus_id else None,
        "accounts_registration_cleared": bool(
            getattr(student, "accounts_registration_cleared", False)
        ),
    }
    payload.update(academic_batch_payload(student))
    return payload


def moodle_launch_profile_for_student(
    student: AdmittedStudent,
    user: User | None = None,
) -> dict:
    """Signed profile fields embedded in SSO launch URL for first-time Moodle login."""
    reg_no = (student.reg_no or "").strip()
    username = (user.username if user else "") or student_portal_username(reg_no)
    firstname, lastname = split_full_name(student.full_name or "")
    email = (student.email or "").strip()
    if user and (user.email or "").strip():
        email = email or (user.email or "").strip()
    return {
        "username": username,
        "firstname": firstname,
        "lastname": lastname,
        "email": email,
    }


def finance_status_for_student(student: AdmittedStudent) -> dict:
    cfg = MoodleIntegrationConfig.get_solo()
    try:
        finance = student_finance_totals(student)
    except Exception:
        finance = {
            "percentage_paid": 0,
            "balance": 0,
            "total_paid": 0,
            "total_required": 0,
            "display_currency": "UGX",
            "commitment_met": False,
            "prepaid_credit": 0,
        }

    percent = Decimal(str(finance.get("percentage_paid") or 0))
    balance = Decimal(str(finance.get("balance") or 0))
    cleared_min = Decimal(str(cfg.cleared_min_percent or 100))
    partial_min = Decimal(str(cfg.partial_min_percent or 50))

    if balance <= 0 or percent >= cleared_min:
        status = "CLEARED"
    elif percent >= partial_min:
        status = "PARTIAL"
    else:
        status = "BLOCKED"

    payload = {
        "reg_no": student.reg_no or "",
        "student_id": student.student_id or "",
        "status": status,
        "percent_paid": float(percent),
        "balance": float(balance),
        "prepaid_credit": float(finance.get("prepaid_credit") or 0),
        "total_paid": float(finance.get("total_paid") or 0),
        "total_required": float(finance.get("total_required") or 0),
        "display_currency": finance.get("display_currency") or "UGX",
        "accounts_cleared": bool(getattr(student, "accounts_registration_cleared", False)),
        "commitment_met": bool(finance.get("commitment_met")),
        "cleared_min_percent": float(cleared_min),
        "partial_min_percent": float(partial_min),
        "as_of": datetime.now(timezone.utc).isoformat(),
    }
    payload.update(academic_batch_payload(student))
    return payload


def programme_enrollment_status_for_student(student: AdmittedStudent) -> str | None:
    try:
        spe = student.programme_enrollment
    except Exception:
        return None
    return getattr(spe, "status", None) if spe is not None else None


def student_is_programme_enrolled(student: AdmittedStudent) -> bool:
    return programme_enrollment_status_for_student(student) == "enrolled"


def lms_course_unit_enrollments_qs(student: AdmittedStudent):
    """
    Course units Moodle should sync for this student.

    - Programme **Enrolled** (commitment met): assigned course units count, even
      before formal semester registration (registration_date may be null).
    - Otherwise: only course units the student formally registered for.
    """
    from django.db.models import Q

    from Programs.models import StudentCourseUnitEnrollment

    base = StudentCourseUnitEnrollment.objects.filter(student=student, status="enrolled")
    if student_is_programme_enrolled(student):
        return base
    return base.filter(registration_date__isnull=False)


def registered_courses_for_student(student: AdmittedStudent) -> list[dict]:
    """Course units for Moodle — programme-enrolled or formally registered."""
    from Programs.models import StudentCourseUnitEnrollment

    enrollments = (
        lms_course_unit_enrollments_qs(student)
        .select_related(
            "course_unit",
            "course_unit__semester",
            "course_unit__program_batch",
            "course_unit__program_batch__program",
            "course_unit__program_batch__program__faculty",
            "course_unit__shared_teaching_offering",
            "course_unit__shared_teaching_offering__catalog_unit",
            "course_unit__shared_teaching_offering__parent_course_unit",
        )
        .prefetch_related(
            "course_unit__lecturers",
            "course_unit__section_lecturers__lecturer",
            "course_unit__shared_teaching_offering__lecturers",
        )
        .order_by("course_unit__code")
    )
    rows = []
    parent_ids: dict[int, str] = {}
    for enr in enrollments:
        cu = enr.course_unit
        if cu is None or not cu.is_active:
            continue
        row = moodle_course_unit_payload(cu, parent_ids=parent_ids)
        row["registration_kind"] = enr.registration_kind
        row["formally_registered"] = enr.registration_date is not None
        row["enrollment_source"] = enr.source or ""
        row["registration_date"] = (
            enr.registration_date.isoformat() if enr.registration_date else None
        )
        rows.append(row)
    return rows


def lecturer_payload(user) -> dict:
    return {
        "id": user.pk,
        "username": user.username,
        "email": user.email or "",
        "full_name": user.get_full_name() or user.username,
        "staff_id": getattr(user, "staff_id", None) or "",
    }


def _lecturers_for_course_unit(cu) -> list[dict]:
    lecturers = {u.pk: lecturer_payload(u) for u in cu.lecturers.all()}
    for link in cu.section_lecturers.all():
        if link.lecturer_id and link.lecturer_id not in lecturers:
            lecturers[link.lecturer_id] = lecturer_payload(link.lecturer)
    sto = getattr(cu, "shared_teaching_offering", None)
    if sto is not None:
        for u in sto.lecturers.all():
            lecturers.setdefault(u.pk, lecturer_payload(u))
    return list(lecturers.values())


def moodle_course_unit_payload(
    cu,
    *,
    parent_ids: dict[int, str] | None = None,
) -> dict:
    """Full Moodle sync row for one programme CourseUnit offering."""
    from Programs.shared_teaching import (
        moodle_shared_fields_for_course_unit,
        study_mode_for_course_unit,
    )

    batch = cu.program_batch if cu.program_batch_id else None
    program = batch.program if batch and batch.program_id else None
    faculty = program.faculty if program and program.faculty_id else None
    sem = cu.semester if cu.semester_id else None
    sto = cu.shared_teaching_offering if cu.shared_teaching_offering_id else None
    academic_year = ""
    if batch and (batch.academic_year or "").strip():
        academic_year = (batch.academic_year or "").strip()
    elif sto and (sto.academic_year_label or "").strip():
        academic_year = (sto.academic_year_label or "").strip()

    row = {
        "id": cu.pk,
        "code": cu.code,
        "name": cu.name,
        "credit_units": float(cu.credit_units) if cu.credit_units is not None else None,
        "semester_id": cu.semester_id,
        "semester": sem.name if sem else None,
        "year_of_study": sem.year_of_study if sem else None,
        "term_number": sem.term_number if sem else None,
        "academic_year": academic_year or None,
        "program_batch_id": cu.program_batch_id,
        "program_batch_name": batch.name if batch else None,
        "programme": program.name if program else None,
        "programme_id": program.pk if program else None,
        "program_code": getattr(program, "short_form", None) if program else None,
        "program_name": program.name if program else None,
        "faculty": faculty.name if faculty else None,
        "faculty_id": faculty.pk if faculty else None,
        "study_mode": study_mode_for_course_unit(cu),
        "exam_paper_code": sto.paper_code if sto else None,
        "lecturers": _lecturers_for_course_unit(cu),
    }
    row.update(moodle_shared_fields_for_course_unit(cu, parent_ids=parent_ids))
    return row


def shared_course_units_registry(
    *,
    semester_id: int | None = None,
    academic_year: str | None = None,
    term_number: int | None = None,
) -> list[dict]:
    """Registry of SharedTeachingOffering rows for Moodle admin / validation."""
    from Programs.models import CourseUnit, SharedTeachingOffering
    from Programs.shared_teaching import (
        moodle_parent_idnumber,
        offering_label_for_course_unit,
        parent_unit_id_for_sto,
        shared_unit_key_for_sto,
    )

    cu_qs = CourseUnit.objects.filter(
        is_active=True,
        shared_teaching_offering_id__isnull=False,
    )
    if semester_id is not None:
        cu_qs = cu_qs.filter(semester_id=semester_id)
    if academic_year:
        cu_qs = cu_qs.filter(program_batch__academic_year__icontains=academic_year.strip())
    if term_number is not None:
        cu_qs = cu_qs.filter(semester__term_number=term_number)

    sto_ids = cu_qs.values_list("shared_teaching_offering_id", flat=True).distinct()
    offerings = (
        SharedTeachingOffering.objects.filter(id__in=sto_ids, is_active=True)
        .prefetch_related(
            "course_units",
            "course_units__program_batch",
            "course_units__program_batch__program",
            "course_units__semester",
            "catalog_unit",
            "parent_course_unit",
        )
        .order_by("code", "id")
    )

    rows = []
    for sto in offerings:
        units = [
            u
            for u in sto.course_units.all()
            if u.is_active
            and (semester_id is None or u.semester_id == semester_id)
            and (
                not academic_year
                or (
                    u.program_batch_id
                    and academic_year.strip().lower()
                    in (u.program_batch.academic_year or "").lower()
                )
            )
            and (term_number is None or (u.semester_id and u.semester.term_number == term_number))
        ]
        if len(units) < 2:
            continue
        term_key = global_term_key_from_units(units)
        parent_unit_id = parent_unit_id_for_sto(sto)
        rows.append(
            {
                "shared_unit_key": shared_unit_key_for_sto(sto),
                "code": sto.code,
                "name": sto.name,
                "shared_teaching_offering_id": sto.pk,
                "parent_unit_id": parent_unit_id,
                "parent_idnumber": moodle_parent_idnumber(sto, term_key),
                "global_term_key": term_key,
                "semester_ids": sorted({u.semester_id for u in units if u.semester_id}),
                "offerings": [
                    {
                        "offering_id": str(u.pk),
                        "offering_label": offering_label_for_course_unit(u),
                        "programme_id": (
                            u.program_batch.program_id if u.program_batch_id else None
                        ),
                        "programme": (
                            u.program_batch.program.name
                            if u.program_batch_id and u.program_batch.program_id
                            else None
                        ),
                        "course_unit_id": u.pk,
                        "semester_id": u.semester_id,
                    }
                    for u in sorted(units, key=lambda x: (x.code or "", x.id))
                ],
            }
        )
    return rows


def global_term_key_from_units(units) -> str:
    from Programs.shared_teaching import global_term_key_for_course_unit

    if not units:
        return "S1"
    return global_term_key_for_course_unit(units[0])
