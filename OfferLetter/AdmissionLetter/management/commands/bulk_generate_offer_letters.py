"""Queue Celery bulk offer-letter generation from the shell."""
import uuid

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from OfferLetter.AdmissionLetter.tasks import bulk_generate_offer_letters_task, save_bulk_offer_letter_job
from OfferLetter.AdmissionLetter.views import _eligible_offer_letter_application_ids
from OfferLetter.AdmissionLetter.utils.offer_generation import resolve_verify_base


class Command(BaseCommand):
    help = "Queue bulk offer-letter generation on main (Celery background job)."

    def add_arguments(self, parser):
        parser.add_argument("--admitted-batch-id", type=int, default=None)
        parser.add_argument("--program-id", type=int, default=None)
        parser.add_argument("--include-existing", action="store_true")
        parser.add_argument("--send-email", action="store_true")
        parser.add_argument("--user-id", type=int, default=None)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        only_missing = not options["include_existing"]
        application_ids = _eligible_offer_letter_application_ids(
            only_missing_pdf=only_missing,
            admitted_batch_id=options["admitted_batch_id"],
            program_id=options["program_id"],
        )
        self.stdout.write(f"Eligible applications: {len(application_ids)}")
        if options["dry_run"] or not application_ids:
            return

        User = get_user_model()
        user_id = options["user_id"]
        if user_id is None:
            admin = User.objects.filter(is_superuser=True).order_by("id").first()
            if not admin:
                self.stderr.write(self.style.ERROR("No superuser found. Pass --user-id."))
                return
            user_id = admin.id

        job_id = uuid.uuid4().hex
        save_bulk_offer_letter_job(
            job_id,
            {
                "job_id": job_id,
                "status": "queued",
                "total": len(application_ids),
                "processed": 0,
                "generated": 0,
                "reused": 0,
                "failed": 0,
                "errors": [],
                "source": "management_command",
            },
        )
        bulk_generate_offer_letters_task.delay(
            job_id,
            application_ids,
            user_id,
            send_email=options["send_email"],
            skip_if_pdf_exists=only_missing,
            verify_base=resolve_verify_base(),
        )
        self.stdout.write(self.style.SUCCESS(f"Queued job {job_id} for {len(application_ids)} application(s)."))
