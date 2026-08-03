from __future__ import annotations

from datetime import date

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from admissions.models import AdmittedStudent

from .eligibility import student_gender, student_hostel_eligibility
from .models import Bed, Hostel, HostelAllocation


def end_allocation(
    allocation: HostelAllocation,
    *,
    user=None,
    status: str = HostelAllocation.STATUS_ENDED,
    check_out: date | None = None,
    notes: str = "",
) -> HostelAllocation:
    if allocation.status != HostelAllocation.STATUS_ACTIVE:
        raise ValidationError({"detail": "Allocation is not active."})
    allocation.status = status
    allocation.ended_at = timezone.now()
    allocation.ended_by = user
    allocation.check_out = check_out or date.today()
    if notes:
        allocation.notes = (allocation.notes + "\n" + notes).strip() if allocation.notes else notes
    allocation.save(
        update_fields=[
            "status",
            "ended_at",
            "ended_by",
            "check_out",
            "notes",
            "updated_at",
        ]
    )
    bed = allocation.bed
    if bed.status == Bed.STATUS_OCCUPIED:
        bed.status = Bed.STATUS_AVAILABLE
        bed.save(update_fields=["status", "updated_at"])
    return allocation


@transaction.atomic
def assign_bed(
    *,
    student: AdmittedStudent,
    bed: Bed,
    academic_year: str,
    term_number: int,
    user=None,
    check_in: date | None = None,
    notes: str = "",
    end_existing: bool = True,
) -> HostelAllocation:
    eligibility = student_hostel_eligibility(student)
    if not eligibility["ok"]:
        raise ValidationError(
            {
                "detail": "Student is not eligible for hostel assignment.",
                "reasons": eligibility["reasons"],
                "eligibility": eligibility,
            }
        )

    gender = student_gender(student)
    hostel_gender = bed.room.floor.building.hostel.gender
    if (
        gender
        and hostel_gender != Hostel.GENDER_MIXED
        and gender != hostel_gender
    ):
        raise ValidationError(
            {
                "detail": (
                    f"Gender mismatch: student is {gender}, "
                    f"hostel is {hostel_gender}."
                )
            }
        )

    if bed.room.room_kind != bed.room.KIND_BEDROOM:
        raise ValidationError({"detail": "Only bedroom beds can be allocated."})

    if bed.status in (Bed.STATUS_BLOCKED, Bed.STATUS_MAINTENANCE):
        raise ValidationError({"detail": f"Bed is {bed.status} and cannot be assigned."})

    existing_bed = (
        HostelAllocation.objects.select_for_update()
        .filter(bed=bed, status=HostelAllocation.STATUS_ACTIVE)
        .first()
    )
    if existing_bed:
        raise ValidationError({"detail": "This bed already has an active allocation."})

    existing_student = (
        HostelAllocation.objects.select_for_update()
        .filter(student=student, status=HostelAllocation.STATUS_ACTIVE)
        .first()
    )
    if existing_student:
        if not end_existing:
            raise ValidationError(
                {"detail": "Student already has an active hostel allocation."}
            )
        end_allocation(
            existing_student,
            user=user,
            notes=f"Ended on reassignment to {bed.room.code} / {bed.label}",
        )

    academic_year = (academic_year or "").strip()
    if not academic_year:
        raise ValidationError({"academic_year": "Required."})
    try:
        term_number = int(term_number)
    except (TypeError, ValueError):
        raise ValidationError({"term_number": "Must be an integer."})
    if term_number < 1:
        raise ValidationError({"term_number": "Must be >= 1."})

    allocation = HostelAllocation.objects.create(
        student=student,
        bed=bed,
        academic_year=academic_year,
        term_number=term_number,
        status=HostelAllocation.STATUS_ACTIVE,
        check_in=check_in or date.today(),
        notes=notes or "",
        assigned_by=user,
    )
    bed.status = Bed.STATUS_OCCUPIED
    bed.save(update_fields=["status", "updated_at"])
    return allocation


@transaction.atomic
def transfer_bed(
    *,
    allocation: HostelAllocation,
    new_bed: Bed,
    user=None,
    notes: str = "",
) -> HostelAllocation:
    if allocation.status != HostelAllocation.STATUS_ACTIVE:
        raise ValidationError({"detail": "Only active allocations can be transferred."})
    student = allocation.student
    academic_year = allocation.academic_year
    term_number = allocation.term_number
    end_allocation(
        allocation,
        user=user,
        notes=notes or f"Transferred to {new_bed.room.code} / {new_bed.label}",
    )
    return assign_bed(
        student=student,
        bed=new_bed,
        academic_year=academic_year,
        term_number=term_number,
        user=user,
        notes=notes or f"Transferred from allocation #{allocation.pk}",
        end_existing=False,
    )
