"""Mark (or create) admitted students as eligible for hostel assignment."""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from admissions.models import AdmittedStudent
from hostel.eligibility import student_hostel_eligibility, student_gender
from hostel.models import HostelAllocation


class Command(BaseCommand):
    help = (
        "Mark admitted students as hostel-eligible: accounts clearance + AR docs, "
        "ensure gender is set. Useful for local assign-wizard testing."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--count",
            type=int,
            default=12,
            help="How many students to make eligible (default: 12).",
        )
        parser.add_argument(
            "--q",
            action="append",
            default=[],
            help=(
                "Also force-clear specific students (reg_no / student_id / name token). "
                "Repeatable."
            ),
        )
        parser.add_argument(
            "--male",
            type=int,
            default=6,
            help="Prefer this many male students among the batch (default: 6).",
        )
        parser.add_argument(
            "--female",
            type=int,
            default=6,
            help="Prefer this many female students among the batch (default: 6).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        now = timezone.now()
        target = max(1, int(options["count"]))
        want_male = max(0, int(options["male"]))
        want_female = max(0, int(options["female"]))
        queries = list(options["q"] or [])

        # Always include the student the user was testing if no explicit --q.
        if not queries:
            queries = ["SENGENDO", "26/2/212/I/0001"]

        cleared: list[AdmittedStudent] = []
        seen: set[int] = set()

        def clear_student(student: AdmittedStudent, *, force_gender: str | None = None):
            if student.pk in seen:
                return False
            app = getattr(student, "application", None)
            if app is None:
                self.stdout.write(
                    self.style.WARNING(f"Skip pk={student.pk}: no application")
                )
                return False
            gender = student_gender(student)
            if not gender:
                if force_gender:
                    app.gender = force_gender
                    app.save(update_fields=["gender"])
                else:
                    # Default unknown genders alternately later; skip for named lookups.
                    app.gender = "Male"
                    app.save(update_fields=["gender"])
            student.is_admitted = True
            student.accounts_registration_cleared = True
            student.accounts_registration_cleared_at = now
            student.physical_documents_verified = True
            student.physical_documents_verified_at = now
            student.save(
                update_fields=[
                    "is_admitted",
                    "accounts_registration_cleared",
                    "accounts_registration_cleared_at",
                    "physical_documents_verified",
                    "physical_documents_verified_at",
                ]
            )
            seen.add(student.pk)
            cleared.append(student)
            return True

        # 1) Explicit lookups first
        from django.db.models import Q

        qs_base = AdmittedStudent.objects.select_related(
            "application", "admitted_campus", "admitted_program"
        )
        for raw in queries:
            token = (raw or "").strip()
            if not token:
                continue
            found = list(
                qs_base.filter(
                    Q(reg_no__icontains=token)
                    | Q(student_id__icontains=token)
                    | Q(application__last_name__icontains=token)
                    | Q(application__first_name__icontains=token)
                )[:5]
            )
            for s in found:
                clear_student(s)

        # 2) Fill remaining from students without active hostel allocation
        remaining = max(0, target - len(cleared))
        males_have = sum(
            1 for s in cleared if student_gender(s) == "male"
        )
        females_have = sum(
            1 for s in cleared if student_gender(s) == "female"
        )
        need_male = max(0, want_male - males_have)
        need_female = max(0, want_female - females_have)

        active_ids = HostelAllocation.objects.filter(
            status=HostelAllocation.STATUS_ACTIVE
        ).values_list("student_id", flat=True)

        pool = (
            qs_base.filter(is_admitted=True)
            .exclude(pk__in=seen)
            .exclude(pk__in=active_ids)
            .order_by("id")
        )

        def take(gender_norm: str, gender_write: str, n: int):
            taken = 0
            # Prefer students who already have matching gender
            for s in pool.filter(
                Q(application__gender__iexact=gender_norm)
                | Q(application__gender__iexact=gender_write)
                | Q(application__gender__istartswith=gender_norm[0])
            ):
                if taken >= n:
                    break
                if clear_student(s):
                    taken += 1
            # Fill from gender-missing if still short
            if taken < n:
                for s in pool.exclude(pk__in=seen):
                    if taken >= n:
                        break
                    g = student_gender(s)
                    if g and g != gender_norm:
                        continue
                    if clear_student(s, force_gender=gender_write):
                        taken += 1
            return taken

        take("male", "Male", need_male)
        take("female", "Female", need_female)

        # Any leftover count without gender preference
        still = max(0, target - len(cleared))
        if still:
            for s in pool.exclude(pk__in=seen)[: still * 2]:
                if len(cleared) >= target:
                    break
                clear_student(s)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Cleared {len(cleared)} student(s) for hostel:"))
        for s in cleared:
            elig = student_hostel_eligibility(s)
            app = s.application
            name = " ".join(
                p
                for p in [
                    getattr(app, "first_name", "") or "",
                    getattr(app, "middle_name", "") or "",
                    getattr(app, "last_name", "") or "",
                ]
                if p
            ).strip()
            status = "OK" if elig["ok"] else f"NOT OK: {'; '.join(elig['reasons'])}"
            self.stdout.write(
                f"  - {name} · {s.reg_no or s.student_id} · "
                f"{student_gender(s)} · pk={s.pk} => {status}"
            )

        if not cleared:
            self.stdout.write(
                self.style.ERROR(
                    "No admitted students found to clear. Admit students first, then re-run."
                )
            )
