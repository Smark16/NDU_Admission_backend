"""Helpers for creating/updating hostel inventory and keeping beds in sync with capacity."""
from __future__ import annotations

from django.db import transaction
from rest_framework.exceptions import ValidationError

from .models import Bed, Floor, HostelAllocation, Room


def sync_beds_for_room(room: Room) -> None:
    """
    Ensure bedroom has Bed 1..capacity.
    Never delete occupied beds; refuse capacity below occupied count.
    Extra beds beyond capacity that are free (available/blocked/maintenance) are removed.
    """
    if room.room_kind != Room.KIND_BEDROOM:
        # Non-bedrooms should not keep allocatable beds
        extras = room.beds.exclude(
            allocations__status=HostelAllocation.STATUS_ACTIVE
        )
        extras.delete()
        if room.capacity != 0:
            room.capacity = 0
            room.save(update_fields=["capacity", "updated_at"])
        return

    capacity = int(room.capacity or 0)
    if capacity < 0:
        raise ValidationError({"capacity": "Must be >= 0."})

    beds = list(room.beds.order_by("label"))
    occupied = [
        b
        for b in beds
        if b.status == Bed.STATUS_OCCUPIED
        or b.allocations.filter(status=HostelAllocation.STATUS_ACTIVE).exists()
    ]
    if capacity < len(occupied):
        raise ValidationError(
            {
                "capacity": (
                    f"Cannot set capacity to {capacity}: "
                    f"{len(occupied)} bed(s) are occupied."
                )
            }
        )

    existing_by_label = {b.label: b for b in beds}
    for i in range(1, capacity + 1):
        label = f"Bed {i}"
        if label not in existing_by_label:
            Bed.objects.create(room=room, label=label, status=Bed.STATUS_AVAILABLE)

    # Remove surplus free beds (Bed N where N > capacity)
    for b in room.beds.all():
        try:
            n = int(str(b.label).replace("Bed", "").strip())
        except ValueError:
            n = None
        if n is not None and n > capacity:
            if b.status == Bed.STATUS_OCCUPIED or b.allocations.filter(
                status=HostelAllocation.STATUS_ACTIVE
            ).exists():
                continue
            b.delete()


@transaction.atomic
def create_room(
    *,
    floor: Floor,
    code: str,
    display_name: str = "",
    room_kind: str = Room.KIND_BEDROOM,
    capacity: int = 4,
    notes: str = "",
    is_active: bool = True,
) -> Room:
    code = (code or "").strip()
    if not code:
        raise ValidationError({"code": "Room code is required."})
    if Room.objects.filter(code__iexact=code).exists():
        raise ValidationError({"code": f'Room code "{code}" already exists.'})

    kind = room_kind or Room.KIND_BEDROOM
    if kind not in dict(Room.KIND_CHOICES):
        raise ValidationError({"room_kind": "Invalid room kind."})

    cap = int(capacity or 0)
    if kind != Room.KIND_BEDROOM:
        cap = 0
    elif cap < 1:
        raise ValidationError({"capacity": "Bedrooms need capacity of at least 1."})

    room = Room.objects.create(
        floor=floor,
        code=code,
        display_name=(display_name or code).strip(),
        room_kind=kind,
        capacity=cap,
        notes=notes or "",
        is_active=is_active,
    )
    sync_beds_for_room(room)
    return room


@transaction.atomic
def update_room(room: Room, **fields) -> Room:
    allowed = {
        "floor_id",
        "code",
        "display_name",
        "room_kind",
        "capacity",
        "notes",
        "is_active",
    }
    data = {k: v for k, v in fields.items() if k in allowed and v is not None}

    if "code" in data:
        code = str(data["code"]).strip()
        if not code:
            raise ValidationError({"code": "Room code is required."})
        if Room.objects.filter(code__iexact=code).exclude(pk=room.pk).exists():
            raise ValidationError({"code": f'Room code "{code}" already exists.'})
        data["code"] = code

    if "room_kind" in data and data["room_kind"] not in dict(Room.KIND_CHOICES):
        raise ValidationError({"room_kind": "Invalid room kind."})

    if "floor_id" in data:
        floor = Floor.objects.filter(pk=data["floor_id"]).first()
        if not floor:
            raise ValidationError({"floor_id": "Floor not found."})
        room.floor = floor
        del data["floor_id"]

    for k, v in data.items():
        setattr(room, k, v)

    if room.room_kind != Room.KIND_BEDROOM:
        room.capacity = 0
    elif "capacity" in data:
        room.capacity = int(data["capacity"])

    room.save()
    sync_beds_for_room(room)
    return room


@transaction.atomic
def update_bed(bed: Bed, *, status: str | None = None, label: str | None = None) -> Bed:
    if status is not None:
        if status not in dict(Bed.STATUS_CHOICES):
            raise ValidationError({"status": "Invalid bed status."})
        if status != Bed.STATUS_OCCUPIED and bed.allocations.filter(
            status=HostelAllocation.STATUS_ACTIVE
        ).exists():
            raise ValidationError(
                {
                    "status": (
                        "This bed has an active allocation. "
                        "End the allocation before changing status."
                    )
                }
            )
        if status == Bed.STATUS_OCCUPIED and not bed.allocations.filter(
            status=HostelAllocation.STATUS_ACTIVE
        ).exists():
            raise ValidationError(
                {"status": "Mark beds occupied by assigning a student, not manually."}
            )
        bed.status = status

    if label is not None:
        label = str(label).strip()
        if not label:
            raise ValidationError({"label": "Label is required."})
        if Bed.objects.filter(room=bed.room, label=label).exclude(pk=bed.pk).exists():
            raise ValidationError({"label": f'Label "{label}" already exists in this room.'})
        bed.label = label

    bed.save()
    return bed
