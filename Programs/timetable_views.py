"""Timetable APIs: venues (classrooms), semester sessions, student/lecturer views."""
from __future__ import annotations

from datetime import datetime

from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Campus
from Programs.models import CourseUnit, RoomType, Semester, TimetableSession, Venue
from Programs.permissions import ProgramSchedulingAPIPermission
from Programs.venue_code_utils import (
    ensure_room_type,
    list_room_type_names,
    suggest_venue_code,
    unique_venue_code_for_campus,
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

        return Response(
            {
                "semester": {
                    "id": semester.id,
                    "name": semester.name,
                    "year_of_study": semester.year_of_study,
                    "term_number": semester.term_number,
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
            day = int(request.data.get("day_of_week"))
            if day not in range(1, 8):
                raise ValueError()
        except (TypeError, ValueError):
            return Response({"detail": "day_of_week must be 1-7 (Mon-Sun)."}, status=400)

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


class SemesterTimetableBulkPublishView(APIView):
    """Publish or unpublish all timetable sessions for a semester."""

    permission_classes = [IsAuthenticated, ProgramSchedulingAPIPermission]

    def post(self, request, semester_id):
        get_object_or_404(Semester, pk=semester_id, is_active=True)
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

        if "day_of_week" in request.data:
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
        session = get_object_or_404(TimetableSession, pk=pk)
        session.is_active = False
        session.save(update_fields=["is_active", "updated_at"])
        return Response(status=204)


class StudentMyTimetableView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from admissions.models import AdmittedStudent
        from Programs.models import StudentCourseUnitEnrollment

        student = AdmittedStudent.objects.filter(
            student_user_id=request.user.id,
            is_admitted=True,
        ).first()
        if not student:
            return Response({"detail": "Student record not found."}, status=404)

        semester_id = request.query_params.get("semester_id")
        enrollments = StudentCourseUnitEnrollment.objects.filter(
            student=student,
            status="enrolled",
            course_unit__is_active=True,
        ).select_related("course_unit__semester__program_batch__program")

        if semester_id:
            enrollments = enrollments.filter(course_unit__semester_id=semester_id)

        unit_ids = list(enrollments.values_list("course_unit_id", flat=True).distinct())
        if not unit_ids:
            return Response({"sessions": [], "course_units": []})

        sessions = (
            TimetableSession.objects.filter(
                is_active=True,
                is_published=True,
                course_unit_id__in=unit_ids,
            )
            .select_related("course_unit", "course_unit__catalog_unit", "venue", "venue__campus")
            .prefetch_related("course_unit__lecturers")
            .order_by("day_of_week", "start_time")
        )
        return Response({"sessions": [serialize_session(s) for s in sessions]})


class LecturerMyTimetableView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not getattr(request.user, "is_lecturer", False) and not request.user.is_staff:
            return Response({"detail": "Lecturer access only."}, status=403)

        semester_id = request.query_params.get("semester_id")
        qs = TimetableSession.objects.filter(
            is_active=True,
            is_published=True,
            course_unit__lecturers=request.user,
            course_unit__is_active=True,
        ).select_related(
            "course_unit",
            "course_unit__catalog_unit",
            "venue",
            "venue__campus",
            "course_unit__semester",
        )
        if semester_id:
            qs = qs.filter(course_unit__semester_id=semester_id)

        sessions = qs.prefetch_related("course_unit__lecturers").order_by(
            "day_of_week", "start_time"
        )
        return Response({"sessions": [serialize_session(s) for s in sessions]})
