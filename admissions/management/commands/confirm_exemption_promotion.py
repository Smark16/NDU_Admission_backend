"""
Confirm (and apply) exemption Year/Term promotion for a change request.

Use when Accounts already billed but HOD never confirmed promotion, or to
re-run apply after a late confirmation.

Usage:
  python manage.py confirm_exemption_promotion --request-id 395 --year 2 --term 1
  python manage.py confirm_exemption_promotion --request-id 395 --year 2 --term 1 --dry-run
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from admissions.exemption_services import (
    apply_stored_exemption_promotion,
    exemption_promotion_applied,
    exemption_promotion_proposed,
    exemption_ready_for_hod_promotion,
    propose_exemption_promotion,
)
from admissions.models import AdmissionChangeRequest


class Command(BaseCommand):
    help = "Store and apply exemption SPE promotion (e.g. Y1T1 → Y2T1)."

    def add_arguments(self, parser):
        parser.add_argument("--request-id", type=int, required=True)
        parser.add_argument("--year", type=int, required=True)
        parser.add_argument("--term", type=int, required=True)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        req = (
            AdmissionChangeRequest.objects.select_related(
                "admitted_student",
                "admitted_student__programme_enrollment",
            )
            .filter(pk=options["request_id"], change_type="exemption")
            .first()
        )
        if req is None:
            raise CommandError(f"Exemption request #{options['request_id']} not found.")

        student = req.admitted_student
        pe = getattr(student, "programme_enrollment", None)
        if pe is None:
            raise CommandError("Student has no programme enrollment.")

        to_year = int(options["year"])
        to_term = int(options["term"])
        self.stdout.write(
            f"CR #{req.id} {student.full_name} ({student.student_id}) "
            f"accounts={req.accounts_status} hod={req.hod_status}"
        )
        self.stdout.write(
            f"  SPE now Y{pe.current_year_of_study}T{pe.current_term_number} "
            f"entry Y{pe.entry_year_of_study}T{pe.entry_term_number}"
        )
        self.stdout.write(f"  Target Y{to_year}T{to_term}")

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("[DRY-RUN] No changes made."))
            return

        User = get_user_model()
        actor = (
            req.exemption_promotion_by
            or req.reviewed_by
            or User.objects.filter(is_superuser=True).order_by("id").first()
        )

        if exemption_promotion_applied(req):
            pe.refresh_from_db()
            self.stdout.write(
                self.style.SUCCESS(
                    f"Already applied — SPE Y{pe.current_year_of_study}T{pe.current_term_number}."
                )
            )
            return

        if not exemption_promotion_proposed(req):
            if req.hod_status != "approved":
                raise CommandError("HOD must approve papers before promotion.")
            if not exemption_ready_for_hod_promotion(req):
                raise CommandError(
                    "Request is not ready for promotion "
                    "(need HOD-approved papers and no existing promotion target)."
                )
            try:
                result = propose_exemption_promotion(
                    req, to_year=to_year, to_term=to_term, decided_by=actor
                )
            except ValueError as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(f"  propose result: {result}")
            req.refresh_from_db()

        if not exemption_promotion_applied(req):
            applied = apply_stored_exemption_promotion(req, decided_by=actor)
            self.stdout.write(f"  apply_stored: {applied}")

        pe.refresh_from_db()
        self.stdout.write(
            self.style.SUCCESS(
                f"Done — SPE Y{pe.current_year_of_study}T{pe.current_term_number} "
                f"entry Y{pe.entry_year_of_study}T{pe.entry_term_number}. "
                f"Student should see Year {pe.current_year_of_study} "
                f"Semester {pe.current_term_number} tuition and course units."
            )
        )
