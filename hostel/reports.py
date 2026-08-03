"""Hostel operational and finance report query helpers."""
from __future__ import annotations

from django.db.models import Count, Q

from admissions.models import AdmittedStudent
from admissions.registration_workflow import student_curriculum_year_term

from .models import Bed, Building, Floor, Hostel, HostelAllocation, Room


def occupancy_summary(*, hostel_id=None, building_id=None, gender=None) -> dict:
    buildings = Building.objects.filter(is_active=True).select_related("hostel")
    if hostel_id:
        buildings = buildings.filter(hostel_id=hostel_id)
    if building_id:
        buildings = buildings.filter(pk=building_id)
    if gender:
        buildings = buildings.filter(hostel__gender=gender)

    by_building = []
    totals = {
        "rooms": 0,
        "beds": 0,
        "occupied": 0,
        "available": 0,
        "blocked": 0,
        "maintenance": 0,
    }

    for b in buildings.order_by("hostel__name", "name"):
        bed_qs = Bed.objects.filter(
            room__floor__building=b,
            room__room_kind=Room.KIND_BEDROOM,
            room__is_active=True,
        )
        rooms = Room.objects.filter(
            floor__building=b, room_kind=Room.KIND_BEDROOM, is_active=True
        ).count()
        beds = bed_qs.count()
        occupied = bed_qs.filter(status=Bed.STATUS_OCCUPIED).count()
        available = bed_qs.filter(status=Bed.STATUS_AVAILABLE).count()
        blocked = bed_qs.filter(status=Bed.STATUS_BLOCKED).count()
        maintenance = bed_qs.filter(status=Bed.STATUS_MAINTENANCE).count()
        fill_pct = round((occupied / beds) * 100, 1) if beds else 0.0
        row = {
            "building_id": b.id,
            "building": b.name,
            "building_code": b.code,
            "hostel_id": b.hostel_id,
            "hostel": b.hostel.name,
            "gender": b.hostel.gender,
            "rooms": rooms,
            "beds": beds,
            "occupied": occupied,
            "available": available,
            "blocked": blocked,
            "maintenance": maintenance,
            "fill_pct": fill_pct,
        }
        by_building.append(row)
        totals["rooms"] += rooms
        totals["beds"] += beds
        totals["occupied"] += occupied
        totals["available"] += available
        totals["blocked"] += blocked
        totals["maintenance"] += maintenance

    totals["fill_pct"] = (
        round((totals["occupied"] / totals["beds"]) * 100, 1) if totals["beds"] else 0.0
    )

    by_gender = []
    for g in (Hostel.GENDER_MALE, Hostel.GENDER_FEMALE, Hostel.GENDER_MIXED):
        subset = [r for r in by_building if r["gender"] == g]
        if not subset:
            continue
        beds = sum(r["beds"] for r in subset)
        occupied = sum(r["occupied"] for r in subset)
        by_gender.append(
            {
                "gender": g,
                "buildings": len(subset),
                "beds": beds,
                "occupied": occupied,
                "available": sum(r["available"] for r in subset),
                "fill_pct": round((occupied / beds) * 100, 1) if beds else 0.0,
            }
        )

    by_floor = []
    floors = Floor.objects.filter(building__in=buildings).select_related(
        "building", "building__hostel"
    )
    for fl in floors.order_by("building__name", "sort_order", "name"):
        bed_qs = Bed.objects.filter(
            room__floor=fl,
            room__room_kind=Room.KIND_BEDROOM,
            room__is_active=True,
        )
        beds = bed_qs.count()
        if beds == 0:
            continue
        occupied = bed_qs.filter(status=Bed.STATUS_OCCUPIED).count()
        by_floor.append(
            {
                "floor_id": fl.id,
                "floor": fl.name,
                "building": fl.building.name,
                "hostel": fl.building.hostel.name,
                "beds": beds,
                "occupied": occupied,
                "available": bed_qs.filter(status=Bed.STATUS_AVAILABLE).count(),
                "fill_pct": round((occupied / beds) * 100, 1) if beds else 0.0,
            }
        )

    return {
        "totals": totals,
        "by_building": by_building,
        "by_gender": by_gender,
        "by_floor": by_floor,
    }


def vacancy_report(*, hostel_id=None, building_id=None, gender=None) -> dict:
    beds = Bed.objects.filter(
        status=Bed.STATUS_AVAILABLE,
        room__room_kind=Room.KIND_BEDROOM,
        room__is_active=True,
        room__floor__building__is_active=True,
    ).select_related(
        "room",
        "room__floor",
        "room__floor__building",
        "room__floor__building__hostel",
    )
    if hostel_id:
        beds = beds.filter(room__floor__building__hostel_id=hostel_id)
    if building_id:
        beds = beds.filter(room__floor__building_id=building_id)
    if gender:
        beds = beds.filter(room__floor__building__hostel__gender=gender)

    rows = []
    for b in beds.order_by(
        "room__floor__building__hostel__name",
        "room__floor__building__name",
        "room__floor__sort_order",
        "room__code",
        "label",
    )[:2000]:
        rows.append(
            {
                "bed_id": b.id,
                "bed_label": b.label,
                "room_code": b.room.code,
                "floor": b.room.floor.name,
                "building": b.room.floor.building.name,
                "building_id": b.room.floor.building_id,
                "hostel": b.room.floor.building.hostel.name,
                "gender": b.room.floor.building.hostel.gender,
            }
        )

    # Group counts by building for quick view
    by_building: dict[int, dict] = {}
    for r in rows:
        bid = r["building_id"]
        if bid not in by_building:
            by_building[bid] = {
                "building_id": bid,
                "building": r["building"],
                "hostel": r["hostel"],
                "gender": r["gender"],
                "vacant_beds": 0,
            }
        by_building[bid]["vacant_beds"] += 1

    return {
        "count": len(rows),
        "by_building": sorted(
            by_building.values(), key=lambda x: (x["hostel"], x["building"])
        ),
        "vacancies": rows,
    }


def allocation_report(
    *,
    status: str | None = None,
    hostel_id=None,
    building_id=None,
    academic_year: str | None = None,
    term_number=None,
    q: str | None = None,
    limit: int = 500,
) -> dict:
    qs = HostelAllocation.objects.select_related(
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
    if status:
        qs = qs.filter(status=status)
    if hostel_id:
        qs = qs.filter(bed__room__floor__building__hostel_id=hostel_id)
    if building_id:
        qs = qs.filter(bed__room__floor__building_id=building_id)
    if academic_year:
        qs = qs.filter(academic_year=academic_year)
    if term_number not in (None, ""):
        qs = qs.filter(term_number=int(term_number))
    if q:
        qs = qs.filter(
            Q(student__reg_no__icontains=q)
            | Q(student__student_id__icontains=q)
            | Q(student__application__first_name__icontains=q)
            | Q(student__application__last_name__icontains=q)
            | Q(student__admitted_program__name__icontains=q)
            | Q(student__admitted_program__code__icontains=q)
            | Q(bed__room__code__icontains=q)
        )

    total = qs.count()
    rows = []
    for a in qs.order_by("-assigned_at")[:limit]:
        app = getattr(a.student, "application", None)
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
        prog = getattr(a.student, "admitted_program", None)
        campus = getattr(a.student, "admitted_campus", None)
        fac = getattr(prog, "faculty", None) if prog else None
        rows.append(
            {
                "id": a.id,
                "status": a.status,
                "student_id": a.student_id,
                "reg_no": a.student.reg_no,
                "student_number": a.student.student_id,
                "name": name or a.student.reg_no,
                "gender": getattr(app, "gender", None) if app else None,
                "program": prog.name if prog else None,
                "program_code": getattr(prog, "code", None) if prog else None,
                "faculty": fac.name if fac else None,
                "campus": campus.name if campus else None,
                "room_code": a.bed.room.code,
                "bed_label": a.bed.label,
                "floor": a.bed.room.floor.name,
                "building": a.bed.room.floor.building.name,
                "hostel": a.bed.room.floor.building.hostel.name,
                "academic_year": a.academic_year,
                "term_number": a.term_number,
                "check_in": a.check_in.isoformat() if a.check_in else None,
                "check_out": a.check_out.isoformat() if a.check_out else None,
                "assigned_at": a.assigned_at.isoformat() if a.assigned_at else None,
                "assigned_by": (
                    a.assigned_by.get_full_name() or a.assigned_by.username
                    if a.assigned_by
                    else None
                ),
            }
        )

    status_counts = {
        row["status"]: row["c"]
        for row in HostelAllocation.objects.values("status").annotate(c=Count("id"))
    }

    return {
        "total": total,
        "returned": len(rows),
        "status_counts": status_counts,
        "results": rows,
    }


def ready_queue_summary() -> dict:
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
        .select_related("application")
    )
    male = female = other = total = 0
    for s in qs[:2000]:
        year, term = student_curriculum_year_term(s)
        if year != 1 or term != 1:
            continue
        total += 1
        g = (getattr(s.application, "gender", None) or "").strip().lower()
        if g in ("m", "male"):
            male += 1
        elif g in ("f", "female"):
            female += 1
        else:
            other += 1
    return {
        "fy_main_cleared_unallocated": total,
        "by_gender": {"male": male, "female": female, "other": other},
    }


def reports_dashboard() -> dict:
    occ = occupancy_summary()
    vac = vacancy_report()
    ready = ready_queue_summary()
    active = HostelAllocation.objects.filter(status=HostelAllocation.STATUS_ACTIVE).count()
    return {
        "occupancy_totals": occ["totals"],
        "by_gender": occ["by_gender"],
        "vacant_beds": vac["count"],
        "active_allocations": active,
        "ready_queue": ready,
        "buildings": len(occ["by_building"]),
    }
