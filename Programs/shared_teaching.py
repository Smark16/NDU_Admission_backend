"""Helpers for SharedTeachingOffering — common courses across programmes."""
from __future__ import annotations

import re
from django.db.models import Q, QuerySet

from .models import CourseUnit, SharedTeachingOffering, StudentCourseUnitEnrollment

# Trailing digits: BEC 1102 / BAF1102 / BEX 1102 → "1102"
_CODE_NUMBER_RE = re.compile(r"(\d{3,})\s*$")


def normalize_course_code(code: str | None) -> str:
    return re.sub(r"\s+", "", (code or "").strip()).upper()


def course_code_number(code: str | None) -> str:
    """Shared paper number across programme prefixes (BEC/BAF/BEX 1102 → 1102)."""
    raw = (code or "").strip()
    if not raw:
        return ""
    m = _CODE_NUMBER_RE.search(raw)
    return m.group(1) if m else ""


def suggested_canonical_code(units: list[CourseUnit]) -> str | None:
    """Prefer shared trailing number when codes differ; else the single shared code."""
    numbers = [course_code_number(u.code) for u in units]
    numbers = [n for n in numbers if n]
    if numbers and len(set(numbers)) == 1:
        return numbers[0]
    norms = {normalize_course_code(u.code) for u in units if u.code}
    if len(norms) == 1:
        return next((u.code or "").strip() for u in units if u.code)
    return None


def serialize_peer_course_unit(cu: CourseUnit, *, match_kind: str = "exact_code") -> dict:
    return {
        "id": cu.id,
        "code": cu.code,
        "name": cu.name,
        "semester_id": cu.semester_id,
        "semester_name": cu.semester.name if cu.semester_id else None,
        "program_batch_id": cu.program_batch_id,
        "program_batch_name": cu.program_batch.name if cu.program_batch_id else None,
        "program_name": (
            cu.program_batch.program.name
            if cu.program_batch_id and cu.program_batch.program_id
            else None
        ),
        "shared_teaching_offering_id": cu.shared_teaching_offering_id,
        "match_kind": match_kind,
        "code_number": course_code_number(cu.code),
    }


def find_peer_course_units(
    *,
    source: CourseUnit,
    exclude_semester_id: int | None = None,
    limit: int = 80,
) -> list[dict]:
    """
    Peers on other programmes: same exact code, or same trailing number
    (e.g. BEC 1102 ↔ BAF 1102 ↔ BEX 1102).
    """
    code = (source.code or "").strip()
    number = course_code_number(code)
    if not code and not number:
        return []

    qs = (
        CourseUnit.objects.filter(is_active=True)
        .exclude(pk=source.pk)
        .select_related(
            "program_batch",
            "program_batch__program",
            "semester",
            "shared_teaching_offering",
        )
    )
    if exclude_semester_id:
        qs = qs.exclude(semester_id=exclude_semester_id)

    q = Q()
    if code:
        q |= Q(code__iexact=code)
        compact = normalize_course_code(code)
        if compact:
            # Match "BEC1102" when source is "BEC 1102" (and vice versa) via endswith number + python filter
            q |= Q(code__iexact=compact)
    if number and len(number) >= 3:
        q |= Q(code__iendswith=number) | Q(code__iendswith=f" {number}")

    if not q:
        return []

    candidates = list(qs.filter(q).order_by("code", "id")[:800])
    source_norm = normalize_course_code(code)
    out: list[dict] = []
    seen: set[int] = set()
    for peer in candidates:
        if peer.id in seen:
            continue
        peer_norm = normalize_course_code(peer.code)
        peer_num = course_code_number(peer.code)
        if source_norm and peer_norm == source_norm:
            match_kind = "exact_code"
        elif number and peer_num == number:
            match_kind = "same_number"
        else:
            continue
        seen.add(peer.id)
        row = serialize_peer_course_unit(peer, match_kind=match_kind)
        row["already_linked"] = bool(
            source.shared_teaching_offering_id
            and peer.shared_teaching_offering_id == source.shared_teaching_offering_id
        )
        out.append(row)
        if len(out) >= limit:
            break
    out.sort(
        key=lambda r: (
            0 if r.get("match_kind") == "exact_code" else 1,
            (r.get("program_name") or ""),
            (r.get("code") or ""),
        )
    )
    return out


def search_course_units_for_share(
    *,
    query: str,
    exclude_semester_id: int | None = None,
    exclude_ids: list[int] | None = None,
    limit: int = 40,
) -> list[dict]:
    """Search other programme course units by code, name, or paper number."""
    q = (query or "").strip()
    if len(q) < 2:
        return []

    qs = (
        CourseUnit.objects.filter(is_active=True)
        .select_related(
            "program_batch",
            "program_batch__program",
            "semester",
            "shared_teaching_offering",
        )
    )
    if exclude_semester_id:
        qs = qs.exclude(semester_id=exclude_semester_id)
    if exclude_ids:
        qs = qs.exclude(id__in=exclude_ids)

    number = course_code_number(q) if q.isdigit() or _CODE_NUMBER_RE.search(q) else ""
    filt = Q(code__icontains=q) | Q(name__icontains=q)
    if number and len(number) >= 3:
        filt |= Q(code__iendswith=number) | Q(code__iendswith=f" {number}")

    rows = []
    for cu in qs.filter(filt).order_by("code", "id")[: limit * 3]:
        if number and course_code_number(cu.code) == number:
            kind = "same_number"
        elif normalize_course_code(cu.code) == normalize_course_code(q):
            kind = "exact_code"
        else:
            kind = "search"
        rows.append(serialize_peer_course_unit(cu, match_kind=kind))
        if len(rows) >= limit:
            break
    return rows


def moodle_idnumber_for_course_unit(cu: CourseUnit) -> str:
    """Moodle course key: shared offering when linked, else legacy code-semester."""
    if cu.shared_teaching_offering_id:
        offering = getattr(cu, "shared_teaching_offering", None)
        if offering is not None and offering.pk:
            return offering.moodle_idnumber
        return f"STO-{cu.shared_teaching_offering_id}"
    return f"{cu.code}-{cu.semester_id}"


def linked_course_unit_ids(course_unit: CourseUnit) -> list[int]:
    """All CourseUnit PKs that share teaching with this one (at least itself)."""
    if not course_unit.shared_teaching_offering_id:
        return [course_unit.pk]
    return list(
        CourseUnit.objects.filter(
            shared_teaching_offering_id=course_unit.shared_teaching_offering_id,
            is_active=True,
        ).values_list("id", flat=True)
    )


def linked_course_units_qs(course_unit: CourseUnit) -> QuerySet[CourseUnit]:
    ids = linked_course_unit_ids(course_unit)
    return CourseUnit.objects.filter(id__in=ids, is_active=True)


def registered_enrollments_for_course_unit(
    course_unit: CourseUnit,
    *,
    statuses: list[str] | None = None,
) -> QuerySet[StudentCourseUnitEnrollment]:
    """Roster for LMS / marks: merges all programme CourseUnits on the same offering."""
    if statuses is None:
        statuses = ["enrolled"]
    cu_ids = linked_course_unit_ids(course_unit)
    return (
        StudentCourseUnitEnrollment.objects.filter(
            course_unit_id__in=cu_ids,
            status__in=statuses,
            registration_date__isnull=False,
        )
        .select_related(
            "student",
            "student__application",
            "student__admitted_program",
            "course_unit",
            "course_unit__program_batch",
            "course_unit__program_batch__program",
            "course_unit__semester",
        )
        .order_by("student__reg_no", "id")
    )


def serialize_shared_offering(offering: SharedTeachingOffering) -> dict:
    units = list(
        offering.course_units.filter(is_active=True)
        .select_related("program_batch", "program_batch__program", "semester")
        .order_by("code", "id")
    )
    lecturers = [
        {
            "id": u.id,
            "name": u.get_full_name() or u.username,
            "email": u.email or "",
        }
        for u in offering.lecturers.all()
    ]
    return {
        "id": offering.id,
        "code": offering.code,
        "name": offering.name,
        "catalog_unit_id": offering.catalog_unit_id,
        "academic_year_label": offering.academic_year_label,
        "year_of_study": offering.year_of_study,
        "term_number": offering.term_number,
        "exam_paper_code": offering.exam_paper_code,
        "paper_code": offering.paper_code,
        "moodle_idnumber": offering.moodle_idnumber,
        "notes": offering.notes,
        "is_active": offering.is_active,
        "lecturers": lecturers,
        "course_units": [
            {
                "id": cu.id,
                "code": cu.code,
                "name": cu.name,
                "semester_id": cu.semester_id,
                "semester_name": cu.semester.name if cu.semester_id else None,
                "program_batch_id": cu.program_batch_id,
                "program_batch_name": cu.program_batch.name if cu.program_batch_id else None,
                "program_id": cu.program_batch.program_id if cu.program_batch_id else None,
                "program_name": (
                    cu.program_batch.program.name
                    if cu.program_batch_id and cu.program_batch.program_id
                    else None
                ),
            }
            for cu in units
        ],
        "linked_count": len(units),
        "created_at": offering.created_at.isoformat() if offering.created_at else None,
        "updated_at": offering.updated_at.isoformat() if offering.updated_at else None,
    }


def create_shared_offering_from_course_units(
    *,
    course_unit_ids: list[int],
    code: str | None = None,
    name: str | None = None,
    academic_year_label: str = "",
    year_of_study: int | None = None,
    term_number: int | None = None,
    exam_paper_code: str = "",
    notes: str = "",
    lecturer_ids: list[int] | None = None,
) -> SharedTeachingOffering:
    """Create an offering and link the given programme CourseUnits to it."""
    units = list(
        CourseUnit.objects.filter(id__in=course_unit_ids, is_active=True).select_related(
            "catalog_unit"
        )
    )
    if len(units) < 2:
        raise ValueError("Link at least two active course units to create a shared offering.")

    codes = {u.code.strip() for u in units if u.code}
    canonical = (code or "").strip()
    if len(codes) > 1 and not canonical:
        # e.g. BEC 1102 + BAF 1102 → canonical "1102"
        auto = suggested_canonical_code(units)
        if not auto:
            raise ValueError(
                f"Course units have different codes ({', '.join(sorted(codes))}). "
                "Pass an explicit canonical code, or use units that share a paper number."
            )
        canonical = auto
    if not canonical:
        canonical = (units[0].code or "").strip()

    primary = units[0]
    offering = SharedTeachingOffering.objects.create(
        code=canonical or (primary.code or "").strip(),
        name=(name or primary.name or "").strip(),
        catalog_unit_id=primary.catalog_unit_id,
        academic_year_label=(academic_year_label or "").strip(),
        year_of_study=year_of_study,
        term_number=term_number,
        exam_paper_code=(exam_paper_code or "").strip(),
        notes=(notes or "").strip(),
        is_active=True,
    )
    CourseUnit.objects.filter(id__in=[u.id for u in units]).update(
        shared_teaching_offering_id=offering.id
    )
    if lecturer_ids:
        offering.lecturers.set(lecturer_ids)
    else:
        # Union lecturers already on the linked units
        from django.contrib.auth import get_user_model

        User = get_user_model()
        lids = set()
        for u in units:
            lids.update(u.lecturers.values_list("id", flat=True))
        if lids:
            offering.lecturers.set(User.objects.filter(id__in=lids))
    return offering
