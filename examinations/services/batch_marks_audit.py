"""Shared helpers for programme-batch marks readiness audit and cleanup."""
from __future__ import annotations

from dataclasses import dataclass, field

from django.db.models import Q, QuerySet

from Programs.models import CourseUnit, ProgramBatch, Semester, StudentCourseUnitEnrollment
from Programs.models import StudentProgrammeEnrollment

from examinations.models import CourseUnitResult, MarksEntryWindow
from examinations.services.grade_scale_resolver import resolve_grade_scale
from examinations.services.marks_window import marks_entry_status
from examinations.services.policy_resolver import resolve_assessment_policy


def resolve_program_batches(batch: str | None = None, batch_id: int | None = None) -> list[ProgramBatch]:
    """
    Resolve ProgramBatch rows from id or name/label fragment.

    Accepts labels like ``LLB-377-Main`` or ``Bachelors of Laws-Main - LLB-377-Main``.
    """
    qs = ProgramBatch.objects.select_related(
        "program",
        "program__faculty",
        "program__academic_level",
    )
    if batch_id:
        found = qs.filter(pk=batch_id).first()
        if not found:
            raise ValueError(f"ProgramBatch id={batch_id} not found.")
        return [found]

    needle = (batch or "").strip()
    if not needle:
        raise ValueError("Provide --batch name or --batch-id.")

    # Prefer exact name match, then contains on name / program short_form / program name.
    exact = list(qs.filter(name__iexact=needle))
    if exact:
        return exact

    # Strip common UI "Program - Batch" prefix.
    if " - " in needle:
        tail = needle.rsplit(" - ", 1)[-1].strip()
        if tail and tail.lower() != needle.lower():
            exact_tail = list(qs.filter(name__iexact=tail))
            if exact_tail:
                return exact_tail
            needle = tail

    matches = list(
        qs.filter(
            Q(name__icontains=needle)
            | Q(program__short_form__icontains=needle)
            | Q(program__name__icontains=needle)
            | Q(program__code__icontains=needle)
        ).distinct()
    )
    if not matches:
        raise ValueError(f"No ProgramBatch matched {batch!r}.")
    return matches


def course_units_for_batch(program_batch: ProgramBatch) -> QuerySet[CourseUnit]:
    return (
        CourseUnit.objects.filter(program_batch=program_batch, is_active=True)
        .select_related("semester", "program_batch", "program_batch__program", "program_batch__program__academic_level")
        .prefetch_related("lecturers")
        .order_by("semester__order", "code")
    )


def spe_for_batch(program_batch: ProgramBatch) -> QuerySet[StudentProgrammeEnrollment]:
    return (
        StudentProgrammeEnrollment.objects.filter(program_batch=program_batch)
        .select_related(
            "student",
            "student__application",
            "program",
            "program_batch",
        )
        .order_by("student__reg_no")
    )


def enrollments_for_batch(program_batch: ProgramBatch) -> QuerySet[StudentCourseUnitEnrollment]:
    return StudentCourseUnitEnrollment.objects.filter(
        course_unit__program_batch=program_batch
    ).select_related(
        "student",
        "student__application",
        "course_unit",
        "course_unit__semester",
        "course_result",
    )


def results_for_batch(program_batch: ProgramBatch) -> QuerySet[CourseUnitResult]:
    return CourseUnitResult.objects.filter(
        enrollment__course_unit__program_batch=program_batch
    ).select_related(
        "enrollment",
        "enrollment__student",
        "enrollment__course_unit",
        "entered_by",
        "published_by",
        "verified_by",
    )


def is_legacy_student(student) -> bool:
    app = getattr(student, "application", None)
    source = (getattr(app, "source", None) or "").strip().lower()
    return source in ("legacy_import", "legacy", "legacy_imported", "imported")


@dataclass
class CourseAuditRow:
    course_unit_id: int
    code: str
    name: str
    semester_id: int | None
    semester_name: str
    lecturer_count: int
    enrolled: int
    registered: int
    unregistered: int
    results_draft: int
    results_verified: int
    results_published: int
    results_without_registration: int
    policy_ok: bool
    policy_name: str
    grade_scale_ok: bool
    grade_scale_name: str
    marks_entry_open: bool
    marks_entry_detail: str
    window_scope: str


@dataclass
class BatchAuditSummary:
    batch: ProgramBatch
    course_rows: list[CourseAuditRow] = field(default_factory=list)
    spe_total: int = 0
    spe_enrolled: int = 0
    spe_legacy: int = 0
    spe_portal: int = 0
    student_revoked: int = 0
    enrollment_total: int = 0
    enrollment_registered: int = 0
    enrollment_unregistered: int = 0
    results_draft: int = 0
    results_verified: int = 0
    results_published: int = 0
    results_without_registration: int = 0
    windows: list[dict] = field(default_factory=list)
    dirty_notes: list[str] = field(default_factory=list)
    result_entered_by: list[dict] = field(default_factory=list)
    result_date_range: dict = field(default_factory=dict)


def audit_program_batch(program_batch: ProgramBatch) -> BatchAuditSummary:
    summary = BatchAuditSummary(batch=program_batch)

    spes = list(spe_for_batch(program_batch))
    summary.spe_total = len(spes)
    for spe in spes:
        student = spe.student
        if spe.status == "enrolled":
            summary.spe_enrolled += 1
        if getattr(student, "application", None) and getattr(student.application, "is_revoked", False):
            summary.student_revoked += 1
        if is_legacy_student(student):
            summary.spe_legacy += 1
        else:
            summary.spe_portal += 1

    courses = list(course_units_for_batch(program_batch))
    enrollments = list(enrollments_for_batch(program_batch))
    summary.enrollment_total = len(enrollments)
    by_course: dict[int, list[StudentCourseUnitEnrollment]] = {}
    for enr in enrollments:
        by_course.setdefault(enr.course_unit_id, []).append(enr)
        if enr.registration_date:
            summary.enrollment_registered += 1
        else:
            summary.enrollment_unregistered += 1

    results = list(results_for_batch(program_batch))
    result_by_enrollment = {r.enrollment_id: r for r in results}
    for r in results:
        if r.status == CourseUnitResult.STATUS_DRAFT:
            summary.results_draft += 1
        elif r.status == CourseUnitResult.STATUS_VERIFIED:
            summary.results_verified += 1
        elif r.status == CourseUnitResult.STATUS_PUBLISHED:
            summary.results_published += 1
        if not r.enrollment.registration_date:
            summary.results_without_registration += 1

    if results:
        times = [r.updated_at for r in results if r.updated_at]
        if times:
            summary.result_date_range = {
                "earliest": min(times).isoformat(),
                "latest": max(times).isoformat(),
            }
        enterers: dict[str, int] = {}
        for r in results:
            key = (
                (r.entered_by.get_full_name() if r.entered_by_id else "")
                or (getattr(r.entered_by, "email", None) if r.entered_by_id else None)
                or "(unknown)"
            )
            enterers[key] = enterers.get(key, 0) + 1
        summary.result_entered_by = [
            {"user": k, "count": v} for k, v in sorted(enterers.items(), key=lambda x: -x[1])
        ]

    windows = list(
        MarksEntryWindow.objects.filter(program_batch=program_batch)
        .select_related("semester", "course_unit")
        .order_by("-is_active", "semester__order", "course_unit__code", "-updated_at")
    )
    for w in windows:
        summary.windows.append(
            {
                "id": w.id,
                "name": w.name,
                "is_active": w.is_active,
                "scope": (
                    "course"
                    if w.course_unit_id
                    else "semester"
                    if w.semester_id
                    else "batch"
                ),
                "semester": w.semester.name if w.semester_id else "",
                "course_code": w.course_unit.code if w.course_unit_id else "",
                "opens_at": w.opens_at.isoformat() if w.opens_at else "",
                "closes_at": w.closes_at.isoformat() if w.closes_at else "",
            }
        )

    for cu in courses:
        rows = by_course.get(cu.id, [])
        active_rows = [e for e in rows if e.status in ("enrolled", "completed", "failed")]
        registered = [e for e in active_rows if e.registration_date]
        unregistered = [e for e in active_rows if not e.registration_date]

        draft = verified = published = without_reg = 0
        for e in active_rows:
            r = result_by_enrollment.get(e.id)
            if not r:
                continue
            if r.status == CourseUnitResult.STATUS_DRAFT:
                draft += 1
            elif r.status == CourseUnitResult.STATUS_VERIFIED:
                verified += 1
            elif r.status == CourseUnitResult.STATUS_PUBLISHED:
                published += 1
            if not e.registration_date:
                without_reg += 1

        policy = resolve_assessment_policy(course_unit=cu)
        scale = resolve_grade_scale(course_unit=cu)
        status = marks_entry_status(cu, user=None)
        window_meta = status.get("window") or {}

        summary.course_rows.append(
            CourseAuditRow(
                course_unit_id=cu.id,
                code=cu.code or "",
                name=cu.name or "",
                semester_id=cu.semester_id,
                semester_name=cu.semester.name if cu.semester_id else "",
                lecturer_count=cu.lecturers.count(),
                enrolled=len(active_rows),
                registered=len(registered),
                unregistered=len(unregistered),
                results_draft=draft,
                results_verified=verified,
                results_published=published,
                results_without_registration=without_reg,
                policy_ok=policy is not None,
                policy_name=policy.name if policy else "",
                grade_scale_ok=scale is not None,
                grade_scale_name=scale.name if scale else "",
                marks_entry_open=bool(status.get("is_open")),
                marks_entry_detail=status.get("detail") or "",
                window_scope=window_meta.get("scope") or "none",
            )
        )

    # Dirty signals
    if summary.results_draft or summary.results_verified:
        summary.dirty_notes.append(
            f"{summary.results_draft} draft + {summary.results_verified} verified "
            "result(s) — treat as test data until confirmed otherwise."
        )
    if summary.results_published and summary.enrollment_unregistered:
        summary.dirty_notes.append(
            f"{summary.results_published} published result(s) while "
            f"{summary.enrollment_unregistered} enrollment(s) lack registration_date."
        )
    if summary.results_without_registration:
        summary.dirty_notes.append(
            f"{summary.results_without_registration} result(s) on unregistered enrollments."
        )
    no_lecturer = [c for c in summary.course_rows if c.lecturer_count == 0 and c.enrolled > 0]
    if no_lecturer:
        summary.dirty_notes.append(
            f"{len(no_lecturer)} course(s) with enrollments but no lecturers assigned."
        )
    no_policy = [c for c in summary.course_rows if not c.policy_ok]
    if no_policy:
        summary.dirty_notes.append(f"{len(no_policy)} course(s) missing assessment policy.")
    closed = [c for c in summary.course_rows if not c.marks_entry_open and c.enrolled > 0]
    if closed:
        summary.dirty_notes.append(
            f"{len(closed)} course(s) with enrollments but marks entry closed / no window."
        )
    if summary.spe_legacy and summary.enrollment_unregistered:
        summary.dirty_notes.append(
            f"{summary.spe_legacy} legacy SPE student(s); many may still need registration stamps "
            "before they appear on the marks roster."
        )

    return summary


def format_summary_text(summary: BatchAuditSummary) -> str:
    b = summary.batch
    prog = b.program
    lines = [
        f"ProgramBatch #{b.id}: {prog.short_form or prog.code} — {b.name}",
        f"  Programme: {prog.name} (id={prog.id})",
        f"  Faculty: {prog.faculty.name if prog.faculty_id else '—'}",
        f"  Level: {prog.academic_level.name if prog.academic_level_id else '—'}",
        f"  Academic year: {b.academic_year or '—'}",
        "",
        "Students (SPE)",
        f"  total={summary.spe_total} enrolled_status={summary.spe_enrolled} "
        f"legacy={summary.spe_legacy} portal={summary.spe_portal} revoked={summary.student_revoked}",
        "",
        "Course enrollments",
        f"  total={summary.enrollment_total} registered={summary.enrollment_registered} "
        f"unregistered={summary.enrollment_unregistered}",
        "",
        "CourseUnitResult",
        f"  draft={summary.results_draft} verified={summary.results_verified} "
        f"published={summary.results_published} without_registration={summary.results_without_registration}",
    ]
    if summary.result_date_range:
        lines.append(
            f"  updated_at range: {summary.result_date_range.get('earliest')} → "
            f"{summary.result_date_range.get('latest')}"
        )
    if summary.result_entered_by:
        lines.append("  entered_by:")
        for row in summary.result_entered_by[:12]:
            lines.append(f"    {row['user']}: {row['count']}")

    lines.extend(["", f"MarksEntryWindow ({len(summary.windows)})"])
    if not summary.windows:
        lines.append("  (none)")
    for w in summary.windows:
        lines.append(
            f"  #{w['id']} [{w['scope']}] active={w['is_active']} "
            f"{w['name']!r} sem={w['semester'] or '—'} course={w['course_code'] or '—'}"
        )

    lines.extend(["", "Courses"])
    for c in summary.course_rows:
        lines.append(
            f"  {c.code} | sem={c.semester_name or '—'} | lecturers={c.lecturer_count} | "
            f"enr={c.enrolled} reg={c.registered} unreg={c.unregistered} | "
            f"results d/v/p={c.results_draft}/{c.results_verified}/{c.results_published} | "
            f"policy={'OK' if c.policy_ok else 'MISSING'} scale={'OK' if c.grade_scale_ok else 'MISSING'} | "
            f"window={'OPEN' if c.marks_entry_open else 'CLOSED'} ({c.window_scope})"
        )

    if summary.dirty_notes:
        lines.extend(["", "Signals"])
        for note in summary.dirty_notes:
            lines.append(f"  - {note}")

    return "\n".join(lines)


def course_rows_as_dicts(summary: BatchAuditSummary) -> list[dict]:
    out = []
    for c in summary.course_rows:
        out.append(
            {
                "batch_id": summary.batch.id,
                "batch_name": summary.batch.name,
                "program": summary.batch.program.name,
                "course_unit_id": c.course_unit_id,
                "code": c.code,
                "name": c.name,
                "semester": c.semester_name,
                "lecturer_count": c.lecturer_count,
                "enrolled": c.enrolled,
                "registered": c.registered,
                "unregistered": c.unregistered,
                "results_draft": c.results_draft,
                "results_verified": c.results_verified,
                "results_published": c.results_published,
                "results_without_registration": c.results_without_registration,
                "policy_ok": c.policy_ok,
                "policy_name": c.policy_name,
                "grade_scale_ok": c.grade_scale_ok,
                "grade_scale_name": c.grade_scale_name,
                "marks_entry_open": c.marks_entry_open,
                "marks_entry_detail": c.marks_entry_detail,
                "window_scope": c.window_scope,
            }
        )
    return out


def semesters_for_batch(program_batch: ProgramBatch) -> QuerySet[Semester]:
    return Semester.objects.filter(program_batch=program_batch).order_by("order", "name")
