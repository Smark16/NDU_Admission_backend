"""
List exemption requests that Accounts billed but SPE is not at the promotion target.

Usage:
  python manage.py list_billed_unpromoted_exemptions
  python manage.py list_billed_unpromoted_exemptions --also-no-target
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Q

from admissions.exemption_services import (
    exemption_promotion_applied,
    exemption_promotion_proposed,
)
from admissions.models import AdmissionChangeRequest


class Command(BaseCommand):
    help = (
        "Exemption CRs with accounts billed/confirmed where the student is not "
        "yet at the stored promotion year/term (or has no promotion target)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--also-no-target",
            action="store_true",
            help="Also list billed CRs with no HOD promotion year/term stored.",
        )

    def handle(self, *args, **options):
        also_no_target = bool(options.get("also_no_target"))
        qs = (
            AdmissionChangeRequest.objects.filter(
                change_type="exemption",
                accounts_status__in=("billed", "confirmed"),
            )
            .select_related(
                "admitted_student",
                "admitted_student__application",
                "admitted_student__admitted_program",
                "admitted_student__programme_enrollment",
            )
            .order_by("id")
        )

        rows_missing_apply = []
        rows_no_target = []

        for cr in qs:
            student = cr.admitted_student
            if student is None:
                continue
            try:
                spe = student.programme_enrollment
            except Exception:
                spe = None

            name = ""
            try:
                name = student.application.full_name or ""
            except Exception:
                name = getattr(student, "full_name", "") or ""

            pay = (student.student_id or student.schoolpay_code or "").strip()
            reg = (student.reg_no or "").strip()
            prog = ""
            if student.admitted_program_id:
                prog = student.admitted_program.name or student.admitted_program.code or ""

            spe_y = spe.current_year_of_study if spe else None
            spe_t = spe.current_term_number if spe else None
            entry_y = spe.entry_year_of_study if spe else None
            entry_t = spe.entry_term_number if spe else None

            base = {
                "cr": cr.id,
                "name": name,
                "reg": reg,
                "pay": pay,
                "prog": prog,
                "accounts": cr.accounts_status,
                "target": (cr.exemption_promotion_year, cr.exemption_promotion_term),
                "from": (cr.exemption_promotion_from_year, cr.exemption_promotion_from_term),
                "spe": (spe_y, spe_t),
                "entry": (entry_y, entry_t),
            }

            if not exemption_promotion_proposed(cr):
                if also_no_target:
                    rows_no_target.append(base)
                continue

            if exemption_promotion_applied(cr):
                continue
            rows_missing_apply.append(base)

        self.stdout.write(
            self.style.NOTICE(
                f"Billed/confirmed but SPE not at promotion target: {len(rows_missing_apply)}"
            )
        )
        self.stdout.write(
            "CR\tName\tReg\tPaycode\tProgramme\tAccounts\tTarget\tSPE\tEntry\tFrom"
        )
        for r in rows_missing_apply:
            ty, tt = r["target"]
            sy, st = r["spe"]
            ey, et = r["entry"]
            fy, ft = r["from"]
            self.stdout.write(
                f"{r['cr']}\t{r['name']}\t{r['reg']}\t{r['pay']}\t{r['prog']}\t"
                f"{r['accounts']}\tY{ty}T{tt}\t"
                f"{'Y'+str(sy)+'T'+str(st) if sy is not None else 'NO_SPE'}\t"
                f"{'Y'+str(ey)+'T'+str(et) if ey is not None else '—'}\t"
                f"{'Y'+str(fy)+'T'+str(ft) if fy is not None else '—'}"
            )

        if also_no_target:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"Billed/confirmed with NO promotion target stored: {len(rows_no_target)}"
                )
            )
            for r in rows_no_target:
                sy, st = r["spe"]
                self.stdout.write(
                    f"{r['cr']}\t{r['name']}\t{r['reg']}\t{r['pay']}\t"
                    f"{r['accounts']}\tSPE="
                    f"{'Y'+str(sy)+'T'+str(st) if sy is not None else 'NO_SPE'}"
                )

        self.stdout.write("")
        self.stdout.write(
            "To promote one: "
            "python manage.py confirm_exemption_promotion --request-id CR --year Y --term T"
        )
