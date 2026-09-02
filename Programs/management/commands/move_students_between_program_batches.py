"""
Move student(s) from one ProgramBatch to another (same programme).

Updates intended_program_batch + SPE via admission sync, remaps course
enrollments by course code onto the destination batch, withdraws source rows.

Examples:
  python manage.py move_students_between_program_batches \\
    --from-batch-id 262 --to-batch-id 154 --dry-run
  python manage.py move_students_between_program_batches \\
    --from-batch-id 262 --to-batch-id 154
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from admissions.models import AdmittedStudent
from admissions.serializers import AdmittedStudentSerializer
from Programs.models import CourseUnit, ProgramBatch, StudentCourseUnitEnrollment
from Programs.teaching_sections import ensure_enrollment_teaching_section


class Command(BaseCommand):
    help = "Move SPE students from one ProgramBatch to another (same programme), remapping course enrollments by code."

    def add_arguments(self, parser):
        parser.add_argument("--from-batch-id", type=int, required=True)
        parser.add_argument("--to-batch-id", type=int, required=True)
        parser.add_argument(
            "--reg-no",
            action="append",
            dest="reg_nos",
            default=[],
            help="Limit to specific reg_no (repeatable). Default: all SPE on from-batch.",
        )
        parser.add_argument(
            "--keep-registration-date",
            action="store_true",
            help="When remapping, copy registration_date to the new enrollment if set.",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        from_id = options["from_batch_id"]
        to_id = options["to_batch_id"]
        dry = bool(options.get("dry_run"))
        keep_reg = bool(options.get("keep_registration_date"))

        try:
            from_batch = ProgramBatch.objects.select_related("program").get(pk=from_id)
            to_batch = ProgramBatch.objects.select_related("program").get(pk=to_id)
        except ProgramBatch.DoesNotExist as exc:
            raise CommandError(str(exc)) from exc

        if from_batch.program_id != to_batch.program_id:
            raise CommandError(
                f"Batches must share a programme "
                f"(from program={from_batch.program_id}, to={to_batch.program_id})."
            )

        dest_units = {
            (cu.code or "").strip().upper(): cu
            for cu in CourseUnit.objects.filter(program_batch=to_batch, is_active=True)
            if (cu.code or "").strip()
        }

        students_qs = AdmittedStudent.objects.filter(
            programme_enrollment__program_batch_id=from_id
        ).select_related("programme_enrollment", "application")
        reg_nos = [r.strip() for r in (options.get("reg_nos") or []) if r and r.strip()]
        if reg_nos:
            students_qs = students_qs.filter(reg_no__in=reg_nos)

        students = list(students_qs.order_by("reg_no"))
        if not students:
            raise CommandError(f"No students found on ProgramBatch #{from_id}.")

        self.stdout.write(
            f"Moving {len(students)} student(s): "
            f"#{from_id} {from_batch.name} → #{to_id} {to_batch.name}"
            + (" [dry-run]" if dry else "")
        )

        for student in students:
            self._move_one(
                student,
                from_batch=from_batch,
                to_batch=to_batch,
                dest_units=dest_units,
                keep_reg=keep_reg,
                dry=dry,
            )

        if dry:
            self.stdout.write(self.style.WARNING("Dry run — no changes saved."))

    def _move_one(self, student, *, from_batch, to_batch, dest_units, keep_reg, dry):
        spe = getattr(student, "programme_enrollment", None)
        self.stdout.write(
            f"  {student.reg_no} — {student.full_name} "
            f"(intended={student.intended_program_batch_id}, spe_batch={getattr(spe, 'program_batch_id', None)})"
        )

        source_enrollments = list(
            StudentCourseUnitEnrollment.objects.filter(
                student=student,
                course_unit__program_batch=from_batch,
            ).select_related("course_unit", "course_result")
        )
        remap_plan = []
        missing_codes = []
        blocked = []
        for enr in source_enrollments:
            code = (enr.course_unit.code or "").strip().upper()
            dest = dest_units.get(code)
            if not dest:
                missing_codes.append(code or f"cu#{enr.course_unit_id}")
                continue
            try:
                result = getattr(enr, "course_result", None)
            except StudentCourseUnitEnrollment.course_result.RelatedObjectDoesNotExist:
                result = None
            if result is not None and result.status == "published":
                blocked.append(f"{code} has published result")
                continue
            remap_plan.append((enr, dest))

        if blocked:
            self.stdout.write(
                self.style.ERROR(f"    SKIP — {'; '.join(blocked)}")
            )
            return
        if missing_codes:
            self.stdout.write(
                self.style.WARNING(
                    f"    Codes with no match on destination batch: {', '.join(missing_codes)}"
                )
            )

        self.stdout.write(
            f"    Will remap {len(remap_plan)} enrollment(s); "
            f"withdraw source rows on batch #{from_batch.id}"
        )
        if dry:
            return

        with transaction.atomic():
            student.intended_program_batch = to_batch
            student.save(update_fields=["intended_program_batch", "updated_at"])
            AdmittedStudentSerializer._sync_programme_enrollment_batch(student)

            spe = student.programme_enrollment
            spe.refresh_from_db()
            ensure_enrollment_teaching_section(spe, assign_only=False)

            created = updated = withdrawn = 0
            for enr, dest in remap_plan:
                try:
                    result = getattr(enr, "course_result", None)
                except StudentCourseUnitEnrollment.course_result.RelatedObjectDoesNotExist:
                    result = None
                if result is not None and result.status != "published":
                    result.delete()

                existing = StudentCourseUnitEnrollment.objects.filter(
                    student=student, course_unit=dest
                ).first()
                if existing:
                    if existing.status == "withdrawn":
                        existing.status = "enrolled"
                        existing.source = existing.source or "admin_assigned"
                        if keep_reg and enr.registration_date and not existing.registration_date:
                            existing.registration_date = enr.registration_date
                        existing.save()
                        updated += 1
                    else:
                        updated += 1
                else:
                    StudentCourseUnitEnrollment.objects.create(
                        student=student,
                        course_unit=dest,
                        status="enrolled",
                        source="admin_assigned",
                        registration_date=enr.registration_date if keep_reg else None,
                        registration_kind=enr.registration_kind,
                    )
                    created += 1

                if enr.status != "withdrawn":
                    enr.status = "withdrawn"
                    enr.save(update_fields=["status", "updated_at"])
                    withdrawn += 1

            self.stdout.write(
                self.style.SUCCESS(
                    f"    Done: intended+SPE→{to_batch.id}; "
                    f"created={created} updated={updated} withdrawn_source={withdrawn}"
                )
            )
