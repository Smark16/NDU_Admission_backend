from datetime import date

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from admissions.models import AdmittedStudent
from admissions.registration_workflow import student_curriculum_year_term

from .eligibility import student_hostel_eligibility
from .models import Bed, Building, Floor, Hostel, HostelAllocation, Room
from .permissions import (
    CanAccessHostel,
    CanAssignHostel,
    CanEndAllocation,
    CanManageInventory,
    CanViewHostelReports,
)
from .serializers import (
    BedSerializer,
    BuildingSerializer,
    FloorSerializer,
    HostelAllocationSerializer,
    HostelSerializer,
    RoomSerializer,
)
from .services import assign_bed, end_allocation, transfer_bed


def _student_base_qs():
    return AdmittedStudent.objects.select_related(
        "application", "admitted_campus", "admitted_program"
    )


def _student_display_name(student: AdmittedStudent) -> str:
    app = getattr(student, "application", None)
    if app:
        parts = [
            getattr(app, "first_name", "") or "",
            getattr(app, "middle_name", "") or "",
            getattr(app, "last_name", "") or "",
        ]
        name = " ".join(p for p in parts if p).strip()
        if name:
            return name
    return student.reg_no or student.student_id or str(student.pk)


def search_admitted_students(identifier, *, limit: int = 20):
    """
    Find admitted students by pk, student_id, reg_no, or name.
    Exact id/reg matches first; name matches are partial (icontains).
    """
    raw = str(identifier or "").strip()
    if not raw:
        return []
    qs = _student_base_qs().filter(is_admitted=True)
    if raw.isdigit():
        found = qs.filter(pk=int(raw)).first()
        if found:
            return [found]
    exact = list(
        qs.filter(Q(student_id__iexact=raw) | Q(reg_no__iexact=raw))[:limit]
    )
    if exact:
        return exact
    compact = " ".join(raw.split())
    exact = list(
        qs.filter(Q(student_id__iexact=compact) | Q(reg_no__iexact=compact))[:limit]
    )
    if exact:
        return exact

    # Name search — supports full or partial names (e.g. "Alyao", "Jacqueline Alyao").
    tokens = [t for t in compact.split() if t]
    name_q = Q()
    for token in tokens:
        name_q &= (
            Q(application__first_name__icontains=token)
            | Q(application__middle_name__icontains=token)
            | Q(application__last_name__icontains=token)
        )
    # Also allow matching against student_id / reg_no substrings.
    loose = (
        Q(student_id__icontains=compact)
        | Q(reg_no__icontains=compact)
        | name_q
    )
    return list(qs.filter(loose).distinct()[:limit])


def resolve_admitted_student(identifier):
    """Return a single match, or None if zero/ambiguous."""
    matches = search_admitted_students(identifier, limit=5)
    if len(matches) == 1:
        return matches[0]
    return None


def _allocation_qs():
    return HostelAllocation.objects.select_related(
        "student",
        "student__application",
        "student__admitted_program",
        "student__admitted_program__faculty",
        "student__admitted_campus",
        "bed",
        "bed__room",
        "bed__room__floor",
        "bed__room__floor__building",
        "bed__room__floor__building__hostel",
        "assigned_by",
    )


class HostelListView(APIView):
    permission_classes = [IsAuthenticated, CanManageInventory]

    def get(self, request):
        qs = Hostel.objects.select_related("campus").all()
        campus_id = request.query_params.get("campus")
        if campus_id:
            qs = qs.filter(campus_id=campus_id)
        gender = request.query_params.get("gender")
        if gender:
            qs = qs.filter(gender=gender)
        return Response(HostelSerializer(qs, many=True).data)


class BuildingListView(APIView):
    permission_classes = [IsAuthenticated, CanManageInventory]

    def get(self, request):
        qs = Building.objects.select_related("hostel", "hostel__campus").all()
        hostel_id = request.query_params.get("hostel")
        if hostel_id:
            qs = qs.filter(hostel_id=hostel_id)
        campus_id = request.query_params.get("campus")
        if campus_id:
            qs = qs.filter(hostel__campus_id=campus_id)
        return Response(BuildingSerializer(qs, many=True).data)

    def post(self, request):
        hostel_id = request.data.get("hostel")
        code = (request.data.get("code") or "").strip()
        name = (request.data.get("name") or "").strip()
        if not hostel_id or not code or not name:
            return Response(
                {"detail": "hostel, code, and name are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        hostel = get_object_or_404(Hostel, pk=hostel_id)
        if Building.objects.filter(hostel=hostel, code__iexact=code).exists():
            return Response(
                {"code": f'Building code "{code}" already exists in this hostel.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        building = Building.objects.create(
            hostel=hostel,
            code=code.upper().replace(" ", "_"),
            name=name,
            external_block_id=request.data.get("external_block_id") or "",
            is_active=bool(request.data.get("is_active", True)),
        )
        return Response(
            BuildingSerializer(building).data, status=status.HTTP_201_CREATED
        )


class FloorListView(APIView):
    permission_classes = [IsAuthenticated, CanManageInventory]

    def get(self, request):
        qs = Floor.objects.select_related("building").all()
        building_id = request.query_params.get("building")
        if building_id:
            qs = qs.filter(building_id=building_id)
        return Response(FloorSerializer(qs, many=True).data)

    def post(self, request):
        building_id = request.data.get("building")
        code = (request.data.get("code") or "").strip()
        name = (request.data.get("name") or "").strip() or code
        if not building_id or not code:
            return Response(
                {"detail": "building and code are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        building = get_object_or_404(Building, pk=building_id)
        if Floor.objects.filter(building=building, code__iexact=code).exists():
            return Response(
                {"code": f'Floor code "{code}" already exists in this building.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        sort_order = request.data.get("sort_order", 50)
        try:
            sort_order = int(sort_order)
        except (TypeError, ValueError):
            sort_order = 50
        floor = Floor.objects.create(
            building=building,
            code=code,
            name=name,
            sort_order=sort_order,
        )
        return Response(FloorSerializer(floor).data, status=status.HTTP_201_CREATED)


def _room_qs():
    return Room.objects.select_related(
        "floor",
        "floor__building",
        "floor__building__hostel",
    ).prefetch_related("beds")


class RoomListView(APIView):
    permission_classes = [IsAuthenticated, CanManageInventory]

    def get(self, request):
        qs = _room_qs()
        building_id = request.query_params.get("building")
        floor_id = request.query_params.get("floor")
        hostel_id = request.query_params.get("hostel")
        kind = request.query_params.get("room_kind")
        q = (request.query_params.get("q") or "").strip()
        available_only = request.query_params.get("available_only", "").lower() in (
            "1",
            "true",
            "yes",
        )
        if building_id:
            qs = qs.filter(floor__building_id=building_id)
        if floor_id:
            qs = qs.filter(floor_id=floor_id)
        if hostel_id:
            qs = qs.filter(floor__building__hostel_id=hostel_id)
        if kind:
            qs = qs.filter(room_kind=kind)
        if q:
            qs = qs.filter(Q(code__icontains=q) | Q(display_name__icontains=q))
        if available_only:
            qs = qs.filter(
                room_kind=Room.KIND_BEDROOM,
                beds__status=Bed.STATUS_AVAILABLE,
            ).distinct()
        return Response(RoomSerializer(qs, many=True).data)

    def post(self, request):
        from .inventory_ops import create_room
        from rest_framework.exceptions import ValidationError as DRFValidationError

        floor_id = request.data.get("floor")
        if not floor_id:
            return Response(
                {"detail": "floor is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        floor = get_object_or_404(Floor, pk=floor_id)
        try:
            room = create_room(
                floor=floor,
                code=request.data.get("code") or "",
                display_name=request.data.get("display_name") or "",
                room_kind=request.data.get("room_kind") or Room.KIND_BEDROOM,
                capacity=request.data.get("capacity", 4),
                notes=request.data.get("notes") or "",
                is_active=bool(request.data.get("is_active", True)),
            )
        except DRFValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            RoomSerializer(_room_qs().get(pk=room.pk)).data,
            status=status.HTTP_201_CREATED,
        )


class RoomDetailView(APIView):
    permission_classes = [IsAuthenticated, CanManageInventory]

    def get(self, request, room_id):
        room = get_object_or_404(_room_qs(), pk=room_id)
        return Response(RoomSerializer(room).data)

    def patch(self, request, room_id):
        from .inventory_ops import update_room
        from rest_framework.exceptions import ValidationError as DRFValidationError

        room = get_object_or_404(_room_qs(), pk=room_id)
        payload = {}
        for key in (
            "code",
            "display_name",
            "room_kind",
            "capacity",
            "notes",
            "is_active",
        ):
            if key in request.data:
                payload[key] = request.data.get(key)
        if "floor" in request.data:
            payload["floor_id"] = request.data.get("floor")
        try:
            room = update_room(room, **payload)
        except DRFValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)
        return Response(RoomSerializer(_room_qs().get(pk=room.pk)).data)

    def delete(self, request, room_id):
        from .inventory_ops import delete_room
        from rest_framework.exceptions import ValidationError as DRFValidationError

        room = get_object_or_404(Room, pk=room_id)
        try:
            result = delete_room(room)
        except DRFValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)
        return Response(result, status=status.HTTP_200_OK)


class BedDetailView(APIView):
    permission_classes = [IsAuthenticated, CanManageInventory]

    def patch(self, request, bed_id):
        from .inventory_ops import update_bed
        from rest_framework.exceptions import ValidationError as DRFValidationError

        bed = get_object_or_404(Bed.objects.select_related("room"), pk=bed_id)
        try:
            bed = update_bed(
                bed,
                status=request.data.get("status"),
                label=request.data.get("label"),
            )
        except DRFValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)
        return Response(BedSerializer(bed).data)


class BuildingDetailView(APIView):
    permission_classes = [IsAuthenticated, CanManageInventory]

    def patch(self, request, building_id):
        building = get_object_or_404(
            Building.objects.select_related("hostel"), pk=building_id
        )
        if "name" in request.data:
            name = (request.data.get("name") or "").strip()
            if not name:
                return Response(
                    {"name": "Name is required."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            building.name = name
        if "is_active" in request.data:
            building.is_active = bool(request.data.get("is_active"))
        if "code" in request.data:
            code = (request.data.get("code") or "").strip().upper().replace(" ", "_")
            if (
                Building.objects.filter(hostel=building.hostel, code__iexact=code)
                .exclude(pk=building.pk)
                .exists()
            ):
                return Response(
                    {"code": f'Building code "{code}" already exists.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            building.code = code
        building.save()
        return Response(BuildingSerializer(building).data)


class InventorySummaryView(APIView):
    permission_classes = [IsAuthenticated, CanAccessHostel]

    def get(self, request):
        rooms = Room.objects.filter(room_kind=Room.KIND_BEDROOM, is_active=True)
        beds = Bed.objects.filter(room__room_kind=Room.KIND_BEDROOM, room__is_active=True)
        by_building = (
            Building.objects.filter(is_active=True)
            .annotate(
                room_count=Count(
                    "floors__rooms",
                    filter=Q(floors__rooms__room_kind=Room.KIND_BEDROOM),
                    distinct=True,
                ),
                bed_count=Count(
                    "floors__rooms__beds",
                    filter=Q(floors__rooms__room_kind=Room.KIND_BEDROOM),
                    distinct=True,
                ),
                occupied=Count(
                    "floors__rooms__beds",
                    filter=Q(
                        floors__rooms__room_kind=Room.KIND_BEDROOM,
                        floors__rooms__beds__status=Bed.STATUS_OCCUPIED,
                    ),
                    distinct=True,
                ),
            )
            .select_related("hostel")
            .order_by("hostel__name", "name")
        )
        return Response(
            {
                "hostels": Hostel.objects.filter(is_active=True).count(),
                "buildings": Building.objects.filter(is_active=True).count(),
                "rooms": rooms.count(),
                "beds": beds.count(),
                "occupied_beds": beds.filter(status=Bed.STATUS_OCCUPIED).count(),
                "available_beds": beds.filter(status=Bed.STATUS_AVAILABLE).count(),
                "by_building": [
                    {
                        "id": b.id,
                        "name": b.name,
                        "code": b.code,
                        "hostel": b.hostel.name,
                        "gender": b.hostel.gender,
                        "rooms": b.room_count,
                        "beds": b.bed_count,
                        "occupied": b.occupied,
                        "available": max(0, b.bed_count - b.occupied),
                    }
                    for b in by_building
                ],
            }
        )


class InventoryImportView(APIView):
    """Upload Halls of Residence .xlsx or .csv from the ERP (no server scp needed)."""

    permission_classes = [IsAuthenticated, CanManageInventory]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        from rest_framework.exceptions import ValidationError as DRFValidationError

        from .import_rooms import import_hostel_file

        upload = request.FILES.get("file")
        if not upload:
            return Response(
                {"detail": "Attach a file field named 'file' (.xlsx or .csv)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        name = (upload.name or "").lower()
        if not (name.endswith(".xlsx") or name.endswith(".xlsm") or name.endswith(".csv")):
            return Response(
                {"detail": "Only .xlsx or .csv files are accepted."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        dry_run = str(request.data.get("dry_run", "")).lower() in ("1", "true", "yes")
        try:
            stats = import_hostel_file(upload, filename=upload.name, dry_run=dry_run)
        except DRFValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response(
                {"detail": f"Import failed: {exc}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"ok": True, "dry_run": dry_run, "stats": stats})



class StudentEligibilityView(APIView):
    """
    GET /api/hostel/students/<pk>/eligibility/
    GET /api/hostel/students/eligibility/?q=<pk|student_id|reg_no>
    """

    permission_classes = [IsAuthenticated, CanAssignHostel]

    def get(self, request, student_id=None):
        lookup = student_id if student_id is not None else (
            request.query_params.get("q")
            or request.query_params.get("student")
            or request.query_params.get("student_id")
        )
        if not lookup:
            return Response(
                {
                    "detail": (
                        "Provide student name, pk, student number, or reg. no. (?q=...)."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Path pk is always unique; query search may return multiple name matches.
        if student_id is not None:
            matches = search_admitted_students(student_id, limit=1)
        else:
            matches = search_admitted_students(lookup, limit=20)

        if not matches:
            return Response(
                {
                    "detail": (
                        f"No admitted student found for '{lookup}'. "
                        "Try name, numeric id, student number, or reg. no."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        if len(matches) > 1:
            return Response(
                {
                    "ambiguous": True,
                    "detail": (
                        f"Multiple students match '{lookup}'. Pick one from the list."
                    ),
                    "matches": [
                        {
                            "student_id": s.pk,
                            "student_number": s.student_id,
                            "reg_no": s.reg_no,
                            "name": _student_display_name(s),
                            "program": (
                                s.admitted_program.name if s.admitted_program_id else None
                            ),
                            "campus": (
                                s.admitted_campus.name if s.admitted_campus_id else None
                            ),
                        }
                        for s in matches
                    ],
                }
            )

        student = matches[0]
        elig = student_hostel_eligibility(student)
        active = (
            _allocation_qs()
            .filter(student=student, status=HostelAllocation.STATUS_ACTIVE)
            .first()
        )
        return Response(
            {
                **elig,
                "student_id": student.pk,
                "student_number": student.student_id,
                "reg_no": student.reg_no,
                "name": _student_display_name(student),
                "active_allocation": HostelAllocationSerializer(active).data if active else None,
            }
        )


class AssignBedView(APIView):
    permission_classes = [IsAuthenticated, CanAssignHostel]

    def post(self, request):
        student_id = request.data.get("student_id") or request.data.get("student")
        bed_id = request.data.get("bed_id")
        academic_year = request.data.get("academic_year")
        term_number = request.data.get("term_number")
        notes = request.data.get("notes") or ""
        check_in = request.data.get("check_in")

        if not student_id or not bed_id:
            return Response(
                {"detail": "student_id and bed_id are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        student = resolve_admitted_student(student_id)
        if student is None:
            return Response(
                {
                    "detail": (
                        f"No admitted student found for '{student_id}'. "
                        "Use pk, student number, or reg. no."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        bed = get_object_or_404(
            Bed.objects.select_related(
                "room",
                "room__floor",
                "room__floor__building",
                "room__floor__building__hostel",
            ),
            pk=bed_id,
        )

        if not academic_year or term_number in (None, ""):
            year, term = student_curriculum_year_term(student)
            # Prefer programme batch academic year label when available
            academic_year = academic_year or _default_academic_year(student)
            term_number = term_number if term_number not in (None, "") else term

        parsed_check_in = None
        if check_in:
            try:
                parsed_check_in = date.fromisoformat(str(check_in)[:10])
            except ValueError:
                return Response(
                    {"detail": "check_in must be YYYY-MM-DD."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        try:
            allocation = assign_bed(
                student=student,
                bed=bed,
                academic_year=str(academic_year),
                term_number=term_number,
                user=request.user,
                check_in=parsed_check_in,
                notes=notes,
            )
        except Exception as exc:
            from rest_framework.exceptions import ValidationError as DRFValidationError

            if isinstance(exc, DRFValidationError):
                return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)
            raise

        return Response(
            HostelAllocationSerializer(_allocation_qs().get(pk=allocation.pk)).data,
            status=status.HTTP_201_CREATED,
        )


def _default_academic_year(student: AdmittedStudent) -> str:
    batch = getattr(student, "intended_program_batch", None) or getattr(
        student, "admitted_batch", None
    )
    # Prefer ProgramBatch.academic_year via programme enrollment
    try:
        enr = student.programme_enrollment
        pb = getattr(enr, "program_batch", None)
        if pb and getattr(pb, "academic_year", None):
            return pb.academic_year
    except Exception:
        pass
    if batch and getattr(batch, "name", None):
        return str(batch.name)[:32]
    from admissions.models import AcademicYear

    current = AcademicYear.objects.filter(is_current=True).first()
    if current:
        return current.label
    return str(date.today().year)


class EndAllocationView(APIView):
    permission_classes = [IsAuthenticated, CanEndAllocation]

    def post(self, request, allocation_id):
        allocation = get_object_or_404(_allocation_qs(), pk=allocation_id)
        notes = request.data.get("notes") or ""
        check_out = request.data.get("check_out")
        parsed = None
        if check_out:
            try:
                parsed = date.fromisoformat(str(check_out)[:10])
            except ValueError:
                return Response(
                    {"detail": "check_out must be YYYY-MM-DD."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        try:
            end_allocation(
                allocation,
                user=request.user,
                notes=notes,
                check_out=parsed,
            )
        except Exception as exc:
            from rest_framework.exceptions import ValidationError as DRFValidationError

            if isinstance(exc, DRFValidationError):
                return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)
            raise
        return Response(
            HostelAllocationSerializer(_allocation_qs().get(pk=allocation.pk)).data
        )


class TransferAllocationView(APIView):
    permission_classes = [IsAuthenticated, CanAssignHostel]

    def post(self, request, allocation_id):
        allocation = get_object_or_404(_allocation_qs(), pk=allocation_id)
        bed_id = request.data.get("bed_id")
        if not bed_id:
            return Response(
                {"detail": "bed_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        new_bed = get_object_or_404(
            Bed.objects.select_related(
                "room",
                "room__floor",
                "room__floor__building",
                "room__floor__building__hostel",
            ),
            pk=bed_id,
        )
        notes = request.data.get("notes") or ""
        try:
            new_alloc = transfer_bed(
                allocation=allocation,
                new_bed=new_bed,
                user=request.user,
                notes=notes,
            )
        except Exception as exc:
            from rest_framework.exceptions import ValidationError as DRFValidationError

            if isinstance(exc, DRFValidationError):
                return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)
            raise
        return Response(
            HostelAllocationSerializer(_allocation_qs().get(pk=new_alloc.pk)).data,
            status=status.HTTP_201_CREATED,
        )


class OccupancyListView(APIView):
    permission_classes = [IsAuthenticated, CanAccessHostel]

    def get(self, request):
        qs = _allocation_qs().filter(status=HostelAllocation.STATUS_ACTIVE)
        building_id = request.query_params.get("building")
        hostel_id = request.query_params.get("hostel")
        q = (request.query_params.get("q") or "").strip()
        if building_id:
            qs = qs.filter(bed__room__floor__building_id=building_id)
        if hostel_id:
            qs = qs.filter(bed__room__floor__building__hostel_id=hostel_id)
        if q:
            qs = qs.filter(
                Q(student__reg_no__icontains=q)
                | Q(student__student_id__icontains=q)
                | Q(student__application__first_name__icontains=q)
                | Q(student__application__last_name__icontains=q)
                | Q(student__admitted_program__name__icontains=q)
                | Q(student__admitted_program__code__icontains=q)
                | Q(bed__room__code__icontains=q)
                | Q(bed__room__floor__building__name__icontains=q)
            )
        return Response(HostelAllocationSerializer(qs[:1000], many=True).data)


class ReadyQueueView(APIView):
    """FY Main Campus students cleared by Accounts+AR but with no active allocation."""

    permission_classes = [IsAuthenticated, CanAssignHostel]

    def get(self, request):
        from accounts.models import Campus

        main_campuses = Campus.objects.filter(
            Q(code__iexact="MAIN")
            | Q(name__icontains="Main")
            | Q(name__icontains="Ndejje")
        )
        qs = (
            AdmittedStudent.objects.filter(
                is_admitted=True,
                accounts_registration_cleared=True,
                physical_documents_verified=True,
                admitted_campus__in=main_campuses,
            )
            .exclude(hostel_allocations__status=HostelAllocation.STATUS_ACTIVE)
            .select_related("application", "admitted_campus", "admitted_program")
            .order_by("reg_no")
        )
        # Prefer Y1T1 via enrollment when present
        rows = []
        limit = int(request.query_params.get("limit") or 200)
        for s in qs[: limit * 3]:
            year, term = student_curriculum_year_term(s)
            if year != 1 or term != 1:
                continue
            app = s.application
            rows.append(
                {
                    "id": s.pk,
                    "reg_no": s.reg_no,
                    "student_id": s.student_id,
                    "name": (
                        " ".join(
                            p
                            for p in [
                                getattr(app, "first_name", "") or "",
                                getattr(app, "middle_name", "") or "",
                                getattr(app, "last_name", "") or "",
                            ]
                            if p
                        ).strip()
                        if app
                        else s.reg_no
                    ),
                    "gender": getattr(app, "gender", None) if app else None,
                    "campus": s.admitted_campus.name if s.admitted_campus_id else None,
                    "program": (
                        s.admitted_program.name if s.admitted_program_id else None
                    ),
                    "accounts_registration_cleared": True,
                    "physical_documents_verified": True,
                }
            )
            if len(rows) >= limit:
                break
        return Response({"count": len(rows), "results": rows})


class StudentMyRoomView(APIView):
    """Read-only current allocation for the logged-in student."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        student = (
            AdmittedStudent.objects.filter(
                Q(student_user=request.user)
                | Q(reg_no__iexact=request.user.username)
                | Q(student_id__iexact=request.user.username)
            )
            .select_related(
                "application",
                "admitted_program",
                "admitted_program__faculty",
                "admitted_campus",
            )
            .first()
        )
        if not student:
            return Response(
                {"detail": "No student profile linked to this account."},
                status=status.HTTP_404_NOT_FOUND,
            )
        active = (
            _allocation_qs()
            .filter(student=student, status=HostelAllocation.STATUS_ACTIVE)
            .first()
        )
        history = _allocation_qs().filter(student=student).exclude(
            status=HostelAllocation.STATUS_ACTIVE
        )[:10]

        roommates = []
        if active:
            others = (
                _allocation_qs()
                .filter(
                    status=HostelAllocation.STATUS_ACTIVE,
                    bed__room_id=active.bed.room_id,
                )
                .exclude(pk=active.pk)
            )
            for o in others:
                roommates.append(
                    {
                        "bed_label": o.bed.label,
                        "reg_no": o.student.reg_no,
                        "name": HostelAllocationSerializer().get_student_name(o),
                        "program": (
                            o.student.admitted_program.name
                            if o.student.admitted_program_id
                            else None
                        ),
                    }
                )

        prog = student.admitted_program
        return Response(
            {
                "student_id": student.pk,
                "reg_no": student.reg_no,
                "student_number": student.student_id,
                "program": prog.name if prog else None,
                "program_code": getattr(prog, "code", None) if prog else None,
                "faculty": (
                    prog.faculty.name if prog and prog.faculty_id else None
                ),
                "campus": (
                    student.admitted_campus.name if student.admitted_campus_id else None
                ),
                "active": HostelAllocationSerializer(active).data if active else None,
                "roommates": roommates,
                "history": HostelAllocationSerializer(history, many=True).data,
            }
        )


class StudentAllocationLookupView(APIView):
    """Staff: current allocation for a given AdmittedStudent pk."""

    permission_classes = [IsAuthenticated, CanAccessHostel]

    def get(self, request, student_id):
        student = get_object_or_404(AdmittedStudent, pk=student_id)
        active = (
            _allocation_qs()
            .filter(student=student, status=HostelAllocation.STATUS_ACTIVE)
            .first()
        )
        elig = student_hostel_eligibility(student)
        return Response(
            {
                "student_id": student.pk,
                "reg_no": student.reg_no,
                "eligibility": elig,
                "active": HostelAllocationSerializer(active).data if active else None,
            }
        )


class HostelFeeExemptionReportView(APIView):
    """
    Finance ops: students with active hostel allocation who still have an active
    hostel fee exemption, and students with hostel exemptions who have never been
    allocated (suggest keep) — and allocated without exemption gaps.
    """

    permission_classes = [IsAuthenticated, CanViewHostelReports]

    def get(self, request):
        from payments.models import FeeHead, StudentFeeExemption

        hostel_heads = FeeHead.objects.filter(
            Q(code__icontains="hostel")
            | Q(name__icontains="hostel")
            | Q(code__icontains="board")
            | Q(name__icontains="board")
            | Q(name__icontains="residence")
        )
        head_ids = list(hostel_heads.values_list("id", flat=True))
        head_info = [
            {"id": h.id, "code": h.code, "name": h.name} for h in hostel_heads
        ]

        allocated_ids = set(
            HostelAllocation.objects.filter(
                status=HostelAllocation.STATUS_ACTIVE
            ).values_list("student_id", flat=True)
        )

        active_exemptions = StudentFeeExemption.objects.filter(
            fee_head_id__in=head_ids,
            is_active=True,
            revoked_at__isnull=True,
        ).select_related("student", "student__application", "fee_head")

        allocated_but_exempt = []
        exempt_not_allocated = []
        exempt_student_ids: set[int] = set()
        for ex in active_exemptions:
            sid = ex.student_id
            exempt_student_ids.add(sid)
            app = getattr(ex.student, "application", None)
            name = ""
            if app:
                name = " ".join(
                    p
                    for p in [
                        app.first_name or "",
                        app.middle_name or "",
                        app.last_name or "",
                    ]
                    if p
                ).strip()
            row = {
                "student_id": sid,
                "reg_no": ex.student.reg_no,
                "name": name or ex.student.reg_no,
                "fee_head": ex.fee_head.code,
                "fee_head_name": ex.fee_head.name,
                "exemption_id": ex.pk,
            }
            if sid in allocated_ids:
                allocated_but_exempt.append(row)
            else:
                exempt_not_allocated.append(row)

        allocated_no_exemption = []
        for alloc in _allocation_qs().filter(status=HostelAllocation.STATUS_ACTIVE)[
            :1000
        ]:
            if alloc.student_id in exempt_student_ids:
                continue
            allocated_no_exemption.append(
                {
                    "student_id": alloc.student_id,
                    "reg_no": alloc.student.reg_no,
                    "room_code": alloc.bed.room.code,
                    "building": alloc.bed.room.floor.building.name,
                }
            )

        return Response(
            {
                "hostel_fee_heads": head_info,
                "allocated_with_active_exemption": allocated_but_exempt,
                "exempt_without_allocation": exempt_not_allocated[:500],
                "allocated_without_exemption_count": len(allocated_no_exemption),
                "notes": (
                    "allocated_with_active_exemption usually means the student has a room "
                    "but is still exempted from hostel fees — Accounts may want to revoke "
                    "the exemption. exempt_without_allocation are likely day scholars."
                ),
            }
        )


class HostelReportsDashboardView(APIView):
    permission_classes = [IsAuthenticated, CanViewHostelReports]

    def get(self, request):
        from .reports import reports_dashboard

        return Response(reports_dashboard())


class OccupancySummaryReportView(APIView):
    permission_classes = [IsAuthenticated, CanViewHostelReports]

    def get(self, request):
        from .reports import occupancy_summary

        return Response(
            occupancy_summary(
                hostel_id=request.query_params.get("hostel"),
                building_id=request.query_params.get("building"),
                gender=request.query_params.get("gender"),
            )
        )


class VacancyReportView(APIView):
    permission_classes = [IsAuthenticated, CanViewHostelReports]

    def get(self, request):
        from .reports import vacancy_report

        return Response(
            vacancy_report(
                hostel_id=request.query_params.get("hostel"),
                building_id=request.query_params.get("building"),
                gender=request.query_params.get("gender"),
            )
        )


class AllocationReportView(APIView):
    permission_classes = [IsAuthenticated, CanViewHostelReports]

    def get(self, request):
        from .reports import allocation_report

        limit = request.query_params.get("limit") or 500
        try:
            limit = min(int(limit), 2000)
        except (TypeError, ValueError):
            limit = 500
        return Response(
            allocation_report(
                status=request.query_params.get("status") or None,
                hostel_id=request.query_params.get("hostel"),
                building_id=request.query_params.get("building"),
                academic_year=request.query_params.get("academic_year") or None,
                term_number=request.query_params.get("term_number"),
                q=request.query_params.get("q") or None,
                limit=limit,
            )
        )
