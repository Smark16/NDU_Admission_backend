"""
Seed local timetable scenarios covering Ndejje-style patterns.

Idempotent (get_or_create / keyed notes). Safe for local/dev DBs.

Scenarios created:
  1. Day Main — weekday lecture bands (Mon–Fri), on-campus + venue
  2. Day KLA — second campus venue / room_label
  3. Weekend — Fri / Sat / Sun recurring
  4. Online Sunday (delivery_mode=online)
  5. Hybrid mid-week
  6. Cross-cutting Shared Teaching (Ethics across BIT + BCS)
  7. Engineering streams — TeachingSection I & II, same EMT code, parallel slots
  8. Practical + tutorial session types
  9. Unpublished draft session
 10. One-off dated session
 11. Community-hour blocker note slot (Wed 12–13)
 12. Catalog is_cross_cutting on Ethics / Comm Skills

Usage:
  python manage.py seed_timetable_scenarios
  python manage.py seed_timetable_scenarios --purge   # remove [TT-TEST] rows only
"""
from __future__ import annotations

from datetime import date, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

User = get_user_model()

TAG = "[TT-TEST]"
AY = "2026/2027"
SEM_START = date(2026, 8, 17)
SEM_END = date(2026, 12, 18)


class Command(BaseCommand):
    help = "Seed comprehensive [TT-TEST] timetable scenarios for local QA."

    def add_arguments(self, parser):
        parser.add_argument(
            "--purge",
            action="store_true",
            help="Delete [TT-TEST] timetable seed data (sessions, offerings, batches, etc.).",
        )

    def handle(self, *args, **options):
        if options["purge"]:
            self._purge()
            return

        self._ensure_section_lecturer_table()

        with transaction.atomic():
            campus_main, campus_kla = self._campuses()
            faculty_sci, faculty_eng = self._faculties(campus_main, campus_kla)
            level = self._academic_level()
            lecturers = self._lecturers(campus_main)

            cat = self._catalog()
            prog_bit, prog_bcs, prog_be = self._programmes(
                level, faculty_sci, faculty_eng, campus_main, campus_kla
            )
            self._curriculum(prog_bit, prog_bcs, prog_be, cat)

            batch_bit_day, sem_bit_day = self._batch_semester(
                prog_bit, "BIT-DAY-MAIN", campus_main, "Day"
            )
            batch_bcs_day, sem_bcs_day = self._batch_semester(
                prog_bcs, "BCS-DAY-MAIN", campus_main, "Day"
            )
            batch_bit_wkd, sem_bit_wkd = self._batch_semester(
                prog_bit, "BIT-WKD-KLA", campus_kla, "Weekend"
            )
            batch_be, sem_be = self._batch_semester(
                prog_be, "BE-CIVIL-DAY", campus_main, "Day"
            )

            venues = self._venues(campus_main, campus_kla)

            cu_bit = self._course_units(batch_bit_day, sem_bit_day, cat, ("PROG", "ETHICS", "COMM", "NET"))
            cu_bcs = self._course_units(batch_bcs_day, sem_bcs_day, cat, ("PROG", "ETHICS", "COMM", "DB"))
            cu_wkd = self._course_units(batch_bit_wkd, sem_bit_wkd, cat, ("PROG", "ETHICS", "COMM", "NET"))
            cu_be = self._course_units(batch_be, sem_be, cat, ("EMT", "DRAW", "SURVEY", "SURVEY_P"))

            for cu in list(cu_bit.values()) + list(cu_bcs.values()) + list(cu_wkd.values()) + list(cu_be.values()):
                if cu.lecturers.count() == 0:
                    cu.lecturers.add(lecturers[0])

            # Shared teaching: Ethics on BIT Day + BCS Day (cross-cutting)
            sto = self._shared_ethics(cu_bit["ETHICS"], cu_bcs["ETHICS"], lecturers[1])

            # Engineering streams
            sec_i, sec_ii = self._streams(batch_be)
            self._section_lecturers(cu_be["EMT"], sec_i, sec_ii, lecturers)

            # Wipe prior TT-TEST sessions on these units then recreate (idempotent shape)
            from Programs.models import TimetableSession

            unit_ids = [u.id for u in list(cu_bit.values()) + list(cu_bcs.values()) + list(cu_wkd.values()) + list(cu_be.values())]
            TimetableSession.objects.filter(
                course_unit_id__in=unit_ids, notes__startswith=TAG
            ).delete()

            n = 0
            n += self._seed_day_main(cu_bit, cu_bcs, venues, sto, lecturers)
            n += self._seed_weekend(cu_wkd, venues)
            n += self._seed_engineering_streams(cu_be, sec_i, sec_ii, venues)
            n += self._seed_edge_cases(cu_bit, venues)

        self.stdout.write(self.style.SUCCESS(
            f"\n{TAG} timetable seed complete — {n} sessions.\n"
            f"Open Batches for programmes whose names start with {TAG}.\n"
            f"Shared Ethics: STO linked on BIT+BCS Day. Streams I/II on BE Civil.\n"
            f"Purge later: python manage.py seed_timetable_scenarios --purge"
        ))

    def _ensure_section_lecturer_table(self):
        """Local DBs sometimes have migration 0025 recorded without the table."""
        from django.db import connection
        from Programs.models import CourseUnitSectionLecturer
        from Programs.section_lecturers import section_lecturer_table_exists

        if section_lecturer_table_exists():
            return
        with connection.schema_editor() as schema_editor:
            schema_editor.create_model(CourseUnitSectionLecturer)
        self.stdout.write(self.style.WARNING(
            "Created missing Programs_courseunitsectionlecturer table (migration was recorded without it)."
        ))

    # ── purge ────────────────────────────────────────────────────────────────

    def _purge(self):
        from Programs.models import (
            CourseCatalogUnit,
            CourseUnit,
            Program,
            ProgramBatch,
            ProgramCurriculumLine,
            ProgramCurriculumVersion,
            SharedTeachingOffering,
            TeachingSection,
            TimetableSession,
            Venue,
        )
        from admissions.models import Faculty
        from Programs.section_lecturers import section_lecturer_table_exists

        with transaction.atomic():
            TimetableSession.objects.filter(notes__startswith=TAG).delete()
            TimetableSession.objects.filter(course_unit__name__startswith=TAG).delete()
            if section_lecturer_table_exists():
                from Programs.models import CourseUnitSectionLecturer

                CourseUnitSectionLecturer.objects.filter(
                    course_unit__name__startswith=TAG
                ).delete()
            SharedTeachingOffering.objects.filter(notes__startswith=TAG).delete()
            SharedTeachingOffering.objects.filter(name__startswith=TAG).delete()
            CourseUnit.objects.filter(name__startswith=TAG).delete()
            TeachingSection.objects.filter(name__startswith=TAG).delete()
            ProgramCurriculumLine.objects.filter(program__name__startswith=TAG).delete()
            ProgramCurriculumVersion.objects.filter(program__name__startswith=TAG).delete()
            ProgramBatch.objects.filter(name__startswith=TAG).delete()
            Program.objects.filter(name__startswith=TAG).delete()
            CourseCatalogUnit.objects.filter(title__startswith=TAG).delete()
            Venue.objects.filter(name__startswith=TAG).delete()
            Faculty.objects.filter(name__startswith=TAG).delete()
            User.objects.filter(email__endswith="@tt-test.ndu.local").delete()
        self.stdout.write(self.style.WARNING(f"Purged {TAG} timetable seed data."))

    # ── infra ────────────────────────────────────────────────────────────────

    def _campuses(self):
        from accounts.models import Campus

        main, _ = Campus.objects.get_or_create(
            code="TT-MAIN",
            defaults=dict(name=f"{TAG} Main Campus", address="Main, Ndejje", email="tt-main@ndu.test"),
        )
        kla, _ = Campus.objects.get_or_create(
            code="TT-KLA",
            defaults=dict(name=f"{TAG} Kampala Campus", address="Kampala", email="tt-kla@ndu.test"),
        )
        return main, kla

    def _faculties(self, campus_main, campus_kla):
        from admissions.models import Faculty

        sci, created = Faculty.objects.get_or_create(
            code="TT-SCI",
            defaults=dict(name=f"{TAG} Science & Computing", is_active=True),
        )
        if created:
            sci.campuses.add(campus_main, campus_kla)
        eng, created = Faculty.objects.get_or_create(
            code="TT-ENG",
            defaults=dict(name=f"{TAG} Engineering & Survey", is_active=True),
        )
        if created:
            eng.campuses.add(campus_main)
        return sci, eng

    def _academic_level(self):
        from admissions.models import AcademicLevel

        obj, _ = AcademicLevel.objects.get_or_create(
            name="Undergraduate", defaults=dict(is_active=True)
        )
        return obj

    def _lecturers(self, campus):
        specs = [
            ("tt.lec.prog", "Alex", "Luyima"),
            ("tt.lec.ethics", "Juliet", "Kansiime"),
            ("tt.lec.emt1", "Fostine", "Kalemba"),
            ("tt.lec.emt2", "Gabriel", "Ekodo"),
        ]
        out = []
        for username, first, last in specs:
            email = f"{username}@tt-test.ndu.local"
            user, created = User.objects.get_or_create(
                username=username,
                defaults=dict(
                    email=email,
                    first_name=first,
                    last_name=last,
                    is_staff=True,
                    is_lecturer=True,
                    primary_campus=campus,
                ),
            )
            if created:
                user.set_password("test1234")
                user.save()
                user.campuses.add(campus)
            out.append(user)
        return out

    def _catalog(self):
        from Programs.models import CourseCatalogUnit

        specs = [
            ("TT-PROG1107", "Principles of Programming", 3, False, ""),
            ("TT-ETHICS1101", "Christian Ethics I", 3, True, "Often shared across programmes; use Shared Teaching."),
            ("TT-COMM1102", "Communication Skills", 3, True, "Often shared; Education joiners."),
            ("TT-NET2106", "Computer Networks", 3, False, ""),
            ("TT-DB2103", "Database Management Systems", 3, False, ""),
            ("TT-EMT1101", "Engineering Mathematics I", 4, False, ""),
            ("TT-DRAW1103", "Engineering Drawing I", 4, False, ""),
            ("TT-GEO1101", "Principles of Surveying", 4, False, ""),
            ("TT-GEO1101P", "Principles of Surveying (Practical)", 0, False, ""),
        ]
        out = {}
        keys = ["PROG", "ETHICS", "COMM", "NET", "DB", "EMT", "DRAW", "SURVEY", "SURVEY_P"]
        for key, (code, title, cu, cross, note) in zip(keys, specs):
            obj, _ = CourseCatalogUnit.objects.get_or_create(
                code=code,
                defaults=dict(
                    title=f"{TAG} {title}",
                    credit_units=Decimal(str(cu)),
                    is_active=True,
                    is_cross_cutting=cross,
                    cross_cutting_note=note,
                ),
            )
            # Keep flags up to date on re-run
            if obj.is_cross_cutting != cross or (cross and not obj.cross_cutting_note):
                obj.is_cross_cutting = cross
                obj.cross_cutting_note = note
                obj.save(update_fields=["is_cross_cutting", "cross_cutting_note", "updated_at"])
            out[key] = obj
        return out

    def _programmes(self, level, faculty_sci, faculty_eng, campus_main, campus_kla):
        from Programs.models import Program

        def mk(code, name, short, faculty, campuses):
            obj, created = Program.objects.get_or_create(
                code=code,
                defaults=dict(
                    name=f"{TAG} {name}",
                    short_form=short,
                    faculty=faculty,
                    academic_level=level,
                    min_years=3,
                    max_years=4,
                    calendar_type="semester",
                    minimum_graduation_load=Decimal("120.00"),
                    is_active=True,
                ),
            )
            if created:
                obj.campuses.add(*campuses)
            return obj

        bit = mk("TT-BIT", "BIT Day/Weekend", "TT-BIT", faculty_sci, [campus_main, campus_kla])
        bcs = mk("TT-BCS", "BCS Day", "TT-BCS", faculty_sci, [campus_main])
        be = mk("TT-BE", "BE Civil Day Streams", "TT-BE", faculty_eng, [campus_main])
        return bit, bcs, be

    def _ensure_version(self, program):
        from Programs.models import ProgramCurriculumVersion, ensure_program_default_curriculum_version

        ensure_program_default_curriculum_version(program)
        return ProgramCurriculumVersion.objects.filter(program=program).order_by("-is_default", "id").first()

    def _curriculum(self, prog_bit, prog_bcs, prog_be, cat):
        from Programs.models import ProgramCurriculumLine

        mapping = {
            prog_bit: ["PROG", "ETHICS", "COMM", "NET"],
            prog_bcs: ["PROG", "ETHICS", "COMM", "DB"],
            prog_be: ["EMT", "DRAW", "SURVEY", "SURVEY_P"],
        }
        for program, keys in mapping.items():
            version = self._ensure_version(program)
            for i, key in enumerate(keys):
                ProgramCurriculumLine.objects.get_or_create(
                    program=program,
                    curriculum_version=version,
                    catalog_course=cat[key],
                    year_of_study=1,
                    term_number=1,
                    specialization="",
                    defaults=dict(
                        course_type="mandatory",
                        sort_order=i,
                        is_active=True,
                    ),
                )

    def _batch_semester(self, program, batch_code, campus, study_mode_label):
        from Programs.models import ProgramBatch, Semester

        batch, _ = ProgramBatch.objects.get_or_create(
            program=program,
            name=f"{TAG} {batch_code}",
            defaults=dict(
                academic_year=AY,
                start_date=SEM_START,
                end_date=SEM_END,
                is_active=True,
            ),
        )
        # study mode / campus often live on batch via related fields — keep name clear
        _ = campus, study_mode_label
        sem, _ = Semester.objects.get_or_create(
            program_batch=batch,
            name=f"{TAG} Y1S1 {batch_code}",
            defaults=dict(
                order=1,
                year_of_study=1,
                term_number=1,
                start_date=SEM_START,
                end_date=SEM_END,
                is_active=True,
            ),
        )
        return batch, sem

    def _venues(self, campus_main, campus_kla):
        from Programs.models import Venue

        specs = [
            ("TT-MAIN-L2R1", f"{TAG} Science Complex L2 R1", campus_main, "Science Complex"),
            ("TT-MAIN-LAB", f"{TAG} Main Lab-SC", campus_main, "Science Complex"),
            ("TT-MAIN-MINI", f"{TAG} Mini Lab Lady Irene", campus_main, "Lady Irene"),
            ("TT-KLA-D44", f"{TAG} Block D Level 4 Room 4", campus_kla, "Block D"),
        ]
        out = {}
        for code, name, campus, building in specs:
            v, _ = Venue.objects.get_or_create(
                campus=campus,
                code=code,
                defaults=dict(name=name, building=building, is_active=True, capacity=60),
            )
            out[code] = v
        return out

    def _course_units(self, batch, semester, cat, keys):
        from Programs.models import CourseUnit, ProgramCurriculumLine

        out = {}
        for key in keys:
            catalog = cat[key]
            line = ProgramCurriculumLine.objects.filter(
                program=batch.program, catalog_course=catalog, year_of_study=1, term_number=1
            ).first()
            cu, _ = CourseUnit.objects.get_or_create(
                semester=semester,
                code=catalog.code,
                defaults=dict(
                    name=catalog.title,
                    credit_units=catalog.credit_units,
                    catalog_unit=catalog,
                    curriculum_line=line,
                    program_batch=batch,
                    is_active=True,
                ),
            )
            out[key] = cu
        return out

    def _shared_ethics(self, cu_bit, cu_bcs, lecturer):
        from Programs.models import SharedTeachingOffering
        from Programs.shared_teaching import create_shared_offering_from_course_units

        if cu_bit.shared_teaching_offering_id and cu_bcs.shared_teaching_offering_id:
            if cu_bit.shared_teaching_offering_id == cu_bcs.shared_teaching_offering_id:
                return cu_bit.shared_teaching_offering

        # Clear prior links then recreate
        SharedTeachingOffering.objects.filter(notes__startswith=TAG).delete()
        offering = create_shared_offering_from_course_units(
            course_unit_ids=[cu_bit.id, cu_bcs.id],
            code="TT-ETHICS1101",
            name=f"{TAG} Christian Ethics I (shared)",
            academic_year_label=AY,
            year_of_study=1,
            term_number=1,
            notes=f"{TAG} cross-cutting shared sitting BIT+BCS Day",
            lecturer_ids=[lecturer.id],
            parent_course_unit_id=cu_bit.id,
        )
        return offering

    def _streams(self, batch):
        from Programs.models import TeachingSection

        # Default MAIN if required
        TeachingSection.objects.get_or_create(
            program_batch=batch,
            code="MAIN",
            defaults=dict(name=f"{TAG} Main", is_default=True, is_active=True, max_capacity=0),
        )
        sec_i, _ = TeachingSection.objects.get_or_create(
            program_batch=batch,
            code="I",
            defaults=dict(name=f"{TAG} Stream I", is_default=False, is_active=True, max_capacity=80),
        )
        sec_ii, _ = TeachingSection.objects.get_or_create(
            program_batch=batch,
            code="II",
            defaults=dict(name=f"{TAG} Stream II", is_default=False, is_active=True, max_capacity=80),
        )
        return sec_i, sec_ii

    def _section_lecturers(self, cu_emt, sec_i, sec_ii, lecturers):
        from Programs.models import CourseUnitSectionLecturer

        CourseUnitSectionLecturer.objects.get_or_create(
            course_unit=cu_emt,
            teaching_section=sec_i,
            lecturer=lecturers[2],
        )
        CourseUnitSectionLecturer.objects.get_or_create(
            course_unit=cu_emt,
            teaching_section=sec_ii,
            lecturer=lecturers[3],
        )

    # ── sessions ─────────────────────────────────────────────────────────────

    def _session(self, **kwargs):
        from Programs.models import TimetableSession

        notes = kwargs.get("notes") or ""
        if not notes.startswith(TAG):
            kwargs["notes"] = f"{TAG} {notes}".strip()
        kwargs.setdefault("start_date", SEM_START)
        kwargs.setdefault("end_date", SEM_END)
        kwargs.setdefault("is_active", True)
        kwargs.setdefault("is_published", True)
        kwargs.setdefault("session_type", "lecture")
        kwargs.setdefault("delivery_mode", "on_campus")
        return TimetableSession.objects.create(**kwargs)

    def _seed_day_main(self, cu_bit, cu_bcs, venues, sto, lecturers):
        n = 0
        lab = venues["TT-MAIN-LAB"]
        mini = venues["TT-MAIN-MINI"]
        l2 = venues["TT-MAIN-L2R1"]

        # BIT Programming Mon 08:30–11:30
        self._session(
            course_unit=cu_bit["PROG"],
            day_of_week=1,
            start_time=time(8, 30),
            end_time=time(11, 30),
            venue=lab,
            notes="Day Main morning band — lecture",
        )
        n += 1

        # Shared Ethics — slot only on parent (BIT); Tue 14:30–17:30
        self._session(
            course_unit=cu_bit["ETHICS"],
            day_of_week=2,
            start_time=time(14, 30),
            end_time=time(17, 30),
            venue=l2,
            notes=f"Cross-cutting shared Ethics (STO#{sto.id}) — parent slot only",
        )
        n += 1

        # Comm Skills hybrid Wed afternoon
        self._session(
            course_unit=cu_bit["COMM"],
            day_of_week=3,
            start_time=time(14, 30),
            end_time=time(17, 30),
            venue=mini,
            delivery_mode="hybrid",
            notes="Hybrid Communication Skills",
        )
        n += 1

        # Community hour blocker Wed 12–13
        self._session(
            course_unit=cu_bit["NET"],
            day_of_week=3,
            start_time=time(12, 0),
            end_time=time(13, 0),
            room_label="D2-1 Community Hour",
            notes="COMMUNITY HOUR — do not schedule teaching over this",
            is_published=False,
        )
        n += 1

        # BCS DB Thu morning
        self._session(
            course_unit=cu_bcs["DB"],
            day_of_week=4,
            start_time=time(8, 30),
            end_time=time(11, 30),
            venue=lab,
            notes="BCS Day — programme-only paper",
        )
        n += 1

        # Tutorial Fri mid
        self._session(
            course_unit=cu_bit["PROG"],
            day_of_week=5,
            start_time=time(11, 30),
            end_time=time(13, 30),
            venue=mini,
            session_type="tutorial",
            notes="Tutorial band",
        )
        n += 1
        return n

    def _seed_weekend(self, cu_wkd, venues):
        n = 0
        kla = venues["TT-KLA-D44"]

        # Fri 07–09 Drawing-style programming
        self._session(
            course_unit=cu_wkd["PROG"],
            day_of_week=5,
            start_time=time(7, 0),
            end_time=time(9, 0),
            venue=kla,
            notes="Weekend Fri physical — Kampala D4-4",
        )
        n += 1

        # Sat 09–11 Networks
        self._session(
            course_unit=cu_wkd["NET"],
            day_of_week=6,
            start_time=time(9, 0),
            end_time=time(11, 0),
            venue=kla,
            notes="Weekend Sat",
        )
        n += 1

        # Sun online Ethics
        self._session(
            course_unit=cu_wkd["ETHICS"],
            day_of_week=7,
            start_time=time(10, 0),
            end_time=time(13, 0),
            delivery_mode="online",
            room_label="",
            notes="Weekend Sunday ONLINE (all lectures online)",
        )
        n += 1

        # Sat afternoon room_label only (no Venue FK)
        self._session(
            course_unit=cu_wkd["COMM"],
            day_of_week=6,
            start_time=time(14, 0),
            end_time=time(16, 0),
            room_label="Learning Centre RM1",
            notes="Weekend Sat — free-text room_label only",
        )
        n += 1
        return n

    def _seed_engineering_streams(self, cu_be, sec_i, sec_ii, venues):
        n = 0
        l2 = venues["TT-MAIN-L2R1"]
        lab = venues["TT-MAIN-LAB"]

        # Stream I EMT Mon 09–12
        self._session(
            course_unit=cu_be["EMT"],
            teaching_section=sec_i,
            day_of_week=1,
            start_time=time(9, 0),
            end_time=time(12, 0),
            venue=l2,
            notes="Stream I EMT — parallel class (not Shared Teaching)",
        )
        n += 1

        # Stream II EMT Tue 09–12 (different lecturer/room pattern)
        self._session(
            course_unit=cu_be["EMT"],
            teaching_section=sec_ii,
            day_of_week=2,
            start_time=time(9, 0),
            end_time=time(12, 0),
            venue=lab,
            notes="Stream II EMT — same code, different sitting",
        )
        n += 1

        # Drawing whole-cohort Wed
        self._session(
            course_unit=cu_be["DRAW"],
            day_of_week=3,
            start_time=time(14, 0),
            end_time=time(17, 0),
            venue=lab,
            notes="BE Drawing — cohort-wide (no section)",
        )
        n += 1

        # Survey lecture Thu
        self._session(
            course_unit=cu_be["SURVEY"],
            teaching_section=sec_i,
            day_of_week=4,
            start_time=time(9, 0),
            end_time=time(11, 0),
            venue=l2,
            notes="Survey lecture Stream I",
        )
        n += 1

        # Survey practical Fri
        self._session(
            course_unit=cu_be["SURVEY_P"],
            teaching_section=sec_i,
            day_of_week=5,
            start_time=time(9, 0),
            end_time=time(12, 0),
            venue=lab,
            session_type="practical",
            notes="GEO practical (P) — session_type=practical",
        )
        n += 1
        return n

    def _seed_edge_cases(self, cu_bit, venues):
        n = 0
        # Unpublished draft
        self._session(
            course_unit=cu_bit["NET"],
            day_of_week=1,
            start_time=time(16, 0),
            end_time=time(17, 0),
            venue=venues["TT-MAIN-MINI"],
            is_published=False,
            notes="UNPUBLISHED draft — hidden from student portal",
        )
        n += 1

        # One-off dated session (no recurring range)
        self._session(
            course_unit=cu_bit["PROG"],
            day_of_week=4,
            session_date=SEM_START + timedelta(days=10),
            start_date=None,
            end_date=None,
            start_time=time(18, 0),
            end_time=time(20, 0),
            room_label="Special makeup class hall",
            notes="One-off session_date makeup class",
        )
        n += 1
        return n
