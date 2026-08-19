"""List admitted students that have two SchoolPay wallet codes."""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Count, F
from django.db.models.functions import Lower

from admissions.models import AdmittedStudent
from payments.models import TuitionLedger


def _name(student) -> str:
    app = getattr(student, "application", None)
    if not app:
        return ""
    return " ".join(
        part
        for part in (app.first_name or "", app.middle_name or "", app.last_name or "")
        if part
    ).strip()


class Command(BaseCommand):
    help = (
        "Students with two pay codes: student_id != schoolpay_code, "
        "and/or two distinct SchoolPay codes on TuitionLedger."
    )

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=500)

    def handle(self, *args, **options):
        limit = options["limit"]

        dual_fields = (
            AdmittedStudent.objects.exclude(student_id__isnull=True)
            .exclude(student_id="")
            .exclude(schoolpay_code__isnull=True)
            .exclude(schoolpay_code="")
            .exclude(student_id=F("schoolpay_code"))
            .select_related("application")
            .order_by("id")
        )
        self.stdout.write(
            f"student_id different from schoolpay_code ({dual_fields.count()}):"
        )
        for s in dual_fields[:limit]:
            self.stdout.write(
                f"  pk={s.pk} name={_name(s)!r} student_id={s.student_id!r} "
                f"schoolpay={s.schoolpay_code!r} reg={s.reg_no!r}"
            )
        if dual_fields.count() == 0:
            self.stdout.write("  (none)")

        ledger_dual = (
            TuitionLedger.objects.exclude(student_id=None)
            .exclude(student_payment_code="")
            .annotate(code=Lower("student_payment_code"))
            .values("student_id")
            .annotate(n=Count("code", distinct=True))
            .filter(n__gte=2)
            .order_by("-n", "student_id")
        )
        ids = [row["student_id"] for row in ledger_dual[:limit]]
        students = {
            s.pk: s
            for s in AdmittedStudent.objects.filter(pk__in=ids).select_related(
                "application"
            )
        }
        self.stdout.write(
            f"\nTwo or more distinct pay codes on ledger ({ledger_dual.count()}):"
        )
        if not ids:
            self.stdout.write("  (none)")
            return

        codes_by_student: dict[int, list[str]] = {}
        for row in (
            TuitionLedger.objects.filter(student_id__in=ids)
            .exclude(student_payment_code="")
            .values("student_id", "student_payment_code")
            .annotate(n=Count("id"))
            .order_by("student_id", "-n")
        ):
            codes_by_student.setdefault(row["student_id"], []).append(
                f"{row['student_payment_code']}({row['n']})"
            )

        for row in ledger_dual[:limit]:
            pk = row["student_id"]
            s = students.get(pk)
            name = _name(s) if s else "?"
            sid = getattr(s, "student_id", None)
            sp = getattr(s, "schoolpay_code", None)
            reg = getattr(s, "reg_no", None)
            codes = ", ".join(codes_by_student.get(pk, []))
            self.stdout.write(
                f"  pk={pk} name={name!r} student_id={sid!r} schoolpay={sp!r} "
                f"reg={reg!r} distinct={row['n']} codes={codes}"
            )
