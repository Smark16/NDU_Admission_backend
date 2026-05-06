"""
NEW MODULE — Update semester (part of program batch management).

Paired with CreateSemesterView in batch_views.py; route in Programs/urls.py:
  batch/<batch_id>/semester/<semester_id>/update
"""
from datetime import datetime

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ProgramBatch, Semester


class UpdateSemesterView(APIView):
    """NEW MODULE — PUT to update name, dates, order, is_active for a Semester."""

    permission_classes = [IsAuthenticated]

    def put(self, request, batch_id, semester_id):
        try:
            batch = ProgramBatch.objects.get(id=batch_id)
        except ProgramBatch.DoesNotExist:
            return Response({"detail": "Batch not found"}, status=status.HTTP_404_NOT_FOUND)
        try:
            semester = Semester.objects.get(id=semester_id, program_batch=batch)
        except Semester.DoesNotExist:
            return Response({"detail": "Semester not found"}, status=status.HTTP_404_NOT_FOUND)

        name = (request.data.get("name") or "").strip()
        if not name:
            return Response({"detail": "Semester name is required"}, status=status.HTTP_400_BAD_REQUEST)

        start_date = (request.data.get("start_date") or "").strip()
        end_date = (request.data.get("end_date") or "").strip()
        if not start_date:
            return Response({"detail": "Start date is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            start = datetime.strptime(start_date, "%Y-%m-%d").date()
        except ValueError:
            return Response(
                {"detail": "Invalid start date. Use YYYY-MM-DD."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        end = None
        if end_date:
            try:
                end = datetime.strptime(end_date, "%Y-%m-%d").date()
            except ValueError:
                return Response(
                    {"detail": "Invalid end date. Use YYYY-MM-DD."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if end < start:
                return Response(
                    {"detail": "End date must be after start date"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        order_raw = request.data.get("order", semester.order)
        try:
            order = int(order_raw)
            if order < 1:
                raise ValueError
        except (TypeError, ValueError):
            return Response({"detail": "Order must be a positive integer"}, status=status.HTTP_400_BAD_REQUEST)

        max_allowed = int(batch.program.min_years or 0) * int(batch.program.max_terms_per_year or 0)
        if max_allowed > 0 and order > max_allowed:
            return Response(
                {
                    "detail": (
                        f"Cannot set term order to {order}. This programme allows at most "
                        f"{max_allowed} semesters/terms ({batch.program.min_years} year(s) x "
                        f"{batch.program.max_terms_per_year} term(s) per year)."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if Semester.objects.filter(program_batch=batch, order=order).exclude(id=semester.id).exists():
            return Response(
                {"detail": f"Another semester already uses order {order} in this batch"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # --- curriculum position (optional update) ---
        year_of_study = semester.year_of_study
        term_number = semester.term_number
        year_raw = request.data.get("year_of_study")
        term_raw = request.data.get("term_number")

        # Accept explicit null to clear the position
        if "year_of_study" in request.data or "term_number" in request.data:
            if year_raw is None and term_raw is None:
                # caller explicitly clearing both
                year_of_study = None
                term_number = None
            else:
                try:
                    year_of_study = int(year_raw)
                    term_number = int(term_raw)
                except (ValueError, TypeError):
                    return Response(
                        {"detail": "year_of_study and term_number must both be integers when provided."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                program = batch.program
                if year_of_study < 1 or year_of_study > program.max_years:
                    return Response(
                        {"detail": f"year_of_study must be between 1 and {program.max_years}."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                max_terms = program.max_terms_per_year
                if term_number not in range(1, max_terms + 1):
                    return Response(
                        {"detail": f"term_number must be between 1 and {max_terms} for a {program.calendar_type}-based programme."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                if Semester.objects.filter(
                    program_batch=batch,
                    year_of_study=year_of_study,
                    term_number=term_number,
                ).exclude(id=semester.id).exists():
                    return Response(
                        {"detail": f"A semester at Year {year_of_study} Term {term_number} already exists in this batch."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

        is_active = request.data.get("is_active")
        semester.name = name
        semester.start_date = start
        semester.end_date = end
        semester.order = order
        semester.year_of_study = year_of_study
        semester.term_number = term_number
        if is_active is not None:
            semester.is_active = bool(is_active)
        semester.save()

        return Response(
            {
                "id": semester.id,
                "name": semester.name,
                "order": semester.order,
                "year_of_study": semester.year_of_study,
                "term_number": semester.term_number,
                "is_curriculum_positioned": semester.year_of_study is not None and semester.term_number is not None,
                "start_date": semester.start_date.isoformat(),
                "end_date": semester.end_date.isoformat() if semester.end_date else None,
                "is_active": semester.is_active,
                "message": "Semester updated successfully",
            },
            status=status.HTTP_200_OK,
        )
