from django.core.management.base import BaseCommand

from admissions.models import (
    Application,
    ApplicationProgramChoice
)


class Command(BaseCommand):

    help = "Migrates old programs M2M into ApplicationProgramChoice"

    def handle(self, *args, **kwargs):

        migrated = 0
        skipped = 0

        applications = (
            Application.objects
            .prefetch_related("programs")
        )

        for app in applications:

            # already migrated
            if app.program_choices.exists():
                skipped += 1
                continue

            old_programs = list(app.programs.all())

            if not old_programs:
                continue

            bulk_choices = []

            for index, program in enumerate(old_programs, start=1):

                bulk_choices.append(
                    ApplicationProgramChoice(
                        application=app,
                        program=program,
                        choice_order=index
                    )
                )

            ApplicationProgramChoice.objects.bulk_create(
                bulk_choices
            )

            migrated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Migration completed. "
                f"Migrated={migrated}, Skipped={skipped}"
            )
        )