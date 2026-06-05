from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from admissions.models import AdmittedStudent
from Programs.models import StudentProgrammeEnrollment

from .models import GraduationAssignment, GraduationCeremony, GraduationSession
from .permissions import (
    CanAccessGraduation,
    CanAssignStudents,
    CanManageCeremonies,
    CanViewGraduationLists,
    CanViewQualifiedLists,
)
from .serializers import (
    GraduationAssignmentSerializer,
    GraduationCeremonySerializer,
    GraduationSessionSerializer,
)
from .services.qualification import (
    DEFAULT_MIN_CGPA,
    evaluate_student_graduation,
    qualified_students_queryset,
)


def _parse_min_cgpa(raw) -> Decimal:
    if raw in (None, ""):
        return DEFAULT_MIN_CGPA
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return DEFAULT_MIN_CGPA


class QualifiedStudentsView(APIView):
    """Students academically eligible to graduate (preview before ceremony assignment)."""

    permission_classes = [IsAuthenticated, CanViewQualifiedLists]

    def get(self, request):
        program_batch_id = request.query_params.get("program_batch_id")
        program_id = request.query_params.get("program_id")
        qualified_only = request.query_params.get("qualified_only", "").lower() in (
            "1",
            "true",
            "yes",
        )
        min_cgpa = _parse_min_cgpa(request.query_params.get("min_cgpa"))

        batch_id = int(program_batch_id) if program_batch_id else None
        prog_id = int(program_id) if program_id else None

        if not batch_id and not prog_id:
            return Response(
                {"detail": "Provide program_batch_id or program_id."},
                status=400,
            )

        rows = qualified_students_queryset(
            program_batch_id=batch_id,
            program_id=prog_id,
            min_cgpa=min_cgpa,
        )
        if qualified_only:
            rows = [r for r in rows if r["qualified"]]

        qualified_count = sum(1 for r in rows if r["qualified"])

        return Response(
            {
                "program_batch_id": batch_id,
                "program_id": prog_id,
                "min_cgpa": str(min_cgpa),
                "total": len(rows),
                "qualified_count": qualified_count,
                "students": rows,
            }
        )


class CeremonyListCreateView(APIView):
    permission_classes = [IsAuthenticated, CanManageCeremonies]

    def get(self, request):
        active = request.query_params.get("active_only", "1").lower() in ("1", "true", "yes")
        qs = GraduationCeremony.objects.all()
        if active:
            qs = qs.filter(is_active=True)
        return Response(
            {"ceremonies": GraduationCeremonySerializer(qs, many=True).data}
        )

    def post(self, request):
        serializer = GraduationCeremonySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ceremony = serializer.save(created_by=request.user)
        return Response(
            GraduationCeremonySerializer(ceremony).data,
            status=status.HTTP_201_CREATED,
        )


class CeremonyDetailView(APIView):
    permission_classes = [IsAuthenticated, CanManageCeremonies]

    def get(self, request, ceremony_id):
        ceremony = get_object_or_404(GraduationCeremony, pk=ceremony_id)
        sessions = ceremony.sessions.all().order_by("graduation_date", "name")
        return Response(
            {
                "ceremony": GraduationCeremonySerializer(ceremony).data,
                "sessions": GraduationSessionSerializer(sessions, many=True).data,
            }
        )

    def patch(self, request, ceremony_id):
        ceremony = get_object_or_404(GraduationCeremony, pk=ceremony_id)
        serializer = GraduationCeremonySerializer(ceremony, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, ceremony_id):
        ceremony = get_object_or_404(GraduationCeremony, pk=ceremony_id)
        if ceremony.sessions.filter(assignments__isnull=False).exists():
            return Response(
                {"detail": "Cannot delete ceremony with assigned students."},
                status=400,
            )
        ceremony.delete()
        return Response(status=204)


class SessionListCreateView(APIView):
    permission_classes = [IsAuthenticated, CanManageCeremonies]

    def post(self, request, ceremony_id):
        ceremony = get_object_or_404(GraduationCeremony, pk=ceremony_id)
        data = {**request.data, "ceremony": ceremony.id}
        serializer = GraduationSessionSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        session = serializer.save()
        return Response(GraduationSessionSerializer(session).data, status=201)


class SessionDetailView(APIView):
    permission_classes = [IsAuthenticated, CanManageCeremonies]

    def patch(self, request, session_id):
        session = get_object_or_404(GraduationSession, pk=session_id)
        serializer = GraduationSessionSerializer(session, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, session_id):
        session = get_object_or_404(GraduationSession, pk=session_id)
        if session.assignments.exists():
            return Response(
                {"detail": "Remove assigned students before deleting this session."},
                status=400,
            )
        session.delete()
        return Response(status=204)


class SessionAssignmentsView(APIView):
    permission_classes = [IsAuthenticated, CanAssignStudents]

    def get(self, request, session_id):
        session = get_object_or_404(
            GraduationSession.objects.select_related("ceremony"),
            pk=session_id,
        )
        assignments = session.assignments.select_related(
            "student",
            "student__programme_enrollment",
            "student__programme_enrollment__program",
        ).order_by("student__reg_no")
        return Response(
            {
                "session": GraduationSessionSerializer(session).data,
                "ceremony": GraduationCeremonySerializer(session.ceremony).data,
                "assignments": GraduationAssignmentSerializer(assignments, many=True).data,
                "count": assignments.count(),
            }
        )

    def post(self, request, session_id):
        session = get_object_or_404(GraduationSession, pk=session_id)
        student_ids = request.data.get("student_ids") or []
        if not student_ids:
            return Response({"detail": "student_ids is required."}, status=400)

        require_qualified = request.data.get("require_qualified", True)
        complete_enrollment = request.data.get("complete_enrollment", False)
        min_cgpa = _parse_min_cgpa(request.data.get("min_cgpa"))

        created = []
        errors = []

        with transaction.atomic():
            for sid in student_ids:
                try:
                    student = AdmittedStudent.objects.get(pk=sid, is_admitted=True)
                except AdmittedStudent.DoesNotExist:
                    errors.append({"student_id": sid, "detail": "Student not found."})
                    continue

                if GraduationAssignment.objects.filter(student=student).exists():
                    errors.append(
                        {
                            "student_id": sid,
                            "detail": "Already assigned to a graduation session.",
                        }
                    )
                    continue

                eval_row = evaluate_student_graduation(student, min_cgpa=min_cgpa)
                if require_qualified and not eval_row["qualified"]:
                    errors.append(
                        {
                            "student_id": sid,
                            "detail": "Not qualified.",
                            "blockers": eval_row["blockers"],
                        }
                    )
                    continue

                assignment = GraduationAssignment.objects.create(
                    session=session,
                    student=student,
                    cgpa_at_assignment=eval_row["cgpa"],
                    credit_units_at_assignment=eval_row["total_credit_units"],
                    award_class=eval_row["award_class"] or "",
                    assigned_by=request.user,
                )

                if complete_enrollment:
                    try:
                        enr = student.programme_enrollment
                        if enr.status == "enrolled":
                            enr.status = "completed"
                            enr.save(update_fields=["status", "updated_at"])
                            assignment.enrollment_completed = True
                            assignment.save(update_fields=["enrollment_completed"])
                    except StudentProgrammeEnrollment.DoesNotExist:
                        pass

                created.append(GraduationAssignmentSerializer(assignment).data)

        return Response(
            {
                "created": created,
                "created_count": len(created),
                "errors": errors,
            },
            status=200 if created else 400,
        )

    def delete(self, request, session_id):
        session = get_object_or_404(GraduationSession, pk=session_id)
        student_ids = request.data.get("student_ids") or []
        if not student_ids:
            return Response({"detail": "student_ids is required."}, status=400)
        removed = GraduationAssignment.objects.filter(
            session=session, student_id__in=student_ids
        ).delete()[0]
        return Response({"removed_count": removed})


class GraduationPrintListView(APIView):
    """Printable graduation list for a session (ceremony book)."""

    permission_classes = [IsAuthenticated, CanViewGraduationLists]

    def get(self, request, session_id):
        session = get_object_or_404(
            GraduationSession.objects.select_related("ceremony"),
            pk=session_id,
        )
        assignments = session.assignments.select_related(
            "student",
            "student__programme_enrollment",
            "student__programme_enrollment__program",
        ).order_by(
            "student__programme_enrollment__program__name",
            "student__reg_no",
        )

        by_program: dict[str, list] = {}
        for a in assignments:
            try:
                prog = a.student.programme_enrollment.program.name
            except Exception:
                prog = "Unknown programme"
            by_program.setdefault(prog, []).append(
                {
                    "reg_no": a.student.reg_no,
                    "student_name": a.student.full_name,
                    "cgpa": str(a.cgpa_at_assignment) if a.cgpa_at_assignment else None,
                    "credit_units": str(a.credit_units_at_assignment)
                    if a.credit_units_at_assignment
                    else None,
                    "award_class": a.award_class,
                }
            )

        return Response(
            {
                "ceremony": GraduationCeremonySerializer(session.ceremony).data,
                "session": GraduationSessionSerializer(session).data,
                "show_marks_on_transcript": session.ceremony.show_marks_on_transcript,
                "total": assignments.count(),
                "by_programme": [
                    {"programme": k, "students": v} for k, v in sorted(by_program.items())
                ],
            }
        )
