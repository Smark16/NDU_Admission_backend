"""
Seed demo hostel inventory (and optional bed allocations) for local/QA testing.

Idempotent on stable codes — safe to re-run.

Examples:
  python manage.py seed_hostel_demo_data
  python manage.py seed_hostel_demo_data --allocations 8
  python manage.py seed_hostel_demo_data --no-allocations
  python manage.py seed_hostel_demo_data --reset
"""
from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import Campus
from hostel.models import Bed, Building, Floor, Hostel, HostelAllocation, Room


# Stable codes so re-runs update instead of duplicating.
DEMO_HOSTELS = [
    {
        "code": "GENTS",
        "name": "Gents Hostel",
        "gender": Hostel.GENDER_MALE,
        "buildings": [
            {
                "code": "YOKANA",
                "name": "Bishop Yokana",
                "floors": [
                    ("GF", "Ground Floor", 1, [("YOK-GF-01", 4), ("YOK-GF-02", 4), ("YOK-GF-03", 2)]),
                    ("L1", "Level 1", 2, [("YOK-L1-01", 4), ("YOK-L1-02", 4), ("YOK-L1-STORE", 0)]),
                    ("L2", "Level 2", 3, [("YOK-L2-01", 2), ("YOK-L2-02", 4)]),
                ],
            },
            {
                "code": "AKIIBUA",
                "name": "Akiibua",
                "floors": [
                    ("GF", "Ground Floor", 1, [("AKI-GF-01", 4), ("AKI-GF-02", 4)]),
                    ("L1", "Level 1", 2, [("AKI-L1-01", 2), ("AKI-L1-02", 2), ("AKI-L1-03", 4)]),
                ],
            },
            {
                "code": "MUTEESA",
                "name": "Muteesa Gents",
                "floors": [
                    ("GF", "Ground Floor", 1, [("MUT-GF-01", 4), ("MUT-GF-02", 4)]),
                    ("L1", "Level 1", 2, [("MUT-L1-01", 4), ("MUT-L1-02", 2)]),
                ],
            },
        ],
    },
    {
        "code": "FEMALE",
        "name": "Female Hostel",
        "gender": Hostel.GENDER_FEMALE,
        "buildings": [
            {
                "code": "NOAHS_ARK",
                "name": "Noah's Ark",
                "floors": [
                    ("GF", "Ground Floor", 1, [("NOA-GF-01", 4), ("NOA-GF-02", 4), ("NOA-GF-03", 2)]),
                    ("L1", "Level 1", 2, [("NOA-L1-01", 4), ("NOA-L1-02", 4)]),
                    ("L2", "Level 2", 3, [("NOA-L2-01", 2), ("NOA-L2-02", 4)]),
                ],
            },
            {
                "code": "WEST_BUGANDA",
                "name": "West Buganda",
                "floors": [
                    ("GF", "Ground Floor", 1, [("WBG-GF-01", 4), ("WBG-GF-02", 4)]),
                    ("L1", "Level 1", 2, [("WBG-L1-01", 2), ("WBG-L1-02", 4), ("WBG-L1-03", 4)]),
                ],
            },
            {
                "code": "WEKISA",
                "name": "Wekisa",
                "floors": [
                    ("GF", "Ground Floor", 1, [("WEK-GF-01", 4), ("WEK-GF-02", 2)]),
                    ("L1", "Level 1", 2, [("WEK-L1-01", 4), ("WEK-L1-02", 4)]),
                ],
            },
        ],
    },
]


def _ensure_campus() -> Campus:
    campus = Campus.objects.filter(code__iexact="MAIN").first()
    if campus:
        return campus
    campus = Campus.objects.filter(name__icontains="Main").first()
    if campus:
        return campus
    campus = Campus.objects.filter(name__icontains="Ndejje").first()
    if campus:
        return campus
    campus = Campus.objects.first()
    if campus:
        return campus
    return Campus.objects.create(
        name="Main Campus",
        code="MAIN",
        address="Ndejje",
        email="",
    )


def _bed_labels(capacity: int) -> list[str]:
    if capacity <= 0:
        return []
    if capacity == 1:
        return ["Bed A"]
    if capacity == 2:
        return ["Bed A", "Bed B"]
    # 3–4+
    letters = "ABCDEFGH"
    return [f"Bed {letters[i]}" for i in range(capacity)]


class Command(BaseCommand):
    help = (
        "Seed demo hostel halls/rooms/beds for testing. "
        "Optionally assign beds to eligible admitted students."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--allocations",
            type=int,
            default=6,
            help="Try to create this many active bed allocations (default: 6).",
        )
        parser.add_argument(
            "--no-allocations",
            action="store_true",
            help="Only create inventory (hostels/buildings/floors/rooms/beds).",
        )
        parser.add_argument(
            "--academic-year",
            default="2025/2026",
            help="Academic year for demo allocations (default: 2025/2026).",
        )
        parser.add_argument(
            "--term",
            type=int,
            default=1,
            help="Term number for demo allocations (default: 1).",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help=(
                "Delete demo hostels (GENTS/FEMALE on the chosen campus) and their "
                "buildings/rooms/beds/allocations before seeding."
            ),
        )

    @transaction.atomic
    def handle(self, *args, **options):
        campus = _ensure_campus()
        self.stdout.write(f"Campus: {campus.name} ({campus.code})")

        if options["reset"]:
            deleted = self._reset_demo(campus)
            self.stdout.write(self.style.WARNING(f"Reset demo hostels: removed {deleted} hostel(s)."))

        stats = {
            "hostels": 0,
            "buildings": 0,
            "floors": 0,
            "rooms": 0,
            "beds": 0,
            "beds_blocked": 0,
            "beds_maintenance": 0,
            "allocations": 0,
            "allocation_skipped": 0,
        }

        for hostel_spec in DEMO_HOSTELS:
            hostel, created = Hostel.objects.update_or_create(
                campus=campus,
                code=hostel_spec["code"],
                defaults={
                    "name": hostel_spec["name"],
                    "gender": hostel_spec["gender"],
                    "is_active": True,
                },
            )
            if created:
                stats["hostels"] += 1

            for bspec in hostel_spec["buildings"]:
                building, b_created = Building.objects.update_or_create(
                    hostel=hostel,
                    code=bspec["code"],
                    defaults={
                        "name": bspec["name"],
                        "external_block_id": bspec["code"],
                        "is_active": True,
                    },
                )
                if b_created:
                    stats["buildings"] += 1

                for floor_code, floor_name, sort_order, rooms in bspec["floors"]:
                    floor, f_created = Floor.objects.update_or_create(
                        building=building,
                        code=floor_code,
                        defaults={
                            "name": floor_name,
                            "sort_order": sort_order,
                        },
                    )
                    if f_created:
                        stats["floors"] += 1

                    for room_code, capacity in rooms:
                        kind = Room.KIND_BEDROOM if capacity > 0 else Room.KIND_STORE
                        room, r_created = Room.objects.update_or_create(
                            code=room_code,
                            defaults={
                                "floor": floor,
                                "display_name": room_code.split("-")[-1],
                                "room_kind": kind,
                                "capacity": capacity,
                                "notes": "Demo seed data",
                                "is_active": True,
                            },
                        )
                        if r_created:
                            stats["rooms"] += 1

                        if capacity <= 0:
                            continue

                        for label in _bed_labels(capacity):
                            bed, bed_created = Bed.objects.get_or_create(
                                room=room,
                                label=label,
                                defaults={"status": Bed.STATUS_AVAILABLE},
                            )
                            if bed_created:
                                stats["beds"] += 1

                # Variety: mark one bed blocked / one maintenance per building (if enough beds).
                beds_qs = Bed.objects.filter(
                    room__floor__building=building,
                    status=Bed.STATUS_AVAILABLE,
                ).order_by("id")
                blocked = beds_qs.first()
                if blocked:
                    blocked.status = Bed.STATUS_BLOCKED
                    blocked.save(update_fields=["status", "updated_at"])
                    stats["beds_blocked"] += 1
                maint = beds_qs.exclude(pk=getattr(blocked, "pk", None)).first()
                if maint:
                    maint.status = Bed.STATUS_MAINTENANCE
                    maint.save(update_fields=["status", "updated_at"])
                    stats["beds_maintenance"] += 1

        if not options["no_allocations"] and options["allocations"] > 0:
            a_stats = self._seed_allocations(
                campus=campus,
                limit=options["allocations"],
                academic_year=options["academic_year"],
                term_number=options["term"],
            )
            stats["allocations"] = a_stats["created"]
            stats["allocation_skipped"] = a_stats["skipped"]

        self.stdout.write(self.style.SUCCESS("Hostel demo data ready."))
        for key, value in stats.items():
            self.stdout.write(f"  {key}: {value}")
        self.stdout.write(
            "Open Admin > Hostel > Inventory / Assign / Occupancy to verify."
        )

    def _reset_demo(self, campus: Campus) -> int:
        qs = Hostel.objects.filter(campus=campus, code__in=["GENTS", "FEMALE"])
        count = qs.count()
        # Cascades buildings → floors → rooms → beds; allocations PROTECT beds —
        # end/delete allocations on demo beds first.
        bed_ids = list(
            Bed.objects.filter(room__floor__building__hostel__in=qs).values_list("id", flat=True)
        )
        HostelAllocation.objects.filter(bed_id__in=bed_ids).delete()
        qs.delete()
        return count

    def _seed_allocations(
        self,
        *,
        campus: Campus,
        limit: int,
        academic_year: str,
        term_number: int,
    ) -> dict:
        from admissions.models import AdmittedStudent
        from hostel.eligibility import student_gender, student_hostel_eligibility
        from hostel.services import assign_bed

        created = skipped = 0
        students = (
            AdmittedStudent.objects.filter(
                is_admitted=True,
                admission_fee_paid=True,
            )
            .select_related("application", "admitted_campus")
            .order_by("id")[: max(limit * 8, 40)]
        )

        for student in students:
            if created >= limit:
                break
            elig = student_hostel_eligibility(student)
            if not elig["ok"]:
                skipped += 1
                continue
            gender = student_gender(student)
            if not gender:
                skipped += 1
                continue

            if HostelAllocation.objects.filter(
                student=student, status=HostelAllocation.STATUS_ACTIVE
            ).exists():
                skipped += 1
                continue

            bed = (
                Bed.objects.filter(
                    status=Bed.STATUS_AVAILABLE,
                    room__is_active=True,
                    room__room_kind=Room.KIND_BEDROOM,
                    room__floor__building__hostel__campus=campus,
                    room__floor__building__hostel__is_active=True,
                    room__floor__building__hostel__gender=gender,
                )
                .select_related("room__floor__building__hostel")
                .order_by("id")
                .first()
            )
            if not bed:
                skipped += 1
                continue

            try:
                assign_bed(
                    student=student,
                    bed=bed,
                    academic_year=academic_year,
                    term_number=term_number,
                    user=None,
                    check_in=date.today(),
                    notes="Demo seed allocation",
                    end_existing=True,
                )
                created += 1
            except Exception as exc:
                skipped += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"  skip student id={student.pk}: {exc}"
                    )
                )

        if created == 0:
            self.stdout.write(
                self.style.WARNING(
                    "No allocations created. Need admitted students who are "
                    "Accounts-cleared (and AR-docs verified if Y1 Main Campus), "
                    "with gender set. Inventory was still seeded."
                )
            )
        return {"created": created, "skipped": skipped}
