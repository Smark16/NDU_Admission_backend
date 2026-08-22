"""Helpers for SharedTeachingOffering — common courses across programmes."""
from __future__ import annotations

import re
from django.db.models import Q, QuerySet

from .models import CourseUnit, SharedTeachingOffering, StudentCourseUnitEnrollment

# Trailing digits: BEC 1102 / BAF1102 / BEX 1102 → "1102"
_CODE_NUMBER_RE = re.compile(r"(\d{3,})\s*$")
_NAME_STOPWORDS = {
    "and",
    "the",
    "of",
    "for",
    "to",
    "in",
    "a",
    "an",
    "on",
    "with",
    "i",
    "ii",
    "iii",
    "iv",
    "year",
    "semester",
    "course",
    "unit",
}


def normalize_course_code(code: str | None) -> str:
    return re.sub(r"\s+", "", (code or "").strip()).upper()


def course_code_number(code: str | None) -> str:
    """Shared paper number across programme prefixes (BEC/BAF/BEX 1102 → 1102)."""
    raw = (code or "").strip()
    if not raw:
        return ""
    m = _CODE_NUMBER_RE.search(raw)
    return m.group(1) if m else ""


def normalize_course_name(name: str | None) -> str:
    s = re.sub(r"[^a-z0-9\s]", " ", (name or "").lower())
    return re.sub(r"\s+", " ", s).strip()


def _stem_token(token: str) -> str:
    t = token
    for suffix in ("ing", "tion", "ments", "ment", "ies", "es", "s"):
        if len(t) > len(suffix) + 3 and t.endswith(suffix):
            t = t[: -len(suffix)]
            break
    return t


def name_tokens(name: str | None) -> set[str]:
    return {
        _stem_token(t)
        for t in normalize_course_name(name).split()
        if len(t) >= 3 and t not in _NAME_STOPWORDS
    }


def names_similar(a: str | None, b: str | None) -> bool:
    """True when titles look like the same paper (exact, containment, or token overlap)."""
    na = normalize_course_name(a)
    nb = normalize_course_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if len(na) >= 8 and len(nb) >= 8 and (na in nb or nb in na):
        return True
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return False
    inter = ta & tb
    if len(inter) >= 2:
        return True
    union = ta | tb
    return bool(union) and (len(inter) / len(union)) >= 0.65 and len(inter) >= 1


def classify_peer_match(source: CourseUnit, peer: CourseUnit) -> str | None:
    """Return match_kind or None if not a useful peer.

    Priority for ranking (handled by callers):
      exact_code > similar_name > same_number
    """
    source_norm = normalize_course_code(source.code)
    peer_norm = normalize_course_code(peer.code)
    source_num = course_code_number(source.code)
    peer_num = course_code_number(peer.code)
    similar = names_similar(source.name, peer.name)

    if source_norm and peer_norm == source_norm:
        return "exact_code"
    # Same title matters more than shared paper number alone
    # (1102 is Fundamentals of Accounting on BBA but Communication Skills on BCS).
    if similar:
        return "similar_name"
    if source_num and peer_num == source_num:
        return "same_number"
    return None


def peer_match_rank(match_kind: str | None) -> int:
    return {
        "exact_code": 0,
        "similar_name": 1,
        "same_number": 2,
        "linked": 3,
        "search": 4,
    }.get(match_kind or "", 9)

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


_STUDY_MODE_ORDER = {
    "Day": 0,
    "Main": 1,
    "Weekend": 2,
    "Evening": 3,
    "Distance": 4,
    "Other": 9,
}


def infer_study_mode(*parts: str | None) -> str:
    """Detect Day / Weekend / Main / etc. from programme or batch labels.

    Note: \"Main\" is its own stream (often Main Campus day school) — not the same as Day.
    """
    text = " ".join((p or "").strip() for p in parts if p).lower()
    text = re.sub(r"[\s_/\-]+", " ", text)
    if re.search(r"\bweek\s*end\b|\bweekend\b", text):
        return "Weekend"
    if re.search(r"\bevening\b", text):
        return "Evening"
    if re.search(r"\bdistance\b|\bonline\b|\be[- ]?learning\b", text):
        return "Distance"
    if re.search(r"\bmain\b", text):
        return "Main"
    if re.search(r"\bday\b|\bweekday\b", text):
        return "Day"
    return "Other"


def study_mode_for_course_unit(cu: CourseUnit) -> str:
    prog_name = ""
    prog_short = ""
    batch_name = ""
    if cu.program_batch_id:
        batch_name = cu.program_batch.name or ""
        if cu.program_batch.program_id:
            prog_name = cu.program_batch.program.name or ""
            prog_short = cu.program_batch.program.short_form or ""
    return infer_study_mode(prog_name, prog_short, batch_name)


def study_mode_sort_tuple(mode: str | None, preferred: str | None) -> tuple:
    m = mode or "Other"
    return (
        0 if preferred and m == preferred else 1,
        _STUDY_MODE_ORDER.get(m, 9),
        m,
    )


def campuses_for_course_unit(cu: CourseUnit) -> list[dict]:
    if not cu.program_batch_id or not getattr(cu.program_batch, "program_id", None):
        return []
    prog = cu.program_batch.program
    campuses = getattr(prog, "campuses", None)
    if campuses is None:
        return []
    return [
        {"id": c.id, "name": c.name, "code": getattr(c, "code", "") or ""}
        for c in campuses.all()
    ]


def campus_ids_for_course_unit(cu: CourseUnit) -> set[int]:
    return {int(c["id"]) for c in campuses_for_course_unit(cu)}


def campuses_compatible(
    source_ids: set[int],
    peer_ids: set[int],
    *,
    required_campus_id: int | None = None,
) -> bool:
    """Peer must share campus with the source programme, or include the selected campus."""
    if required_campus_id:
        if peer_ids:
            return required_campus_id in peer_ids
        # No campus on peer programme — do not mix into a campus-scoped timetable
        return False
    if not source_ids:
        return True
    if not peer_ids:
        return False
    return bool(source_ids & peer_ids)


def serialize_peer_course_unit(cu: CourseUnit, *, match_kind: str = "exact_code") -> dict:
    sem = cu.semester if cu.semester_id else None
    campuses = campuses_for_course_unit(cu)
    return {
        "id": cu.id,
        "code": cu.code,
        "name": cu.name,
        "semester_id": cu.semester_id,
        "semester_name": sem.name if sem else None,
        "year_of_study": getattr(sem, "year_of_study", None) if sem else None,
        "term_number": getattr(sem, "term_number", None) if sem else None,
        "study_mode": study_mode_for_course_unit(cu),
        "campus_ids": [c["id"] for c in campuses],
        "campus_names": [c["name"] for c in campuses],
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
    campus_id: int | None = None,
    limit: int = 120,
    same_number_limit: int = 40,
) -> list[dict]:
    """
    Peers across programmes (same study mode + campus) by code / similar name / number.
    """
    code = (source.code or "").strip()
    number = course_code_number(code)
    name = (source.name or "").strip()
    tokens = list(name_tokens(name))[:5]
    if not code and not number and not name:
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
        .prefetch_related("program_batch__program__campuses")
    )
    if exclude_semester_id:
        qs = qs.exclude(semester_id=exclude_semester_id)

    q = Q()
    if code:
        q |= Q(code__iexact=code)
        compact = normalize_course_code(code)
        if compact:
            q |= Q(code__iexact=compact)
    if number and len(number) >= 3:
        q |= Q(code__iendswith=number) | Q(code__iendswith=f" {number}")
    if name and len(name) >= 5:
        q |= Q(name__iexact=name)
        for tok in tokens:
            q |= Q(name__icontains=tok)

    if not q:
        return []

    candidates = list(qs.filter(q).order_by("code", "id")[:4000])
    preferred_mode = study_mode_for_course_unit(source)
    source_campus_ids = campus_ids_for_course_unit(source)
    required_campus_id = int(campus_id) if campus_id else None
    strong: list[dict] = []
    weak: list[dict] = []
    seen: set[int] = set()
    for peer in candidates:
        if peer.id in seen:
            continue
        match_kind = classify_peer_match(source, peer)
        if not match_kind:
            continue
        seen.add(peer.id)
        row = serialize_peer_course_unit(peer, match_kind=match_kind)
        peer_campus_ids = set(row.get("campus_ids") or [])
        if not campuses_compatible(
            source_campus_ids,
            peer_campus_ids,
            required_campus_id=required_campus_id,
        ):
            continue
        # Exact study mode from programme name (Day ≠ Main campus stream)
        if preferred_mode and preferred_mode != "Other":
            if (row.get("study_mode") or "Other") != preferred_mode:
                continue
        row["already_linked"] = bool(
            source.shared_teaching_offering_id
            and peer.shared_teaching_offering_id == source.shared_teaching_offering_id
        )
        row["same_study_mode"] = True
        row["same_campus"] = True
        if match_kind in ("exact_code", "similar_name"):
            strong.append(row)
        else:
            weak.append(row)

    def _sort_key(r: dict):
        yos = r.get("year_of_study")
        term = r.get("term_number")
        return (
            peer_match_rank(r.get("match_kind")),
            *study_mode_sort_tuple(r.get("study_mode"), preferred_mode),
            0
            if (
                r.get("match_kind") == "similar_name"
                and number
                and course_code_number(r.get("code")) == number
            )
            else 1,
            yos if isinstance(yos, int) else 99,
            term if isinstance(term, int) else 99,
            (r.get("name") or "").lower(),
            (r.get("program_name") or ""),
            (r.get("code") or ""),
        )

    strong.sort(key=_sort_key)
    weak.sort(key=_sort_key)
    out = strong + weak[:same_number_limit]
    if len(out) > limit and len(strong) < limit:
        out = strong + weak[: max(0, limit - len(strong))]
    elif len(strong) >= limit:
        out = strong
    return out


def search_course_units_for_share(
    *,
    query: str,
    exclude_semester_id: int | None = None,
    exclude_ids: list[int] | None = None,
    study_mode: str | None = None,
    campus_id: int | None = None,
    source_campus_ids: list[int] | None = None,
    limit: int = 60,
) -> list[dict]:
    """Search units filtered by study mode and campus when provided."""
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
        .prefetch_related("program_batch__program__campuses")
    )
    if exclude_semester_id:
        qs = qs.exclude(semester_id=exclude_semester_id)
    if exclude_ids:
        qs = qs.exclude(id__in=exclude_ids)

    number = course_code_number(q) if q.isdigit() or _CODE_NUMBER_RE.search(q) else ""
    filt = Q(code__icontains=q) | Q(name__icontains=q)
    if number and len(number) >= 3:
        filt |= Q(code__iendswith=number) | Q(code__iendswith=f" {number}")
    for tok in list(name_tokens(q))[:4]:
        filt |= Q(name__icontains=tok)

    preferred = (study_mode or "").strip()
    required_campus_id = int(campus_id) if campus_id else None
    source_ids = set(int(x) for x in (source_campus_ids or []) if x)
    scored: list[tuple[tuple, dict]] = []
    for cu in qs.filter(filt).order_by("code", "id")[:800]:
        row = serialize_peer_course_unit(cu, match_kind="search")
        mode = row.get("study_mode") or "Other"
        peer_campus_ids = set(row.get("campus_ids") or [])
        if preferred and preferred != "Other" and mode != preferred:
            continue
        if not campuses_compatible(
            source_ids,
            peer_campus_ids,
            required_campus_id=required_campus_id,
        ):
            continue
        if normalize_course_code(cu.code) == normalize_course_code(q):
            kind = "exact_code"
        elif names_similar(q, cu.name):
            kind = "similar_name"
        elif number and course_code_number(cu.code) == number:
            kind = "same_number"
        else:
            kind = "search"
        row["match_kind"] = kind
        row["same_study_mode"] = bool(preferred and preferred != "Other" and mode == preferred)
        row["same_campus"] = True
        yos = row.get("year_of_study")
        term = row.get("term_number")
        scored.append(
            (
                (
                    peer_match_rank(kind),
                    *study_mode_sort_tuple(mode, preferred or None),
                    yos if isinstance(yos, int) else 99,
                    term if isinstance(term, int) else 99,
                    (row.get("name") or "").lower(),
                    row.get("code") or "",
                ),
                row,
            )
        )
    scored.sort(key=lambda x: x[0])
    return [row for _, row in scored[:limit]]


def moodle_idnumber_for_course_unit(cu: CourseUnit) -> str:
    """Moodle course key: shared offering when linked, else legacy code-semester."""
    if cu.shared_teaching_offering_id:
        offering = getattr(cu, "shared_teaching_offering", None)
        if offering is not None and offering.pk:
            return offering.moodle_idnumber
        return f"STO-{cu.shared_teaching_offering_id}"
    return f"{cu.code}-{cu.semester_id}"


def normalize_shared_unit_key(code: str | None) -> str:
    """Stable shared paper key, e.g. ``ETH 1101`` → ``ETH1101``."""
    return re.sub(r"[^A-Z0-9]", "", normalize_course_code(code))


def global_term_key_for_course_unit(cu: CourseUnit) -> str:
    """Term label for Moodle parent idnumbers, e.g. ``2026-S1``."""
    sem = cu.semester if cu.semester_id else None
    batch = cu.program_batch if cu.program_batch_id else None
    ay = ""
    if batch and (batch.academic_year or "").strip():
        ay = (batch.academic_year or "").split("/")[0].strip()
    elif sem and sem.start_date:
        ay = str(sem.start_date.year)
    term = None
    if sem and sem.term_number:
        term = sem.term_number
    elif sem and sem.order:
        term = sem.order
    else:
        term = 1
    return f"{ay}-S{term}" if ay else f"S{term}"


def shared_unit_key_for_sto(sto: SharedTeachingOffering) -> str:
    catalog = getattr(sto, "catalog_unit", None)
    if catalog is not None and getattr(catalog, "code", None):
        key = normalize_shared_unit_key(catalog.code)
        if key:
            return key
    key = normalize_shared_unit_key(sto.code)
    if key:
        return key
    return f"STO{sto.pk}"


def moodle_parent_idnumber(sto: SharedTeachingOffering, term_key: str) -> str:
    return f"ndu_erp:shared:{shared_unit_key_for_sto(sto)}:{term_key}"


def moodle_group_idnumber(course_unit_id: int) -> str:
    return f"ndu_erp:group:{course_unit_id}"


def moodle_unit_idnumber(course_unit_id: int) -> str:
    return f"ndu_erp:unit:{course_unit_id}"


def offering_label_for_course_unit(cu: CourseUnit) -> str:
    prog_short = ""
    prog_name = ""
    if cu.program_batch_id and cu.program_batch.program_id:
        prog = cu.program_batch.program
        prog_short = (prog.short_form or "").strip()
        prog_name = (prog.name or "").strip()
    mode = study_mode_for_course_unit(cu)
    head = prog_short or prog_name or (cu.code or "").strip()
    if mode and mode != "Other":
        head = f"{head} {mode}".strip()
    yos = cu.semester.year_of_study if cu.semester_id else None
    if yos:
        return f"{head} · Year {yos}"
    return head


def parent_unit_id_for_sto(sto: SharedTeachingOffering) -> str | None:
    unit_id = (
        sto.course_units.filter(is_active=True)
        .order_by("id")
        .values_list("id", flat=True)
        .first()
    )
    return str(unit_id) if unit_id else None


def moodle_shared_fields_for_course_unit(
    cu: CourseUnit,
    *,
    parent_ids: dict[int, str] | None = None,
) -> dict:
    """Shared-unit metadata for Moodle LMS sync (parent course + programme groups)."""
    sto = getattr(cu, "shared_teaching_offering", None)
    is_shared = bool(cu.shared_teaching_offering_id and sto is not None)
    term_key = global_term_key_for_course_unit(cu)
    offering_id = str(cu.pk)
    fields: dict = {
        "is_shared": is_shared,
        "shared_unit_key": None,
        "offering_id": offering_id,
        "offering_label": offering_label_for_course_unit(cu),
        "parent_unit_id": None,
        "parent_idnumber": None,
        "group_idnumber": moodle_group_idnumber(cu.pk) if is_shared else None,
        "global_term_key": term_key,
        "legacy_idnumber": moodle_idnumber_for_course_unit(cu),
    }
    if not is_shared or sto is None:
        fields["idnumber"] = moodle_unit_idnumber(cu.pk)
        return fields

    sto_id = sto.pk
    if parent_ids is not None and sto_id in parent_ids:
        parent_unit_id = parent_ids[sto_id]
    else:
        parent_unit_id = parent_unit_id_for_sto(sto)
        if parent_ids is not None and parent_unit_id:
            parent_ids[sto_id] = parent_unit_id

    parent_idnumber = moodle_parent_idnumber(sto, term_key)
    fields.update(
        {
            "shared_unit_key": shared_unit_key_for_sto(sto),
            "parent_unit_id": parent_unit_id,
            "parent_idnumber": parent_idnumber,
            "idnumber": parent_idnumber,
            "shared_teaching_offering_id": sto_id,
        }
    )
    return fields


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
    merge_shared: bool = True,
) -> QuerySet[StudentCourseUnitEnrollment]:
    """Roster for LMS / marks.

    When ``merge_shared`` is true (default), merges all programme CourseUnits on the
    same SharedTeachingOffering. Moodle per-offering sync should pass ``merge_shared=False``.
    """
    if statuses is None:
        statuses = ["enrolled"]
    cu_ids = (
        linked_course_unit_ids(course_unit)
        if merge_shared
        else [course_unit.pk]
    )
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
                "year_of_study": (
                    cu.semester.year_of_study if cu.semester_id else None
                ),
                "term_number": cu.semester.term_number if cu.semester_id else None,
                "study_mode": study_mode_for_course_unit(cu),
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
