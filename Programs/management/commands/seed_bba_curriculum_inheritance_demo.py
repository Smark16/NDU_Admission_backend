"""
Idempotent demo data for BBA Main vs Kampala curriculum inheritance.

  python manage.py seed_bba_curriculum_inheritance_demo
  python manage.py seed_bba_curriculum_inheritance_demo --fork-kampala
  python manage.py seed_bba_curriculum_inheritance_demo --reset
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

TAG = "[BBA-INHERIT-DEMO]"
MASTER_CODE = "BBA-INH-MAIN"
KLA_CODE = "BBA-INH-KLA"
VERSION_NAME = "2026 default"


class Command(BaseCommand):
    help = "Seed BBA Main/Kampala curriculum inheritance demo data (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fork-kampala",
            action="store_true",
            help="After seeding inheritance, fork Kampala into a local editable curriculum copy.",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Remove demo programmes and their owned curriculum rows.",
        )

    def handle(self, *args, **options):
        if options["reset"]:
            self._reset()
            return

        with transaction.atomic():
            main_campus, kla_campus = self._campuses()
            faculty, level = self._faculty_and_level(main_campus, kla_campus)
            master = self._program(
                code=MASTER_CODE,
                name=f"{TAG} BBA - Main Campus",
                short_form="BBA Main",
                faculty=faculty,
                level=level,
                campuses=[main_campus],
                mode="master",
                source=None,
            )
            kampala = self._program(
                code=KLA_CODE,
                name=f"{TAG} BBA - Kampala Campus",
                short_form="BBA Kampala",
                faculty=faculty,
                level=level,
                campuses=[kla_campus],
                mode="inherited",
                source=master,
            )
            catalog = self._catalog_courses()
            version = self._master_curriculum(master, catalog)
            self._program_batch(master, "Main Year 1", version, "Main 2026/2027")
            self._program_batch(kampala, "Kampala Year 1", version, "Kampala 2026/2027")

            if options["fork_kampala"]:
                from Programs.curriculum_inheritance import fork_curriculum_version

                forked = fork_curriculum_version(kampala, version.id)
                kampala.refresh_from_db()
                self.stdout.write(
                    self.style.WARNING(
                        f"Forked Kampala curriculum to local version id={forked.id} "
                        f"(programme mode={kampala.curriculum_mode})."
                    )
                )

        self._print_summary(master, kampala, options["fork_kampala"])

    def _reset(self):
        from Programs.models import Program

        qs = Program.objects.filter(code__in=[MASTER_CODE, KLA_CODE])
        count = qs.count()
        if not count:
            self.stdout.write("No demo programmes to remove.")
            return
        qs.delete()
        self.stdout.write(self.style.SUCCESS(f"Removed {count} demo programme(s) and owned curriculum data."))

    def _campuses(self):
        from accounts.models import Campus

        main, _ = Campus.objects.get_or_create(
            code="MAIN",
            defaults={
                "name": "Main Campus",
                "address": "Demo Main Campus",
                "email": "main.demo@ndu.test",
            },
        )
        kla, _ = Campus.objects.get_or_create(
            code="KLA",
            defaults={
                "name": "Kampala Campus",
                "address": "Demo Kampala Campus",
                "email": "kampala.demo@ndu.test",
            },
        )
        return main, kla

    def _faculty_and_level(self, main_campus, kla_campus):
        from admissions.models import AcademicLevel, Faculty

        level, _ = AcademicLevel.objects.get_or_create(
            name="Undergraduate",
            defaults={"is_active": True},
        )
        faculty, _ = Faculty.objects.get_or_create(
            code="FBM",
            defaults={"name": "Faculty of Business and Management", "is_active": True},
        )
        faculty.campuses.add(main_campus, kla_campus)
        return faculty, level

    def _program(self, *, code, name, short_form, faculty, level, campuses, mode, source):
        from Programs.models import Program

        program, created = Program.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "short_form": short_form,
                "faculty": faculty,
                "academic_level": level,
                "min_years": 3,
                "max_years": 4,
                "calendar_type": "semester",
                "minimum_graduation_load": Decimal("120.00"),
                "is_active": True,
                "curriculum_mode": Program.CURRICULUM_MODE_MASTER,
            },
        )
        program.campuses.set(campuses)
        if created:
            self.stdout.write(self.style.SUCCESS(f"Created programme {program.code} (id={program.id})"))
        else:
            self.stdout.write(f"Reusing programme {program.code} (id={program.id})")

        if mode == "inherited" and source:
            from Programs.curriculum_inheritance import link_program_to_curriculum_source

            link_program_to_curriculum_source(program, source)
            program.refresh_from_db()
        elif mode == "master":
            program.curriculum_source_program = None
            program.curriculum_mode = Program.CURRICULUM_MODE_MASTER
            program.save(update_fields=["curriculum_source_program", "curriculum_mode", "updated_at"])
        return program

    def _catalog_courses(self):
        from Programs.models import CourseCatalogUnit

        rows = [
            ("DEMO-BBA101", "Principles of Management", 3),
            ("DEMO-BBA102", "Business Communication", 3),
            ("DEMO-BBA103", "Financial Accounting I", 3),
            ("DEMO-BBA201", "Organizational Behaviour", 3),
            ("DEMO-BBA202", "Business Statistics", 3),
            ("DEMO-BBA203", "Marketing Principles", 3),
        ]
        out = []
        for code, title, credits in rows:
            course, _ = CourseCatalogUnit.objects.get_or_create(
                code=code,
                defaults={
                    "title": f"{TAG} {title}",
                    "credit_units": Decimal(str(credits)),
                    "is_active": True,
                },
            )
            out.append(course)
        return out

    def _master_curriculum(self, program, catalog):
        from Programs.models import ProgramCurriculumLine, ProgramCurriculumVersion

        version, _ = ProgramCurriculumVersion.objects.get_or_create(
            program=program,
            name=VERSION_NAME,
            defaults={
                "description": f"{TAG} Master BBA map used by Kampala inheritance demo.",
                "is_active": True,
                "is_default": True,
            },
        )
        ProgramCurriculumVersion.objects.filter(program=program).exclude(pk=version.pk).update(
            is_default=False,
        )
        if not version.is_default:
            version.is_default = True
            version.save(update_fields=["is_default", "updated_at"])

        slots = [
            (1, 1),
            (1, 1),
            (1, 2),
            (2, 1),
            (2, 1),
            (2, 2),
        ]
        for idx, (course, (year, term)) in enumerate(zip(catalog, slots), start=1):
            ProgramCurriculumLine.objects.get_or_create(
                program=program,
                curriculum_version=version,
                catalog_course=course,
                year_of_study=year,
                term_number=term,
                defaults={
                    "course_type": "mandatory",
                    "sort_order": idx,
                    "is_active": True,
                },
            )
        self.stdout.write(
            f"Master curriculum version id={version.id} with {version.lines.count()} line(s)."
        )
        return version

    def _program_batch(self, program, batch_name, version, academic_year):
        from Programs.models import ProgramBatch, Semester

        batch, _ = ProgramBatch.objects.get_or_create(
            program=program,
            name=f"{TAG} {batch_name}",
            defaults={
                "academic_year": academic_year,
                "start_date": date.today(),
                "is_active": True,
                "curriculum_version": version,
            },
        )
        if batch.curriculum_version_id != version.id:
            batch.curriculum_version = version
            batch.save(update_fields=["curriculum_version", "updated_at"])

        Semester.objects.get_or_create(
            program_batch=batch,
            order=1,
            defaults={
                "name": "Semester 1 (Y1T1)",
                "year_of_study": 1,
                "term_number": 1,
                "start_date": date.today(),
                "is_active": True,
            },
        )
        self.stdout.write(f"Programme batch id={batch.id} for {program.code}.")

    def _print_summary(self, master, kampala, forked: bool):
        from Programs.curriculum_inheritance import curriculum_context_payload

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("BBA inheritance demo ready"))
        self.stdout.write(f"  Master programme:  {master.name} (id={master.id}, code={master.code})")
        self.stdout.write(f"  Kampala programme: {kampala.name} (id={kampala.id}, code={kampala.code})")
        self.stdout.write(f"  Master context:    {curriculum_context_payload(master)}")
        self.stdout.write(f"  Kampala context:   {curriculum_context_payload(kampala)}")
        self.stdout.write("")
        self.stdout.write("In the portal:")
        self.stdout.write("  1. Faculty > Programmes > open curriculum on BBA Main (editable master map).")
        self.stdout.write("  2. Open curriculum on BBA Kampala (same map, inherited read-only).")
        self.stdout.write("  3. Edit programme BBA Kampala > Curriculum Source shows the master link.")
        self.stdout.write("  4. Academic batches differ per campus row (Main Year 1 vs Kampala Year 1).")
        if forked:
            self.stdout.write("  5. Kampala was forked; it owns a local copy and no longer auto-follows Main.")
        self.stdout.write("")
        self.stdout.write("Remove demo data: python manage.py seed_bba_curriculum_inheritance_demo --reset")
