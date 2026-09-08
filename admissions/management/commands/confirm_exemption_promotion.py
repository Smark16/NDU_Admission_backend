"""
Confirm (and apply) exemption Year/Term promotion for a change request.

Use when Accounts already billed but HOD never confirmed promotion, or to
retarget after an earlier apply (e.g. Y1T2 → Y2T1).

Usage:
  python manage.py confirm_exemption_promotion --request-id 395 --year 2 --term 1
  python manage.py confirm_exemption_promotion --request-id 395 --year 2 --term 1 --dry-run
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from admissions.exemption_services import (
    apply_exemption_promotion_for_billed,
    apply_stored_exemption_promotion,
    exemption_promotion_applied,
    exemption_promotion_proposed,
    exemption_ready_for_hod_promotion,
    propose_exemption_promotion,
    validate_advance_position,
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
        self.stdout.write(
            f"  Stored target Y{req.exemption_promotion_year}T{req.exemption_promotion_term} "
            f"→ requested Y{to_year}T{to_term}"
        )

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("[DRY-RUN] No changes made."))
            return

        User = get_user_model()
        actor = (
            req.exemption_promotion_by
            or req.reviewed_by
            or User.objects.filter(is_superuser=True).order_by("id").first()
        )

        already_at = (
            int(pe.current_year_of_study or 0),
            int(pe.current_term_number or 0),
        ) == (to_year, to_term)
        if already_at:
            if (
                req.exemption_promotion_year != to_year
                or req.exemption_promotion_term != to_term
            ):
                req.exemption_promotion_year = to_year
                req.exemption_promotion_term = to_term
                req.exemption_promotion_at = timezone.now()
                req.save(
                    update_fields=[
                        "exemption_promotion_year",
                        "exemption_promotion_term",
                        "exemption_promotion_at",
                        "updated_at",
                    ]
                )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Already at requested position — SPE Y{to_year}T{to_term}."
                )
            )
            return

        try:
            if req.accounts_status in ("billed", "confirmed"):
                result = apply_exemption_promotion_for_billed(
                    req,
                    decided_by=actor,
                    to_year=to_year,
                    to_term=to_term,
                )
                self.stdout.write(f"  billed apply result: {result}")
            elif not exemption_promotion_proposed(req):
                if req.hod_status != "approved":
                    raise CommandError("HOD must approve papers before promotion.")
                if not exemption_ready_for_hod_promotion(req):
                    raise CommandError(
                        "Request is not ready for promotion "
                        "(need HOD-approved papers and no existing promotion target)."
                    )
                result = propose_exemption_promotion(
                    req, to_year=to_year, to_term=to_term, decided_by=actor
                )
                self.stdout.write(f"  propose result: {result}")
            else:
                # Pending Accounts but retarget stored year/term.
                validate_advance_position(student, to_year=to_year, to_term=to_term)
                req.exemption_promotion_from_year = int(pe.current_year_of_study or 1)
                req.exemption_promotion_from_term = int(pe.current_term_number or 1)
                req.exemption_promotion_year = to_year
                req.exemption_promotion_term = to_term
                req.exemption_promotion_by = actor
                req.exemption_promotion_at = timezone.now()
                req.save(
                    update_fields=[
                        "exemption_promotion_year",
                        "exemption_promotion_term",
                        "exemption_promotion_from_year",
                        "exemption_promotion_from_term",
                        "exemption_promotion_by",
                        "exemption_promotion_at",
                        "updated_at",
                    ]
                )
                self.stdout.write(
                    "  Target updated; SPE will move when Accounts bills "
                    f"(or run again after billing). Stored Y{to_year}T{to_term}."
                )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        req.refresh_from_db()
        pe.refresh_from_db()
        if (
            req.accounts_status in ("billed", "confirmed")
            and not exemption_promotion_applied(req)
        ):
            applied = apply_stored_exemption_promotion(req, decided_by=actor)
            self.stdout.write(f"  apply_stored: {applied}")
            pe.refresh_from_db()

        self.stdout.write(
            self.style.SUCCESS(
                f"Done — SPE Y{pe.current_year_of_study}T{pe.current_term_number} "
                f"entry Y{pe.entry_year_of_study}T{pe.entry_term_number}. "
                f"Target Y{req.exemption_promotion_year}T{req.exemption_promotion_term}."
            )
        )
