"""Remove mis-targeted student admission notices from staff/lecturer accounts.

Historically, admit flow called:
  celery_application_notification.delay(request.user.id, "Admission Successful", ...)
so the *staff member who admitted* got "You have been admitted…".
"""
from django.core.management.base import BaseCommand
from django.db.models import Q

from admissions.models import PortalNotification


class Command(BaseCommand):
    help = "Delete student-facing admission notifications wrongly assigned to staff/lecturers."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Count matches without deleting.",
        )

    def handle(self, *args, **options):
        qs = PortalNotification.objects.filter(
            Q(recipient__is_staff=True) | Q(recipient__is_lecturer=True)
        ).filter(
            Q(title__icontains="Admission Successful")
            | Q(title__icontains="Application Submitted")
            | Q(message__icontains="you have been admitted")
            | Q(message__icontains="Your application was successfully submitted")
        )
        # Keep notices for true dual student accounts on the student portal;
        # only remove when recipient is staff/lecturer and NOT a student-only user.
        qs = qs.exclude(recipient__is_student=True, recipient__is_staff=False, recipient__is_lecturer=False)

        count = qs.count()
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING(f"Would delete {count} notification(s)."))
            for n in qs.select_related("recipient")[:50]:
                self.stdout.write(
                    f"  #{n.id} {n.recipient.email}: {n.title} — {(n.message or '')[:60]}"
                )
            return

        deleted, _ = qs.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} notification row(s)."))
