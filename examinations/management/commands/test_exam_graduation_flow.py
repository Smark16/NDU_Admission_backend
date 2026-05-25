"""Integration smoke test: examinations + graduation APIs."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management.base import BaseCommand
from django.test import override_settings
from rest_framework.test import APIClient

from admissions.models import AdmittedStudent
from examinations.models import AssessmentPolicy, CourseUnitResult, GradeScale
from examinations.services.scoring import compute_course_result
from graduation.models import GraduationAssignment, GraduationCeremony, GraduationSession
from graduation.services.qualification import evaluate_student_graduation
from Programs.models import CourseUnit, ProgramBatch, StudentCourseUnitEnrollment


def _response_data(res):
    if hasattr(res, "data"):
        return res.data
    try:
        import json

        return json.loads(res.content.decode()) if res.content else {}
    except Exception:
        return {"detail": res.content.decode()[:200] if res.content else str(res.status_code)}


class Command(BaseCommand):
    help = "Smoke-test examinations and graduation APIs against the database."

    @override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"])
    def handle(self, *args, **options):
        failures = []
        passed = []

        def ok(msg):
            passed.append(msg)
            self.stdout.write(self.style.SUCCESS(f"  OK  {msg}"))

        def fail(msg, exc=None):
            failures.append(msg)
            self.stdout.write(self.style.ERROR(f"  FAIL {msg}"))
            if exc:
                self.stdout.write(f"       {exc}")

        self.stdout.write(self.style.MIGRATE_HEADING("Examinations + Graduation integration test\n"))

        # --- Setup data ---
        policy = AssessmentPolicy.get_active_default()
        if not policy:
            self.stdout.write("Seeding assessment policy…")
            from django.core.management import call_command

            call_command("seed_examination_defaults", verbosity=0)
            policy = AssessmentPolicy.get_active_default()

        if not policy:
            fail("No assessment policy")
            self._summary(passed, failures)
            return

        scale = GradeScale.get_active()
        if not scale:
            fail("No grade scale")
            self._summary(passed, failures)
            return

        enrollment = (
            StudentCourseUnitEnrollment.objects.filter(status="enrolled")
            .select_related("student", "course_unit", "course_unit__program_batch")
            .first()
        )
        if not enrollment:
            fail(
                "No StudentCourseUnitEnrollment with status=enrolled — "
                "enroll a student via Academic Enrollment first"
            )
            self._summary(passed, failures)
            return

        course = enrollment.course_unit
        batch = course.program_batch
        if not batch:
            fail("Course has no program_batch")
            self._summary(passed, failures)
            return

        student = enrollment.student
        ok(f"Using batch: {batch.name} (id={batch.id})")
        ok(f"Using course: {course.code} (id={course.id})")
        ok(f"Using student: {student.reg_no} (id={student.id})")

        User = get_user_model()
        staff = User.objects.filter(is_superuser=True).first()
        if not staff:
            staff = User.objects.filter(is_staff=True).first()
        if not staff:
            fail("No staff user for API tests")
            self._summary(passed, failures)
            return

        # Ensure graduation permissions on staff
        for perm_str in (
            "accounts.access_examinations",
            "accounts.access_graduation",
            "examinations.publish_results",
            "examinations.enter_marks",
            "examinations.view_all_results",
            "graduation.view_qualified_lists",
            "graduation.manage_ceremonies",
            "graduation.assign_students",
            "graduation.view_graduation_lists",
        ):
            app_label, codename = perm_str.split(".", 1)
            perm = Permission.objects.filter(
                content_type__app_label=app_label, codename=codename
            ).first()
            if perm:
                staff.user_permissions.add(perm)

        client = APIClient()
        client.force_authenticate(user=staff)

        # --- Scoring engine ---
        try:
            r = compute_course_result(
                ca_mark=Decimal("20"),
                exam_mark=Decimal("60"),
                policy=policy.as_policy_values(),
            )
            assert r.exam_sitting_allowed and r.final_mark == Decimal("56.00")
            ok(f"Scoring: CA 20 + exam 60 -> final {r.final_mark}")
        except Exception as e:
            fail("Scoring engine", e)

        try:
            compute_course_result(
                ca_mark=Decimal("10"),
                exam_mark=Decimal("80"),
                policy=policy.as_policy_values(),
            )
            fail("Scoring should block exam when CA < 17.5")
        except Exception:
            ok("Scoring blocks exam when CA < 17.5")

        # --- Marks API ---
        marks_url = f"/api/examinations/lecturer/courses/{course.id}/marks/"
        try:
            res = client.get(marks_url)
            data = _response_data(res)
            if res.status_code != 200:
                fail(f"GET marks -> {res.status_code}: {data}")
            else:
                ok(f"GET marks ({len(data.get('rows', []))} rows)")
        except Exception as e:
            fail("GET marks", e)

        try:
            res = client.post(
                marks_url,
                {
                    "marks": [
                        {
                            "enrollment_id": enrollment.id,
                            "ca_mark": "22",
                            "exam_mark": "65",
                        }
                    ]
                },
                format="json",
            )
            data = _response_data(res)
            if res.status_code not in (200, 400):
                fail(f"POST marks -> {res.status_code}: {data}")
            elif data.get("saved_count", 0) < 1 and data.get("errors"):
                fail(f"POST marks errors: {data.get('errors')}")
            else:
                ok("POST marks (CA 22, exam 65)")
        except Exception as e:
            fail("POST marks", e)

        # --- Staff courses filter ---
        try:
            res = client.get(
                "/api/examinations/staff/courses/",
                {"program_batch_id": batch.id, "with_students_only": "1"},
            )
            data = _response_data(res)
            if res.status_code != 200:
                fail(f"Staff courses filter -> {res.status_code}: {data}")
            else:
                ids = [c["course_unit_id"] for c in data.get("courses", [])]
                if course.id not in ids:
                    fail(f"Course {course.id} not in batch-filtered list")
                else:
                    ok(f"Staff courses filtered by batch ({len(ids)} courses)")
        except Exception as e:
            fail("Staff courses filter", e)

        # --- Publish ---
        try:
            res = client.post(
                f"/api/examinations/lecturer/courses/{course.id}/publish/?force=true"
            )
            data = _response_data(res)
            if res.status_code != 200:
                fail(f"Publish -> {res.status_code}: {data}")
            else:
                ok(f"Publish ({data.get('published_count', 0)} published)")
        except Exception as e:
            fail("Publish", e)

        result = CourseUnitResult.objects.filter(enrollment=enrollment).first()
        if result and result.status == CourseUnitResult.STATUS_PUBLISHED:
            ok("Result row is published")
        elif result and result.status in (
            CourseUnitResult.STATUS_DRAFT,
            CourseUnitResult.STATUS_VERIFIED,
        ):
            fail(f"Result still {result.status} after publish (expected published)")
        else:
            fail("No result row after marks save")

        # --- Student my-results ---
        student_user = getattr(student, "student_user", None)
        if student_user:
            sclient = APIClient()
            sclient.force_authenticate(user=student_user)
            try:
                res = sclient.get("/api/examinations/student/my-results/")
                if res.status_code == 200:
                    ok("Student my-results")
                else:
                    fail(f"Student my-results → {res.status_code}")
            except Exception as e:
                fail("Student my-results", e)
        else:
            self.stdout.write("  SKIP student my-results (no student_user linked)")

        # --- Graduation qualified ---
        try:
            res = client.get(
                "/api/graduation/qualified/",
                {"program_batch_id": batch.id, "qualified_only": "0"},
            )
            data = _response_data(res)
            if res.status_code != 200:
                fail(f"Qualified list -> {res.status_code}: {data}")
            else:
                ok(
                    f"Qualified list ({data.get('qualified_count', 0)}/"
                    f"{data.get('total', 0)} qualified)"
                )
        except Exception as e:
            fail("Qualified list", e)

        eval_row = evaluate_student_graduation(student)
        ok(
            f"Qualification eval for test student: qualified={eval_row['qualified']} "
            f"cgpa={eval_row.get('cgpa')}"
        )

        # --- Ceremony + assign ---
        ceremony = None
        try:
            ceremony = GraduationCeremony.objects.create(
                name="INTEGRATION TEST Ceremony",
                completion_date="2026-07-01",
                created_by=staff,
            )
            session = GraduationSession.objects.create(
                ceremony=ceremony,
                name="Test Day 1",
                graduation_date="2026-07-15",
            )
            GraduationAssignment.objects.filter(student=student).delete()

            res = client.post(
                f"/api/graduation/sessions/{session.id}/assignments/",
                {
                    "student_ids": [student.id],
                    "require_qualified": False,
                    "complete_enrollment": False,
                },
                format="json",
            )
            data = _response_data(res)
            if res.status_code != 200 or data.get("created_count", 0) < 1:
                fail(f"Assign student -> {res.status_code} {data}")
            else:
                ok("Assign student to graduation session")

            res = client.get(f"/api/graduation/sessions/{session.id}/print-list/")
            data = _response_data(res)
            if res.status_code != 200:
                fail(f"Print list -> {res.status_code}: {data}")
            else:
                ok(f"Print list ({data.get('total', 0)} graduate(s))")
        except Exception as e:
            fail("Ceremony flow", e)
        finally:
            if ceremony:
                ceremony.delete()
                ok("Test ceremony cleaned up")

        self._summary(passed, failures)

    def _summary(self, passed, failures):
        self.stdout.write("")
        self.stdout.write(f"Passed: {len(passed)}  Failed: {len(failures)}")
        if failures:
            self.stdout.write(self.style.ERROR("Some tests failed."))
        else:
            self.stdout.write(self.style.SUCCESS("All integration checks passed."))