"""Timetable APIs: venues (classrooms), semester sessions, student/lecturer views."""
from __future__ import annotations

from datetime import date, datetime
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
import csv
import io

from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Campus
from Programs.models import CourseUnit, RoomType, Semester, TimetableSession, Venue
from Programs.permissions import ProgramSchedulingAPIPermission
from admissions.faculty_scope import assert_semester_access, assert_timetable_session_access
from Programs.venue_code_utils import (
    ensure_room_type,
    list_room_type_names,
    suggest_venue_code,
    unique_venue_code_for_campus,
)
from Programs.timetable_pdf import (
    build_teaching_load_pdf_context,
    build_timetable_pdf_context,
    render_teaching_load_pdf,
    render_timetable_pdf,
    safe_pdf_filename,
)
from Programs.timetable_utils import (
    build_catalog_overview,
    compute_teaching_load,
    parse_delivery_mode,
    resolve_semester_campuses,
    serialize_session,
    sessions_for_semester,
    validate_session_scheduling,
)


def _parse_time(value: str, label: str):
    text = (value or "").strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"{label} must be HH:MM (e.g. 09:00).")


def _parse_date(value, label: str, *, required: bool = True) -> date | None:
    text = (value or "").strip()
    if not text:
        if required:
            raise ValueError(f"{label} is required (YYYY-MM-DD).")
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"{label} must be YYYY-MM-DD.") from exc


def _serialize_venue(v: Venue) -> dict:
    return {
        "id": v.id,
        "campus_id": v.campus_id,
        "campus_name": v.campus.name if v.campus_id else "",
        "code": v.code or "",
        "name": v.name,
        "building": v.building or "",
        "room_type": v.room_type,
        "capacity": v.capacity,
        "allows_parallel_sessions": v.allows_parallel_sessions,
        "is_active": v.is_active,
    }


def _validation_response(validation, *, session_data: dict | None = None, status_code=400):
    body = {
        "detail": "; ".join(validation.errors) if validation.errors else "Scheduling conflict.",
        "errors": validation.errors,
        "warnings": validation.warnings,
        "clashes": validation.clashes,
    }
    if session_data:
        body.update(session_data)
    return Response(body, status=status_code)


class VenueListCreateView(APIView):
    """Classroom register: list / create venues per campus."""

    permission_classes = [IsAuthenticated, ProgramSchedulingAPIPermission]

    def get(self, request):
        include_inactive = request.query_params.get("include_inactive", "").lower() in (
            "1",
            "true",
            "yes",
        )
        qs = Venue.objects.select_related("campus")
        if not include_inactive:
            qs = qs.filter(is_active=True)
        campus_id = request.query_params.get("campus_id")
        if campus_id:
            qs = qs.filter(campus_id=campus_id)
        building = (request.query_params.get("building") or "").strip()
        if building:
            qs = qs.filter(building__icontains=building)
        payload = {
            "venues": [_serialize_venue(v) for v in qs.order_by("campus__name", "building", "name")],
            "room_types": list_room_type_names(),
        }
        return Response(payload)

    def post(self, request):
        campus_id = request.data.get("campus_id")
        name = (request.data.get("name") or "").strip()
        if not campus_id:
            return Response({"detail": "campus_id is required."}, status=400)
        if not name:
            return Response({"detail": "name is required."}, status=400)
        if Venue.objects.filter(campus_id=campus_id, name__iexact=name, is_active=True).exists():
            return Response(
                {"detail": f'A room named "{name}" already exists on this campus.'},
                status=400,
            )
        campus = get_object_or_404(Campus, pk=campus_id)
        building = (request.data.get("building") or "").strip()
        code = (request.data.get("code") or "").strip()
        if not code:
            base = suggest_venue_code(
                campus_code=campus.code,
                campus_name=campus.name,
                building=building,
                name=name,
            )
            code = unique_venue_code_for_campus(campus_id, base)
        elif Venue.objects.filter(campus_id=campus_id, code__iexact=code).exists():
            return Response({"detail": f'Code "{code}" already exists on this campus.'}, status=400)
        room_type = ensure_room_type(request.data.get("room_type") or "Lecture room")
        capacity = request.data.get("capacity")
        row = Venue.objects.create(
            campus_id=campus_id,
            name=name,
            code=code,
            building=building,
            room_type=room_type,
            capacity=int(capacity) if capacity not in (None, "") else None,
            allows_parallel_sessions=bool(request.data.get("allows_parallel_sessions", False)),
        )
        data = _serialize_venue(row)
        data["generated_code"] = not bool((request.data.get("code") or "").strip())
        return Response(data, status=201)


class RoomTypeListCreateView(APIView):
    """List room types; POST creates a new label for the dropdown."""

    permission_classes = [IsAuthenticated, ProgramSchedulingAPIPermission]

    def get(self, request):
        return Response({"room_types": list_room_type_names()})

    def post(self, request):
        name = (request.data.get("name") or "").strip()
        if not name:
            return Response({"detail": "name is required."}, status=400)
        label = ensure_room_type(name)
        row = RoomType.objects.filter(name=label).first()
        return Response(
            {"id": row.id if row else None, "name": label, "room_types": list_room_type_names()},
            status=201,
        )


class VenueSuggestCodeView(APIView):
    """Preview auto-generated code from campus + building + room name."""

    permission_classes = [IsAuthenticated, ProgramSchedulingAPIPermission]

    def get(self, request):
        campus_id = request.query_params.get("campus_id")
        name = (request.query_params.get("name") or "").strip()
        if not campus_id or not name:
            return Response({"detail": "campus_id and name are required."}, status=400)
        campus = get_object_or_404(Campus, pk=campus_id)
        building = (request.query_params.get("building") or "").strip()
        base = suggest_venue_code(
            campus_code=campus.code,
            campus_name=campus.name,
            building=building,
            name=name,
        )
        code = unique_venue_code_for_campus(int(campus_id), base)
        return Response({"suggested_code": code, "base": base})


class VenueBulkUploadView(APIView):
    """
    POST /api/program/venues/bulk_upload

    Multipart fields:
      - campus_id (required)
      - file (required CSV)

    CSV columns (header row required):
      room_name*  building  room_type  capacity  code  allows_parallel_sessions
    (* room_name required; leave code blank to auto-generate)
    """

    permission_classes = [IsAuthenticated, ProgramSchedulingAPIPermission]
    parser_classes = [MultiPartParser, FormParser]

    @staticmethod
    def _norm_col(name: str) -> str:
        return (name or "").strip().lower().replace(" ", "_")

    @staticmethod
    def _as_bool(value) -> bool | None:
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("1", "true", "yes", "y", "t"):
            return True
        if text in ("0", "false", "no", "n", "f"):
            return False
        return None

    @staticmethod
    def _as_int(value):
        if value is None or value == "":
            return None
        try:
            parsed = int(str(value).strip())
        except (TypeError, ValueError):
            return None
        return parsed if parsed >= 0 else None

    def post(self, request):
        try:
            campus_id = int(request.data.get("campus_id") or 0)
        except (TypeError, ValueError):
            campus_id = 0
        if not campus_id:
            return Response({"detail": "campus_id is required."}, status=400)

        campus = get_object_or_404(Campus, pk=campus_id)

        uploaded = request.FILES.get("file")
        if not uploaded:
            return Response(
                {"detail": 'No file received. Send the CSV as multipart field "file".'},
                status=400,
            )
        if not (uploaded.name or "").lower().endswith(".csv"):
            return Response({"detail": "Only .csv files are accepted."}, status=400)

        try:
            text = uploaded.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            return Response(
                {"detail": "Could not decode file — ensure it is UTF-8 encoded."},
                status=400,
            )

        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            return Response({"detail": "CSV file is empty or has no header row."}, status=400)

        col_map = {
            "room_name": "room_name",
            "name": "room_name",
            "room": "room_name",
            "building": "building",
            "block": "building",
            "room_type": "room_type",
            "type": "room_type",
            "capacity": "capacity",
            "code": "code",
            "allows_parallel_sessions": "allows_parallel_sessions",
            "parallel_labs": "allows_parallel_sessions",
            "parallel": "allows_parallel_sessions",
        }
        resolved = {}
        for raw_col in reader.fieldnames:
            key = col_map.get(self._norm_col(raw_col))
            if key and key not in resolved:
                resolved[key] = raw_col

        if "room_name" not in resolved:
            return Response(
                {"detail": 'CSV must include a "room_name" column.'},
                status=400,
            )

        saved = 0
        errors = []
        seen_names: set[str] = set()

        for row_num, raw in enumerate(reader, start=2):
            row = {}
            for key, raw_col in resolved.items():
                row[key] = (raw.get(raw_col) or "").strip()

            name = row.get("room_name", "")
            if not name:
                errors.append(
                    {
                        "row": row_num,
                        "room_name": "",
                        "reason": "room_name is required.",
                    }
                )
                continue

            name_key = name.lower()
            if name_key in seen_names:
                errors.append(
                    {
                        "row": row_num,
                        "room_name": name,
                        "reason": f'Duplicate room_name "{name}" in this file.',
                    }
                )
                continue

            if Venue.objects.filter(campus_id=campus_id, name__iexact=name, is_active=True).exists():
                errors.append(
                    {
                        "row": row_num,
                        "room_name": name,
                        "reason": f'A room named "{name}" already exists on this campus.',
                    }
                )
                continue

            building = row.get("building", "")
            capacity = self._as_int(row.get("capacity"))
            if row.get("capacity") and capacity is None:
                errors.append(
                    {
                        "row": row_num,
                        "room_name": name,
                        "reason": "capacity must be a whole number.",
                    }
                )
                continue

            parallel_raw = row.get("allows_parallel_sessions", "")
            parallel = self._as_bool(parallel_raw)
            if parallel_raw and parallel is None:
                errors.append(
                    {
                        "row": row_num,
                        "room_name": name,
                        "reason": "allows_parallel_sessions must be yes/no or 1/0.",
                    }
                )
                continue
            if parallel is None:
                parallel = False

            code = row.get("code", "")
            if code:
                if Venue.objects.filter(campus_id=campus_id, code__iexact=code).exists():
                    errors.append(
                        {
                            "row": row_num,
                            "room_name": name,
                            "reason": f'Code "{code}" already exists on this campus.',
                        }
                    )
                    continue
            else:
                base = suggest_venue_code(
                    campus_code=campus.code,
                    campus_name=campus.name,
                    building=building,
                    name=name,
                )
                code = unique_venue_code_for_campus(campus_id, base)

            room_type = ensure_room_type(row.get("room_type") or "Lecture room")

            Venue.objects.create(
                campus_id=campus_id,
                name=name,
                code=code,
                building=building,
                room_type=room_type,
                capacity=capacity,
                allows_parallel_sessions=parallel,
            )
            seen_names.add(name_key)
            saved += 1

        return Response(
            {
                "saved": saved,
                "error_count": len(errors),
                "errors": errors,
            }
        )


class VenueDetailView(APIView):
    permission_classes = [IsAuthenticated, ProgramSchedulingAPIPermission]

    def patch(self, request, pk):
        row = get_object_or_404(Venue.objects.select_related("campus"), pk=pk)
        if "name" in request.data:
            name = (request.data.get("name") or "").strip()
            if not name:
                return Response({"detail": "name cannot be empty."}, status=400)
            if (
                Venue.objects.filter(campus_id=row.campus_id, name__iexact=name)
                .exclude(pk=row.pk)
                .exists()
            ):
                return Response(
                    {"detail": f'A room named "{name}" already exists on this campus.'},
                    status=400,
                )
            row.name = name
        if "building" in request.data:
            row.building = (request.data.get("building") or "").strip()
        if "room_type" in request.data:
            row.room_type = ensure_room_type(request.data["room_type"])
        if "code" in request.data:
            code = (request.data.get("code") or "").strip()
            if code and (
                Venue.objects.filter(campus_id=row.campus_id, code__iexact=code)
                .exclude(pk=row.pk)
                .exists()
            ):
                return Response(
                    {"detail": f'Code "{code}" already exists on this campus.'},
                    status=400,
                )
            row.code = code
        elif request.data.get("auto_code"):
            base = suggest_venue_code(
                campus_code=row.campus.code,
                campus_name=row.campus.name,
                building=row.building,
                name=row.name,
            )
            row.code = unique_venue_code_for_campus(row.campus_id, base, exclude_venue_id=row.pk)
        if "is_active" in request.data:
            row.is_active = bool(request.data["is_active"])
        if "capacity" in request.data:
            cap = request.data.get("capacity")
            row.capacity = int(cap) if cap not in (None, "") else None
        if "allows_parallel_sessions" in request.data:
            row.allows_parallel_sessions = bool(request.data["allows_parallel_sessions"])
        row.save()
        return Response(_serialize_venue(row))

    def delete(self, request, pk):
        row = get_object_or_404(Venue, pk=pk)
        if row.timetable_sessions.filter(is_active=True).exists():
            row.is_active = False
            row.save(update_fields=["is_active", "updated_at"])
            return Response({"detail": "Room in use on timetables; marked inactive."})
        row.delete()
        return Response(status=204)


class SemesterTimetableView(APIView):
    """GET full timetable for a semester; POST create session."""

    permission_classes = [IsAuthenticated, ProgramSchedulingAPIPermission]

    def get(self, request, semester_id):
        semester = get_object_or_404(
            Semester.objects.select_related("program_batch__program").prefetch_related(
                "program_batch__program__campuses"
            ),
            pk=semester_id,
            is_active=True,
        )
        assert_semester_access(request.user, semester)
        batch = semester.program_batch
        program = batch.program
        campuses, suggested_campus_id = resolve_semester_campuses(semester)

        campus_filter = request.query_params.get("campus_id") or suggested_campus_id
        sessions = sessions_for_semester(semester.id)
        by_unit: dict[int, list] = {}
        for s in sessions:
            by_unit.setdefault(s.course_unit_id, []).append(serialize_session(s))

        units = (
            CourseUnit.objects.filter(semester_id=semester.id, is_active=True)
            .select_related("catalog_unit")
            .prefetch_related("lecturers")
            .order_by("code")
        )
        course_units = []
        for cu in units:
            cat = cu.catalog_unit
            course_units.append(
                {
                    "id": cu.id,
                    "code": cu.code,
                    "name": cu.name,
                    "credit_units": float(cu.credit_units) if cu.credit_units else None,
                    "catalog_unit_id": cat.id if cat else None,
                    "catalog_code": cat.code if cat else "",
                    "sessions": by_unit.get(cu.id, []),
                }
            )

        venues_qs = Venue.objects.filter(is_active=True).select_related("campus")
        if campus_filter:
            venues_qs = venues_qs.filter(campus_id=campus_filter)
        else:
            # Restrict to program's allowed campuses only
            allowed_campus_ids = list(program.campuses.values_list("id", flat=True))
            if allowed_campus_ids:
                venues_qs = venues_qs.filter(campus_id__in=allowed_campus_ids)

        return Response(
            {
                "semester": {
                    "id": semester.id,
                    "name": semester.name,
                    "year_of_study": semester.year_of_study,
                    "term_number": semester.term_number,
                    "start_date": semester.start_date.isoformat() if semester.start_date else "",
                    "end_date": semester.end_date.isoformat() if semester.end_date else "",
                },
                "batch": {"id": batch.id, "name": batch.name, "academic_year": batch.academic_year},
                "program": {
                    "id": program.id,
                    "name": program.name,
                    "short_form": program.short_form,
                },
                "campuses": campuses,
                "suggested_campus_id": suggested_campus_id,
                "course_units": course_units,
                "sessions": [serialize_session(s) for s in sessions],
                "venues": [_serialize_venue(v) for v in venues_qs],
                "catalog_overview": build_catalog_overview(sessions),
                "teaching_load": compute_teaching_load(
                    sessions
                    if request.query_params.get("teaching_load") == "all"
                    else [s for s in sessions if s.is_published]
                ),
            }
        )

    def post(self, request, semester_id):
        semester = get_object_or_404(Semester, pk=semester_id, is_active=True)
        assert_semester_access(request.user, semester)
        course_unit_id = request.data.get("course_unit_id")
        if not course_unit_id:
            return Response({"detail": "course_unit_id is required."}, status=400)

        course_unit = get_object_or_404(
            CourseUnit,
            pk=course_unit_id,
            semester_id=semester.id,
            is_active=True,
        )

        try:
            session_date = _parse_date(request.data.get("session_date"), "session_date")
            day = session_date.weekday() + 1
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)

        try:
            start_time = _parse_time(request.data.get("start_time"), "start_time")
            end_time = _parse_time(request.data.get("end_time"), "end_time")
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)

        if end_time <= start_time:
            return Response({"detail": "end_time must be after start_time."}, status=400)

        venue_id = request.data.get("venue_id") or None
        venue = None
        if venue_id:
            venue = get_object_or_404(Venue, pk=venue_id, is_active=True)

        session_type = (request.data.get("session_type") or "lecture").strip().lower()
        valid_types = {c[0] for c in TimetableSession.SESSION_TYPE_CHOICES}
        if session_type not in valid_types:
            return Response(
                {"detail": f"session_type must be one of: {', '.join(sorted(valid_types))}."},
                status=400,
            )

        try:
            delivery_mode = parse_delivery_mode(request.data.get("delivery_mode"))
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)

        is_published = bool(request.data.get("is_published", True))
        session = TimetableSession(
            course_unit=course_unit,
            day_of_week=day,
            session_date=session_date,
            start_time=start_time,
            end_time=end_time,
            venue=venue,
            room_label=(request.data.get("room_label") or "").strip(),
            session_type=session_type,
            delivery_mode=delivery_mode,
            notes=(request.data.get("notes") or "").strip(),
            is_published=is_published,
        )

        validation = validate_session_scheduling(session, require_venue=True)
        if not validation.ok:
            return _validation_response(validation)

        session.full_clean()
        session.save()

        data = serialize_session(session)
        data["warnings"] = validation.warnings
        data["clashes"] = validation.clashes
        return Response(data, status=201)


class SemesterTimetablePdfView(APIView):
    """Admin/faculty PDF of a semester teaching timetable (for reporting / notice boards)."""

    permission_classes = [IsAuthenticated, ProgramSchedulingAPIPermission]

    def get(self, request, semester_id):
        semester = get_object_or_404(
            Semester.objects.select_related("program_batch__program"),
            pk=semester_id,
            is_active=True,
        )
        assert_semester_access(request.user, semester)
        batch = semester.program_batch
        program = batch.program

        include_drafts = str(request.query_params.get("include_drafts") or "").lower() in {
            "1",
            "true",
            "yes",
            "all",
        }
        sessions = sessions_for_semester(semester.id, published_only=not include_drafts)
        serialized = [serialize_session(s) for s in sessions]

        period = ""
        if semester.start_date and semester.end_date:
            period = (
                f"{semester.start_date.strftime('%d %b %Y')} – "
                f"{semester.end_date.strftime('%d %b %Y')}"
            )
        extra_lines = [
            f"Programme: {program.name}",
            f"Batch: {batch.name}"
            + (f" ({batch.academic_year})" if batch.academic_year else ""),
            f"Semester: {semester.name}",
        ]
        if period:
            extra_lines.append(f"Period: {period}")
        extra_lines.append(
            "Includes draft slots" if include_drafts else "Published slots only"
        )

        context = build_timetable_pdf_context(
            title="Teaching Timetable",
            person_name=program.short_form or program.name,
            person_subtitle=f"{batch.name} · {semester.name}",
            sessions=serialized,
            extra_lines=extra_lines,
        )
        if include_drafts:
            context["disclaimer"] = (
                "This timetable includes draft (unpublished) slots for internal reporting. "
                "Confirm publication status before posting for students."
            )
        else:
            context["disclaimer"] = (
                "This timetable shows published teaching sessions for this semester cohort."
            )

        try:
            pdf_bytes = render_timetable_pdf(context)
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=500)

        filename = safe_pdf_filename(
            "timetable",
            f"{program.short_form or program.code or program.id}_{batch.name}_{semester.name}",
        )
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class SemesterTeachingLoadPdfView(APIView):
    """Admin/faculty PDF of lecturer teaching load for a semester (reporting)."""

    permission_classes = [IsAuthenticated, ProgramSchedulingAPIPermission]

    def get(self, request, semester_id):
        semester = get_object_or_404(
            Semester.objects.select_related("program_batch__program"),
            pk=semester_id,
            is_active=True,
        )
        assert_semester_access(request.user, semester)
        batch = semester.program_batch
        program = batch.program

        include_drafts = str(request.query_params.get("include_drafts") or "").lower() in {
            "1",
            "true",
            "yes",
            "all",
        }
        sessions = sessions_for_semester(semester.id, published_only=not include_drafts)
        load_rows = compute_teaching_load(sessions)

        context = build_teaching_load_pdf_context(
            title="Teaching Load Report",
            program_name=program.name,
            batch_name=batch.name,
            semester_name=semester.name,
            academic_year=batch.academic_year or "",
            load_rows=load_rows,
            include_drafts=include_drafts,
            extra_lines=[
                f"Prepared for: {request.user.get_full_name() or request.user.username}",
            ],
        )
        try:
            pdf_bytes = render_teaching_load_pdf(context)
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=500)

        filename = safe_pdf_filename(
            "teaching_load",
            f"{program.short_form or program.code or program.id}_{batch.name}_{semester.name}",
        )
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class SemesterTimetableBulkPublishView(APIView):
    """Publish or unpublish all timetable sessions for a semester."""

    permission_classes = [IsAuthenticated, ProgramSchedulingAPIPermission]

    def post(self, request, semester_id):
        semester = get_object_or_404(Semester, pk=semester_id, is_active=True)
        assert_semester_access(request.user, semester)
        action = (request.data.get("action") or "").strip().lower()
        if action not in ("publish_all", "unpublish_all"):
            return Response(
                {"detail": 'action must be "publish_all" or "unpublish_all".'},
                status=400,
            )

        qs = (
            TimetableSession.objects.filter(
                is_active=True,
                course_unit__semester_id=semester_id,
                course_unit__is_active=True,
            )
            .select_related("course_unit", "course_unit__catalog_unit", "venue", "venue__campus")
            .prefetch_related("course_unit__lecturers")
        )

        if action == "unpublish_all":
            count = qs.filter(is_published=True).update(is_published=False)
            return Response(
                {
                    "action": action,
                    "unpublished_count": count,
                    "message": f"{count} session(s) set to draft.",
                }
            )

        published_count = 0
        skipped: list[dict] = []
        for session in qs.filter(is_published=False):
            session.is_published = True
            validation = validate_session_scheduling(session, require_venue=True)
            if not validation.ok:
                session.is_published = False
                skipped.append(
                    {
                        "session_id": session.id,
                        "course_code": session.course_unit.code,
                        "errors": validation.errors,
                    }
                )
            else:
                session.save(update_fields=["is_published", "updated_at"])
                published_count += 1

        return Response(
            {
                "action": action,
                "published_count": published_count,
                "skipped": skipped,
                "message": (
                    f"Published {published_count} session(s)."
                    + (f" {len(skipped)} could not be published (fix conflicts first)." if skipped else "")
                ),
            }
        )


class TimetableSessionDetailView(APIView):
    permission_classes = [IsAuthenticated, ProgramSchedulingAPIPermission]

    def patch(self, request, pk):
        session = get_object_or_404(
            TimetableSession.objects.select_related("course_unit", "venue", "venue__campus"),
            pk=pk,
        )
        assert_timetable_session_access(request.user, session)

        if "session_date" in request.data:
            try:
                session_date = _parse_date(request.data.get("session_date"), "session_date")
            except ValueError as exc:
                return Response({"detail": str(exc)}, status=400)
            session.session_date = session_date
            session.day_of_week = session_date.weekday() + 1
        elif "day_of_week" in request.data:
            day = int(request.data["day_of_week"])
            if day not in range(1, 8):
                return Response({"detail": "day_of_week must be 1-7."}, status=400)
            session.day_of_week = day

        if "start_time" in request.data:
            session.start_time = _parse_time(request.data["start_time"], "start_time")
        if "end_time" in request.data:
            session.end_time = _parse_time(request.data["end_time"], "end_time")
        if session.end_time <= session.start_time:
            return Response({"detail": "end_time must be after start_time."}, status=400)

        if "venue_id" in request.data:
            vid = request.data.get("venue_id")
            if vid:
                session.venue = get_object_or_404(Venue, pk=vid, is_active=True)
            else:
                session.venue = None
        if "room_label" in request.data:
            session.room_label = (request.data.get("room_label") or "").strip()
        if "session_type" in request.data:
            session.session_type = request.data["session_type"]
        if "delivery_mode" in request.data:
            try:
                session.delivery_mode = parse_delivery_mode(request.data.get("delivery_mode"))
            except ValueError as exc:
                return Response({"detail": str(exc)}, status=400)
        if "notes" in request.data:
            session.notes = (request.data.get("notes") or "").strip()
        if "is_published" in request.data:
            session.is_published = bool(request.data["is_published"])
        if "is_active" in request.data:
            session.is_active = bool(request.data["is_active"])

        validation = validate_session_scheduling(session, exclude_pk=session.pk, require_venue=True)
        if not validation.ok:
            return _validation_response(validation)

        session.full_clean()
        session.save()

        data = serialize_session(session)
        data["warnings"] = validation.warnings
        data["clashes"] = validation.clashes
        return Response(data)

    def delete(self, request, pk):
        session = get_object_or_404(
            TimetableSession.objects.select_related("course_unit__program_batch__program"),
            pk=pk,
        )
        assert_timetable_session_access(request.user, session)
        session.is_active = False
        session.save(update_fields=["is_active", "updated_at"])
        return Response(status=204)


def _student_timetable_sessions(user, semester_id=None):
    from admissions.models import AdmittedStudent
    from Programs.models import StudentCourseUnitEnrollment

    student = (
        AdmittedStudent.objects.filter(
            student_user_id=user.id,
            is_admitted=True,
        )
        .select_related("application", "admitted_program")
        .first()
    )
    if not student:
        return None, []

    enrollments = StudentCourseUnitEnrollment.objects.filter(
        student=student,
        status="enrolled",
        course_unit__is_active=True,
    )
    if semester_id:
        enrollments = enrollments.filter(course_unit__semester_id=semester_id)

    unit_ids = list(enrollments.values_list("course_unit_id", flat=True).distinct())
    if not unit_ids:
        return student, []

    sessions = (
        TimetableSession.objects.filter(
            is_active=True,
            is_published=True,
            course_unit_id__in=unit_ids,
        )
        .select_related(
            "course_unit",
            "course_unit__catalog_unit",
            "course_unit__semester",
            "venue",
            "venue__campus",
        )
        .prefetch_related("course_unit__lecturers")
        .order_by("day_of_week", "start_time")
    )
    return student, list(sessions)


def _lecturer_timetable_sessions(user, semester_id=None):
    assigned_ids = list(
        user.course_units.filter(is_active=True).values_list("id", flat=True).distinct()
    )
    if not assigned_ids:
        return []

    qs = TimetableSession.objects.filter(
        is_active=True,
        is_published=True,
        course_unit_id__in=assigned_ids,
    ).select_related(
        "course_unit",
        "course_unit__catalog_unit",
        "venue",
        "venue__campus",
        "course_unit__semester",
    )
    if semester_id:
        qs = qs.filter(course_unit__semester_id=semester_id)

    return list(
        qs.prefetch_related("course_unit__lecturers")
        .distinct()
        .order_by("day_of_week", "start_time")
    )


class StudentMyTimetableView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        semester_id = request.query_params.get("semester_id")
        student, sessions = _student_timetable_sessions(request.user, semester_id=semester_id)
        if not student:
            return Response({"detail": "Student record not found."}, status=404)
        return Response({"sessions": [serialize_session(s) for s in sessions]})


class StudentMyTimetablePdfView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        semester_id = request.query_params.get("semester_id")
        student, sessions = _student_timetable_sessions(request.user, semester_id=semester_id)
        if not student:
            return Response({"detail": "Student record not found."}, status=404)

        program_name = getattr(student.admitted_program, "name", "") or ""
        extra_lines = [f"Reg. No: {student.reg_no}"]
        if program_name:
            extra_lines.append(f"Programme: {program_name}")

        context = build_timetable_pdf_context(
            title="My Teaching Timetable",
            person_name=student.full_name,
            person_subtitle="Student",
            sessions=[serialize_session(s) for s in sessions],
            extra_lines=extra_lines,
        )
        pdf_bytes = render_timetable_pdf(context)
        filename = safe_pdf_filename("student_timetable", student.reg_no)
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class LecturerMyTimetableView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        is_lecturer = bool(getattr(user, "is_lecturer", False)) or user.course_units.exists()
        if not is_lecturer and not user.is_staff:
            return Response({"detail": "Lecturer access only."}, status=403)

        semester_id = request.query_params.get("semester_id")
        sessions = _lecturer_timetable_sessions(request.user, semester_id=semester_id)
        return Response({"sessions": [serialize_session(s) for s in sessions]})


class LecturerMyTimetablePdfView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        is_lecturer = bool(getattr(user, "is_lecturer", False)) or user.course_units.exists()
        if not is_lecturer and not user.is_staff:
            return Response({"detail": "Lecturer access only."}, status=403)

        semester_id = request.query_params.get("semester_id")
        sessions = _lecturer_timetable_sessions(request.user, semester_id=semester_id)
        user = request.user
        person_name = user.get_full_name() or user.username
        extra_lines = []
        if user.email:
            extra_lines.append(f"Email: {user.email}")

        context = build_timetable_pdf_context(
            title="My Teaching Timetable",
            person_name=person_name,
            person_subtitle="Lecturer",
            sessions=[serialize_session(s) for s in sessions],
            extra_lines=extra_lines,
        )
        pdf_bytes = render_timetable_pdf(context)
        filename = safe_pdf_filename("lecturer_timetable", user.username)
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
