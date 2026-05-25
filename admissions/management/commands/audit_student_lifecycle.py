"""
Print a plain-language student lifecycle audit report (counts + problem buckets).

Examples::

    python manage.py audit_student_lifecycle
    python manage.py audit_student_lifecycle --verbose
    python manage.py audit_student_lifecycle --csv reports/lifecycle_audit.csv
"""
from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db.models import Count, Q

from admissions.models import AdmittedStudent, Application, Batch


def _hr(title: str, width: int = 72) -> None:
    print()
    print("=" * width)
    print(title)
    print("=" * width)


def _section(title: str) -> None:
    print()
    print(f"--- {title} ---")


def _print_timetable_readiness(verbose: bool, limit: int) -> None:
    """Checks prerequisites before building a timetable module."""
    _hr("TIMETABLE READINESS (academic structure)")
    ready_flags: list[tuple[str, bool, str]] = []

    try:
        from admissions.models import AcademicYear
        from Programs.models import (
            CourseUnit,
            ProgramBatch,
            Semester,
            StudentCourseUnitEnrollment,
            StudentProgrammeEnrollment,
        )
    except ImportError as exc:
        print(f"  Programs/AcademicYear unavailable: {exc}")
        return

    # 1. Academic year registry
    _section("1. Academic year registry")
    ay_active = AcademicYear.objects.filter(is_active=True)
    ay_count = ay_active.count()
    ay_current = ay_active.filter(is_current=True).count()
    print(f"  Active years in registry:              {ay_count}")
    print(f"  Marked as current (is_current):        {ay_current}")
    registry_labels = set(ay_active.values_list("label", flat=True))
    ready_flags.append(
        (
            "Academic years",
            ay_count > 0 and ay_current == 1,
            "Need at least one active year and exactly one current.",
        )
    )

    pb_active = ProgramBatch.objects.filter(is_active=True)
    pb_total = pb_active.count()
    pb_no_year = pb_active.filter(academic_year="").count()
    pb_unknown_year = 0
    if registry_labels:
        pb_unknown_year = pb_active.exclude(academic_year="").exclude(
            academic_year__in=registry_labels
        ).count()
    print(f"  Active programme batches:                {pb_total}")
    print(f"  Batches with blank academic_year:        {pb_no_year}")
    print(f"  Batches with year not in registry:       {pb_unknown_year}")

    # 2. Programme batches + semesters (curriculum position)
    _section("2. Programme batches + semesters")
    sem_qs = Semester.objects.filter(program_batch__is_active=True, is_active=True)
    sem_total = sem_qs.count()
    sem_unpositioned = sem_qs.filter(
        Q(year_of_study__isnull=True) | Q(term_number__isnull=True)
    ).count()
    batches_no_semesters = pb_active.annotate(sem_count=Count("semesters")).filter(
        sem_count=0
    ).count()
    print(f"  Active semesters (all active batches):   {sem_total}")
    print(f"  Semesters missing year/term (Y/T):       {sem_unpositioned}")
    print(f"  Active batches with zero semesters:      {batches_no_semesters}")
    ready_flags.append(
        (
            "Semesters positioned",
            sem_total > 0 and sem_unpositioned == 0,
            "Every active semester needs year_of_study + term_number.",
        )
    )
    ready_flags.append(
        (
            "Batches have semesters",
            pb_total == 0 or batches_no_semesters == 0,
            "Create semesters (or auto-generate) on each active batch.",
        )
    )

    if verbose and sem_unpositioned:
        print("  Sample semesters missing Y/T:")
        for s in sem_qs.filter(
            Q(year_of_study__isnull=True) | Q(term_number__isnull=True)
        ).select_related("program_batch__program")[:limit]:
            print(
                f"       · sem id={s.id} {s.name} batch={s.program_batch.name} "
                f"prog={s.program_batch.program.short_form}"
            )

    # 3. Course units for the term
    _section("3. Course units (operational offerings)")
    cu_active = CourseUnit.objects.filter(is_active=True)
    cu_total = cu_active.count()
    cu_no_semester = cu_active.filter(semester__isnull=True).count()
    cu_no_lecturer = (
        cu_active.annotate(lc=Count("lecturers")).filter(lc=0).count()
    )
    print(f"  Active course units:                     {cu_total}")
    print(f"  Without a semester FK:                   {cu_no_semester}")
    print(f"  Without any lecturer assigned:           {cu_no_lecturer}")
    ready_flags.append(
        (
            "Course units exist",
            cu_total > 0,
            "Instantiate units from curriculum or add manually per semester.",
        )
    )

    _section("  Course units per positioned semester (top 15)")
    sem_with_units = (
        sem_qs.filter(year_of_study__isnull=False, term_number__isnull=False)
        .annotate(unit_count=Count("course_units", filter=Q(course_units__is_active=True)))
        .order_by("-unit_count")[:15]
    )
    sem_zero_units = 0
    for s in sem_qs.filter(
        year_of_study__isnull=False, term_number__isnull=False
    ).annotate(unit_count=Count("course_units", filter=Q(course_units__is_active=True))):
        if s.unit_count == 0:
            sem_zero_units += 1
    print(f"  Positioned semesters with 0 course units: {sem_zero_units}")
    for s in sem_with_units:
        pb = s.program_batch
        print(
            f"    - {pb.program.short_form} / {pb.name} / {s.name} "
            f"(Y{s.year_of_study}T{s.term_number}): {s.unit_count} units"
        )

    if verbose and cu_no_lecturer:
        print("  Sample units without lecturers:")
        for cu in (
            cu_active.annotate(lc=Count("lecturers"))
            .filter(lc=0)
            .select_related("semester", "program_batch__program")[:limit]
        ):
            sem_name = cu.semester.name if cu.semester_id else "—"
            print(f"       · {cu.code} {cu.name} sem={sem_name}")

    # 4. Programme enrollment
    _section("4. Programme enrollment (SPE)")
    spe_total = StudentProgrammeEnrollment.objects.count()
    spe_enrolled = StudentProgrammeEnrollment.objects.filter(status="enrolled").count()
    spe_pending = StudentProgrammeEnrollment.objects.filter(status="pending").count()
    spe_no_batch = StudentProgrammeEnrollment.objects.filter(
        program_batch__isnull=True
    ).count()
    print(f"  All programme enrollments:               {spe_total}")
    print(f"  Status enrolled:                         {spe_enrolled}")
    print(f"  Status pending:                          {spe_pending}")
    print(f"  Missing program_batch on SPE:            {spe_no_batch}")
    ready_flags.append(
        (
            "Students enrolled on programme",
            spe_enrolled > 0,
            "Activate SPE after commitment / admin enroll.",
        )
    )

    # 5. Course unit registration
    _section("5. Course unit registration")
    scu_total = StudentCourseUnitEnrollment.objects.filter(status="enrolled").count()
    enrolled_student_ids = StudentProgrammeEnrollment.objects.filter(
        status="enrolled"
    ).values_list("student_id", flat=True)
    enrolled_with_cu = (
        StudentCourseUnitEnrollment.objects.filter(
            status="enrolled", student_id__in=enrolled_student_ids
        )
        .values("student_id")
        .distinct()
        .count()
    )
    enrolled_no_cu = max(0, spe_enrolled - enrolled_with_cu)
    units_no_students = (
        cu_active.annotate(ec=Count("student_enrollments", filter=Q(
            student_enrollments__status="enrolled"
        ))).filter(ec=0).count()
    )
    print(f"  Active course-unit enrollments:          {scu_total}")
    print(f"  SPE-enrolled students with >=1 unit:     {enrolled_with_cu}")
    print(f"  SPE-enrolled with no unit registration:  {enrolled_no_cu}")
    print(f"  Active course units with 0 students:     {units_no_students}")
    ready_flags.append(
        (
            "Course registration started",
            scu_total > 0,
            "Students should register (portal/admin) before timetable is useful.",
        )
    )

    # Summary
    _section("Timetable readiness summary")
    all_ok = True
    for name, ok, hint in ready_flags:
        mark = "OK" if ok else "GAP"
        if not ok:
            all_ok = False
        print(f"  [{mark}] {name}")
        if not ok:
            print(f"         -> {hint}")
    if all_ok:
        print()
        print("  Structure looks ready to attach timetable sessions (Phase 1).")
    else:
        print()
        print("  Fix GAP items before timetabling; see STUDENT_LIFECYCLE_REPORT.md §11.")


class Command(BaseCommand):
    help = "Audit student lifecycle: application → admission → payments → registration."

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            default="",
            help="Optional path to write detail rows (problem students) as CSV.",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="List up to 30 sample rows per problem bucket.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=30,
            help="Max sample rows per bucket when --verbose (default 30).",
        )
        parser.add_argument(
            "--timetable-only",
            action="store_true",
            help="Print only the timetable readiness block (skip student lifecycle).",
        )

    def handle(self, *args, **options):
        verbose = options["verbose"]
        limit = options["limit"]
        csv_path = (options["csv"] or "").strip()
        timetable_only = options["timetable_only"]

        try:
            from Programs.models import StudentProgrammeEnrollment
        except ImportError:
            self.stderr.write("Programs app not available; enrollment checks skipped.")
            StudentProgrammeEnrollment = None

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if timetable_only:
            _print_timetable_readiness(verbose, limit)
            self.stdout.write(self.style.SUCCESS("Timetable readiness audit complete."))
            return

        _hr(f"STUDENT LIFECYCLE AUDIT  ({now})")

        # ── Overview ─────────────────────────────────────────────────────
        _section("Overview")
        app_total = Application.objects.count()
        batch_total = Batch.objects.count()
        admitted_qs = AdmittedStudent.objects.filter(is_admitted=True)
        admitted_total = admitted_qs.count()

        print(f"  Intake batches (admissions.Batch):     {batch_total}")
        print(f"  Applications (all):                    {app_total}")
        print(f"  Admitted students (is_admitted=True): {admitted_total}")

        print()
        print("  Applications by status:")
        for row in (
            Application.objects.values("status")
            .annotate(c=Count("id"))
            .order_by("-c")
        ):
            print(f"    - {row['status'] or '(blank)'}: {row['c']}")

        print()
        print("  Applications by intake batch:")
        for row in (
            Application.objects.values("batch_id", "batch__name")
            .annotate(c=Count("id"))
            .order_by("-c")[:15]
        ):
            name = row["batch__name"] or f"id={row['batch_id']}"
            print(f"    - {name}: {row['c']}")

        print()
        print("  Admitted students by intake batch (admitted_batch):")
        for row in (
            admitted_qs.values("admitted_batch_id", "admitted_batch__name")
            .annotate(c=Count("id"))
            .order_by("-c")[:15]
        ):
            name = row["admitted_batch__name"] or f"id={row['admitted_batch_id']}"
            print(f"    - {name}: {row['c']}")

        # ── Payment & registration flags ─────────────────────────────────
        _section("Payment and registration flags (admitted students)")
        print(f"  application_fee_paid (via application):  "
              f"{admitted_qs.filter(application__application_fee_paid=True).count()}")
        print(f"  admission_fee_paid:                    "
              f"{admitted_qs.filter(admission_fee_paid=True).count()}")
        print(f"  is_registered_with_schoolpay:          "
              f"{admitted_qs.filter(is_registered_with_schoolpay=True).count()}")
        print(f"  is_registered (course registration):   "
              f"{admitted_qs.filter(is_registered=True).count()}")
        print(f"  physical_documents_verified:           "
              f"{admitted_qs.filter(physical_documents_verified=True).count()}")
        print(f"  has student_user (portal login):       "
              f"{admitted_qs.filter(student_user_id__isnull=False).count()}")
        print(f"  intended_program_batch set:            "
              f"{admitted_qs.filter(intended_program_batch_id__isnull=False).count()}")

        if StudentProgrammeEnrollment is not None:
            spe_enrolled = admitted_qs.filter(
                programme_enrollment__status="enrolled"
            ).count()
            spe_pending = admitted_qs.filter(
                programme_enrollment__status="pending"
            ).count()
            spe_none = admitted_total - admitted_qs.filter(
                programme_enrollment__isnull=False
            ).count()
            print(f"  programme enrollment — enrolled:       {spe_enrolled}")
            print(f"  programme enrollment — pending:        {spe_pending}")
            print(f"  programme enrollment — missing:        {spe_none}")

        # ── Problem buckets ──────────────────────────────────────────────
        _section("Problem buckets (needs attention)")
        problems: list[dict] = []

        def add_bucket(code: str, label: str, qs):
            n = qs.count()
            print(f"  [{code}] {label}: {n}")
            if verbose and n:
                sample = qs.select_related(
                    "application", "admitted_program", "admitted_batch"
                )[:limit]
                for s in sample:
                    app = s.application
                    print(
                        f"       · id={s.id} reg={s.reg_no} "
                        f"{app.first_name} {app.last_name} "
                        f"prog={getattr(s.admitted_program, 'name', '?')} "
                        f"intake={getattr(s.admitted_batch, 'name', '?')}"
                    )
            for s in qs.iterator(chunk_size=500):
                app = s.application
                problems.append({
                    "bucket": code,
                    "bucket_label": label,
                    "admitted_student_id": s.id,
                    "reg_no": s.reg_no or "",
                    "student_id": s.student_id or "",
                    "full_name": f"{app.first_name} {app.last_name}".strip(),
                    "email": app.email or "",
                    "application_id": app.id,
                    "application_status": app.status or "",
                    "is_revoked": app.is_revoked,
                    "intake_batch": getattr(s.admitted_batch, "name", ""),
                    "programme": getattr(s.admitted_program, "name", ""),
                    "admission_fee_paid": s.admission_fee_paid,
                    "is_registered": s.is_registered,
                    "has_student_user": bool(s.student_user_id),
                    "intended_program_batch_id": s.intended_program_batch_id or "",
                })
            return n

        if StudentProgrammeEnrollment is not None:
            add_bucket(
                "NO_ENROLLMENT",
                "Admitted but no programme enrollment (SPE)",
                admitted_qs.filter(programme_enrollment__isnull=True),
            )
            add_bucket(
                "ENROLL_PENDING",
                "Enrollment exists but status is not 'enrolled'",
                admitted_qs.filter(programme_enrollment__isnull=False).exclude(
                    programme_enrollment__status="enrolled"
                ),
            )
        else:
            print("  (Programme enrollment checks skipped — Programs app unavailable)")

        add_bucket(
            "NO_ACADEMIC_BATCH",
            "No intended_program_batch (academic cohort)",
            admitted_qs.filter(intended_program_batch_id__isnull=True),
        )
        add_bucket(
            "NO_STUDENT_LOGIN",
            "No student_user linked (Celery account may have failed)",
            admitted_qs.filter(student_user_id__isnull=True),
        )
        add_bucket(
            "REVOKED_APP",
            "Application marked revoked (should not be active cohort)",
            admitted_qs.filter(
                Q(application__status="revoked") | Q(application__is_revoked=True)
            ),
        )

        # Applications Admitted without AdmittedStudent
        orphan_apps = Application.objects.filter(
            status__iexact="admitted"
        ).exclude(admission__isnull=False)
        n_orphan = orphan_apps.count()
        print(f"  [ORPHAN_APP] Application status Admitted but no AdmittedStudent: {n_orphan}")
        if verbose and n_orphan:
            for app in orphan_apps[:limit]:
                print(f"       · app id={app.id} {app.first_name} {app.last_name} {app.email}")

        # Accepted with admission row (ok) vs accepted without (queue)
        _section("Application queue (not yet admitted)")
        for st in ("submitted", "under_review", "accepted", "approved"):
            c = Application.objects.filter(status=st).count()
            if c:
                print(f"  status={st}: {c}")

        revoked_apps = Application.objects.filter(
            Q(status="revoked") | Q(is_revoked=True)
        ).count()
        print(f"  revoked applications (all): {revoked_apps}")

        # ── Exams readiness summary ──────────────────────────────────────
        _section("Suggested exams readiness (strict rule)")
        if StudentProgrammeEnrollment is not None:
            exam_ready = admitted_qs.filter(
                application__is_revoked=False,
                programme_enrollment__status="enrolled",
                intended_program_batch_id__isnull=False,
            ).exclude(application__status__in=["revoked", "rejected", "draft"])
            print(f"  Likely exam-ready (strict): {exam_ready.count()} of {admitted_total}")
            print("  Rule: is_admitted + SPE enrolled + intended_program_batch + not revoked")
        else:
            print("  Cannot compute exam-ready without StudentProgrammeEnrollment model.")

        # ── CSV ──────────────────────────────────────────────────────────
        if csv_path:
            path = Path(csv_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            if problems:
                with path.open("w", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=list(problems[0].keys()))
                    w.writeheader()
                    w.writerows(problems)
                print()
                print(f"  Wrote {len(problems)} detail rows to {path}")
            else:
                print()
                print(f"  No problem rows to write (file not created): {path}")

        _print_timetable_readiness(verbose, limit)

        _section("Full guide")
        print("  Read: admissions/docs/STUDENT_LIFECYCLE_REPORT.md")
        print()
        self.stdout.write(self.style.SUCCESS("Audit complete."))
