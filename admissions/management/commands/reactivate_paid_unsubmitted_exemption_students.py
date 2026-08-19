"""
Re-activate student portal logins for people who paid the UGX 50,000
exemption form fee and can still submit (never submitted, or returned/rejected).

The paid fee is kept.

Usage:
  python manage.py reactivate_paid_unsubmitted_exemption_students --dry-run
  python manage.py reactivate_paid_unsubmitted_exemption_students --inactive-only --dry-run
  python manage.py reactivate_paid_unsubmitted_exemption_students --reg-no 26/2/328/W/2127
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from admissions.exemption_services import (
    exemption_application_attempt_state,
    exemption_form_fee_report,
    student_has_paid_exemption_form_fee,
)
from admissions.models import AdmittedStudent, AdmissionChangeRequest, StudentPortalAccountAction
from admissions.student_accounts import ensure_student_portal_account

REASON = (
    "Reactivated so the student can submit course exemption after paying the form fee."
)


def _find_student(reg: str) -> AdmittedStudent | None:
    reg = (reg or "").strip()
    if not reg:
        return None
    return (
        AdmittedStudent.objects.filter(Q(reg_no__iexact=reg) | Q(student_id__iexact=reg))
        .select_related("student_user", "application")
        .first()
    )


def _can_still_submit(row: dict) -> bool:
    status = (row.get("change_request_status") or "").strip().lower()
    if status in ("pending", "approved"):
        return False
    return True


class Command(BaseCommand):
    help = (
        "Activate portal accounts for students who paid the exemption form fee "
        "and can still submit the form."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--reg-no",
            type=str,
            default="",
            help="Limit to one registration number or student ID, and explain if skipped.",
        )
        parser.add_argument(
            "--inactive-only",
            action="store_true",
            help="Only students whose portal login is currently inactive.",
        )
        parser.add_argument(
            "--never-submitted-only",
            action="store_true",
            help="Old filter: paid and never created an exemption request.",
        )

    def handle(self, *args, **options):
        dry = options["dry_run"]
        reg = (options.get("reg_no") or "").strip()
        inactive_only = options.get("inactive_only")
        never_only = options.get("never_submitted_only")

        if reg:
            self._explain_student(reg)

        status_filter = "paid_unsubmitted" if never_only else "completed"
        rows = exemption_form_fee_report(status_filter)
        seen = set()
        students = []
        for row in rows:
            pk = row.get("student_pk")
            if not pk or pk in seen:
                continue
            if not never_only and not _can_still_submit(row):
                continue
            if reg:
                target = _find_student(reg)
                if not target or target.pk != pk:
                    continue
            seen.add(pk)
            students.append(row)

        if inactive_only:
            filtered = []
            for row in students:
                st = AdmittedStudent.objects.filter(pk=row["student_pk"]).select_related("student_user").first()
                user = getattr(st, "student_user", None) if st else None
                if user is None or not user.is_active:
                    filtered.append(row)
            students = filtered

        if not students:
            self.stdout.write(self.style.WARNING("No matching paid students who can still submit."))
            if not never_only:
                self.stdout.write(
                    "Tip: add --never-submitted-only for the old list, "
                    "or --inactive-only for paid students whose login is off."
                )
            return

        self.stdout.write(
            f"{'[DRY-RUN] ' if dry else ''}{len(students)} student(s) paid and can still submit:"
        )

        activated = 0
        already = 0
        provisioned = 0
        missing = 0

        for row in students:
            student = (
                AdmittedStudent.objects.filter(pk=row["student_pk"])
                .select_related("student_user", "application")
                .first()
            )
            if student is None:
                missing += 1
                self.stdout.write(self.style.WARNING(f"  skip missing pk={row['student_pk']}"))
                continue

            user = student.student_user
            name = row.get("student_name") or ""
            reg_no = row.get("reg_no") or student.reg_no or ""
            cr = row.get("change_request_status") or "not submitted"
            was_inactive = bool(user and not user.is_active)
            had_user = bool(user)

            if dry:
                state = "no login" if not user else ("inactive" if was_inactive else "already active")
                self.stdout.write(f"  {reg_no} {name} — {state}; exemption={cr} (fee kept)")
                continue

            with transaction.atomic():
                if user is None:
                    user, created = ensure_student_portal_account(student)
                    student.refresh_from_db(fields=["student_user_id"])
                    user = student.student_user or user
                    if created:
                        provisioned += 1
                    if user is None:
                        missing += 1
                        self.stdout.write(
                            self.style.WARNING(f"  {reg_no} {name} — could not create portal login")
                        )
                        continue

                fields = []
                if not user.is_active:
                    user.is_active = True
                    fields.append("is_active")
                if not user.is_student:
                    user.is_student = True
                    fields.append("is_student")
                if fields:
                    user.save(update_fields=fields)
                    StudentPortalAccountAction.objects.create(
                        student=student,
                        portal_user=user,
                        action=StudentPortalAccountAction.ACTION_ACTIVATE,
                        reason=REASON,
                        performed_by=None,
                    )
                    activated += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  {reg_no} {name} — portal activated; exemption={cr} (fee kept)"
                        )
                    )
                else:
                    already += 1
                    extra = " (new login created)" if not had_user else ""
                    self.stdout.write(
                        f"  {reg_no} {name} — already active{extra}; exemption={cr} (fee kept)"
                    )

        if dry:
            self.stdout.write("Dry run — no accounts were changed. Re-run without --dry-run to activate.")
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Activated {activated}, already active {already}, "
                f"new logins {provisioned}, skipped {missing}."
            )
        )
        self.stdout.write(
            "Students keep the paid 50k form fee. They should log in and submit Course Exemption."
        )

    def _explain_student(self, reg: str) -> None:
        student = _find_student(reg)
        if student is None:
            self.stdout.write(self.style.WARNING(f"{reg}: student record not found."))
            return
        name = ""
        try:
            name = student.full_name or ""
        except Exception:
            pass
        user = student.student_user
        login = "no portal user"
        if user:
            login = f"portal {user.username} {'ACTIVE' if user.is_active else 'INACTIVE'}"
        paid = student_has_paid_exemption_form_fee(student)
        latest = (
            AdmissionChangeRequest.objects.filter(
                admitted_student=student, change_type="exemption"
            )
            .order_by("-created_at")
            .first()
        )
        cr = "none"
        if latest:
            cr = f"#{latest.id} {latest.status}"
        attempts = exemption_application_attempt_state(student)
        self.stdout.write(
            f"{student.reg_no or student.student_id} {name}: {login}; "
            f"prompt-paid={paid}; latest exemption={cr}; "
            f"can_submit={attempts.get('can_submit')} {attempts.get('detail') or ''}"
        )
