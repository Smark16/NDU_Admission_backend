"""Timetable helpers: serialization, overlap checks, clash detection, teaching load."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from collections import defaultdict

from django.db.models import Q

from Programs.models import TimetableSession


DAY_LABELS = dict(TimetableSession.DAY_CHOICES)
DELIVERY_MODES = {c[0] for c in TimetableSession.DELIVERY_MODE_CHOICES}


def times_overlap(start_a: time, end_a: time, start_b: time, end_b: time) -> bool:
    return start_a < end_b and start_b < end_a


def session_duration_minutes(start: time, end: time) -> int:
    a = datetime.combine(datetime.min.date(), start)
    b = datetime.combine(datetime.min.date(), end)
    return max(0, int((b - a).total_seconds() // 60))


def session_catalog_unit_id(session: TimetableSession) -> int | None:
    cu = session.course_unit
    if cu and cu.catalog_unit_id:
        return cu.catalog_unit_id
    return None


def shares_catalog_unit(a: TimetableSession, b: TimetableSession) -> bool:
    cid = session_catalog_unit_id(a)
    return bool(cid and cid == session_catalog_unit_id(b))


def is_online_delivery(session: TimetableSession) -> bool:
    return (session.delivery_mode or "on_campus") == "online"


def requires_venue_when_published(session: TimetableSession) -> bool:
    """Published on-campus and hybrid sessions need a registered room."""
    if not session.is_published:
        return False
    return (session.delivery_mode or "on_campus") in ("on_campus", "hybrid")


def allows_parallel_room_use(session: TimetableSession, other: TimetableSession) -> bool:
    if not session.venue_id or session.venue_id != other.venue_id:
        return False
    venue = session.venue
    if not venue or not venue.allows_parallel_sessions:
        return False
    return session.session_type == "practical" and other.session_type == "practical"


def session_location_label(session: TimetableSession) -> str:
    if is_online_delivery(session):
        return "Online"
    if session.venue_id and session.venue:
        parts = [session.venue.name]
        if session.venue.building:
            parts.insert(0, session.venue.building)
        return " — ".join(parts) if len(parts) > 1 else parts[0]
    return (session.room_label or "").strip() or "TBA"


def session_campus_id(session: TimetableSession) -> int | None:
    if is_online_delivery(session):
        return None
    if session.venue_id and session.venue:
        return session.venue.campus_id
    return None


def format_short_date(value: date) -> str:
    return value.strftime("%d %b %Y")


def weekday_dates_in_range(start: date, end: date, day_of_week: int) -> list[date]:
    """Return each calendar date for a weekday between semester start and end."""
    if not start or not end or end < start:
        return []
    target_weekday = int(day_of_week) - 1  # TimetableSession: 1=Mon … 7=Sun
    current = start
    while current.weekday() != target_weekday:
        current += timedelta(days=1)
        if current > end:
            return []
    dates: list[date] = []
    while current <= end:
        dates.append(current)
        current += timedelta(days=7)
    return dates


def session_date_label(day_label: str, session_dates: list[date]) -> str:
    if not session_dates:
        return day_label or ""
    if len(session_dates) == 1:
        return format_short_date(session_dates[0])
    return f"{format_short_date(session_dates[0])} – {format_short_date(session_dates[-1])}"


def semester_period_label(name: str, start: date | None, end: date | None) -> str:
    label = (name or "Semester").strip()
    if start and end:
        return f"{label}: {format_short_date(start)} – {format_short_date(end)}"
    if start:
        return f"{label}: from {format_short_date(start)}"
    return label


def serialize_session(session: TimetableSession) -> dict:
    lecturers = []
    for lec in session.course_unit.lecturers.all():
        lecturers.append(
            {
                "id": lec.id,
                "name": lec.get_full_name() or lec.username,
                "email": lec.email,
                "primary_campus_id": lec.primary_campus_id,
            }
        )
    venue = session.venue
    cu = session.course_unit
    cat = cu.catalog_unit if cu and cu.catalog_unit_id else None
    semester = getattr(cu, "semester", None) if cu else None
    semester_start = getattr(semester, "start_date", None) if semester else None
    semester_end = getattr(semester, "end_date", None) if semester else None
    if semester_end is None and semester_start is not None:
        semester_end = semester_start
    day_label = DAY_LABELS.get(session.day_of_week, "")
    session_date = session.session_date
    if session_date:
        session_dates = [session_date]
        date_label = format_short_date(session_date)
    else:
        session_dates = (
            weekday_dates_in_range(semester_start, semester_end, session.day_of_week)
            if semester_start and semester_end
            else []
        )
        date_label = session_date_label(day_label, session_dates)
    return {
        "id": session.id,
        "course_unit_id": session.course_unit_id,
        "course_code": session.course_unit.code,
        "course_name": session.course_unit.name,
        "catalog_unit_id": cat.id if cat else None,
        "catalog_code": cat.code if cat else "",
        "catalog_name": cat.title if cat else "",
        "day_of_week": session.day_of_week,
        "day_label": day_label,
        "session_date": session_date.isoformat() if session_date else "",
        "session_dates": [d.isoformat() for d in session_dates],
        "date_label": date_label,
        "semester_name": semester.name if semester else "",
        "semester_start": semester_start.isoformat() if semester_start else "",
        "semester_end": semester_end.isoformat() if semester_end else "",
        "semester_period": semester_period_label(
            semester.name if semester else "",
            semester_start,
            semester_end,
        ),
        "start_time": session.start_time.strftime("%H:%M"),
        "end_time": session.end_time.strftime("%H:%M"),
        "duration_minutes": session_duration_minutes(session.start_time, session.end_time),
        "venue_id": session.venue_id,
        "venue_name": venue.name if venue else "",
        "venue_code": venue.code if venue else "",
        "campus_id": venue.campus_id if venue else None,
        "campus_name": venue.campus.name if venue else "",
        "room_label": session.room_label or "",
        "location": session_location_label(session),
        "session_type": session.session_type,
        "delivery_mode": session.delivery_mode or "on_campus",
        "delivery_label": dict(TimetableSession.DELIVERY_MODE_CHOICES).get(
            session.delivery_mode or "on_campus", ""
        ),
        "notes": session.notes or "",
        "is_published": session.is_published,
        "is_active": session.is_active,
        "lecturers": lecturers,
    }


@dataclass
class ScheduleValidation:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    clashes: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _active_sessions_qs(exclude_pk: int | None = None):
    qs = (
        TimetableSession.objects.filter(is_active=True)
        .select_related("course_unit", "course_unit__catalog_unit", "venue", "venue__campus")
        .prefetch_related("course_unit__lecturers")
    )
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs


def validate_session_scheduling(
    session: TimetableSession,
    *,
    exclude_pk: int | None = None,
    require_venue: bool = True,
) -> ScheduleValidation:
    """
    Hard errors: room double-book (unless online / parallel lab / shared catalog class),
    lecturer time overlap (unless shared catalog offering), multi-campus same day.
    """
    out = ScheduleValidation()
    pk = exclude_pk or session.pk

    if require_venue and requires_venue_when_published(session) and not session.venue_id:
        out.errors.append(
            "Published on-campus and hybrid sessions must use a registered classroom. "
            "Add the room under Academics → Classrooms, or set delivery to Online."
        )
    if session.room_label and not session.venue_id and not is_online_delivery(session):
        out.warnings.append(
            "Using a free-text room only. Register the room under Classrooms for reliable clash checks."
        )

    # ── Campus isolation: Room must belong to program's allowed campuses ────────
    if session.venue_id and not is_online_delivery(session):
        program = session.course_unit.semester.program_batch.program
        allowed_campuses = program.campuses.values_list("id", flat=True)
        
        if allowed_campuses and session.venue.campus_id not in allowed_campuses:
            campus_names = ", ".join(
                program.campuses.values_list("name", flat=True).order_by("name")
            )
            room_campus = session.venue.campus.name if session.venue.campus else "Unknown"
            out.errors.append(
                f'Room "{session.venue.name}" is on campus {room_campus}, '
                f'but this programme is only offered on: {campus_names}. '
                f'Select a classroom assigned to one of these campuses.'
            )
    # ───────────────────────────────────────────────────────────────────────────

    if not session.course_unit_id:
        return out

    others = _active_sessions_qs(exclude_pk=pk)
    if session.session_date:
        others = others.filter(
            Q(session_date=session.session_date)
            | Q(session_date__isnull=True, day_of_week=session.day_of_week)
        )
    else:
        others = others.filter(day_of_week=session.day_of_week)
    lecturer_ids = set(session.course_unit.lecturers.values_list("id", flat=True))
    session_campus = session_campus_id(session)
    check_room = not is_online_delivery(session) and bool(session.venue_id)

    for other in others:
        if not times_overlap(
            session.start_time, session.end_time, other.start_time, other.end_time
        ):
            continue

        shared_catalog = shares_catalog_unit(session, other)

        if check_room and session.venue_id and other.venue_id and session.venue_id == other.venue_id:
            if shared_catalog or allows_parallel_room_use(session, other):
                if allows_parallel_room_use(session, other):
                    out.warnings.append(
                        f'Room "{other.venue.name}" has parallel lab groups at this time '
                        f"({other.course_unit.code})."
                    )
                continue
            msg = (
                f'Room "{other.venue.name}" is already booked for {other.course_unit.code} '
                f"({other.start_time.strftime('%H:%M')}-{other.end_time.strftime('%H:%M')})."
            )
            out.errors.append(msg)
            out.clashes.append({"type": "venue", "message": msg, "other_session_id": other.id})

        elif (
            check_room
            and session.venue_id
            and other.venue_id
            and not is_online_delivery(other)
            and session.venue.campus_id == other.venue.campus_id
            and session.venue.name.lower() == other.venue.name.lower()
            and session.venue_id != other.venue_id
        ):
            msg = (
                f'Another room with the same name on this campus is in use for '
                f"{other.course_unit.code} at this time."
            )
            out.warnings.append(msg)
            out.clashes.append({"type": "room", "message": msg, "other_session_id": other.id})

        if lecturer_ids:
            other_lecturer_ids = set(other.course_unit.lecturers.values_list("id", flat=True))
            shared = lecturer_ids & other_lecturer_ids
            if shared:
                if shared_catalog:
                    continue
                from accounts.models import User

                names = list(
                    User.objects.filter(id__in=shared).values_list("first_name", "last_name")
                )
                who = ", ".join(" ".join(n).strip() for n in names) or "Lecturer"
                msg = (
                    f"{who} is already teaching {other.course_unit.code} "
                    f"({other.start_time.strftime('%H:%M')}-{other.end_time.strftime('%H:%M')})."
                )
                out.errors.append(msg)
                out.clashes.append({"type": "lecturer", "message": msg, "other_session_id": other.id})

    if lecturer_ids and not is_online_delivery(session):
        from accounts.models import User

        day_sessions = _active_sessions_qs(exclude_pk=pk).filter(day_of_week=session.day_of_week)
        for lec in User.objects.filter(id__in=lecturer_ids):
            if lec.allow_multi_campus_per_day:
                continue
            campuses_today = set()
            if session_campus:
                campuses_today.add(session_campus)
            for other in day_sessions:
                if is_online_delivery(other):
                    continue
                if not other.course_unit.lecturers.filter(id=lec.id).exists():
                    continue
                oc = session_campus_id(other)
                if oc:
                    campuses_today.add(oc)
            if len(campuses_today) > 1:
                msg = (
                    f"{lec.get_full_name() or lec.username} is scheduled on more than one campus "
                    f"on {DAY_LABELS.get(session.day_of_week, 'this day')}. "
                    f"Enable 'allow multi-campus per day' on their staff profile if intentional."
                )
                out.errors.append(msg)
                out.clashes.append({"type": "lecturer_campus", "message": msg})

    return out


def find_clashes_for_session(session: TimetableSession, *, exclude_pk: int | None = None) -> list[dict]:
    v = validate_session_scheduling(session, exclude_pk=exclude_pk, require_venue=False)
    return v.clashes


def sessions_for_semester(semester_id: int, *, published_only: bool = False) -> list[TimetableSession]:
    qs = (
        TimetableSession.objects.filter(
            is_active=True,
            course_unit__semester_id=semester_id,
            course_unit__is_active=True,
        )
        .select_related("course_unit", "course_unit__catalog_unit", "venue", "venue__campus")
        .prefetch_related("course_unit__lecturers")
        .order_by("day_of_week", "start_time", "course_unit__code")
    )
    if published_only:
        qs = qs.filter(is_published=True)
    return list(qs)


def build_catalog_overview(sessions: list[TimetableSession]) -> list[dict]:
    """Group sessions by shared catalog course (e.g. Christian Ethics across programmes)."""
    groups: dict[int, dict] = {}
    for s in sessions:
        cat_id = session_catalog_unit_id(s)
        if not cat_id:
            continue
        cat = s.course_unit.catalog_unit
        if cat_id not in groups:
            groups[cat_id] = {
                "catalog_unit_id": cat_id,
                "catalog_code": cat.code,
                "catalog_name": cat.title,
                "sessions": [],
                "course_unit_codes": set(),
            }
        groups[cat_id]["sessions"].append(serialize_session(s))
        groups[cat_id]["course_unit_codes"].add(s.course_unit.code)
    out = []
    for g in sorted(groups.values(), key=lambda x: (x["catalog_code"], x["catalog_name"])):
        g["course_unit_codes"] = sorted(g["course_unit_codes"])
        g["session_count"] = len(g["sessions"])
        out.append(g)
    return out


def compute_teaching_load(sessions: list[TimetableSession]) -> list[dict]:
    """Sum scheduled minutes per lecturer from a session list."""
    agg: dict[int, dict] = defaultdict(
        lambda: {
            "lecturer_id": 0,
            "name": "",
            "email": "",
            "total_minutes": 0,
            "total_hours": 0.0,
            "session_count": 0,
            "by_day": defaultdict(int),
        }
    )
    for s in sessions:
        mins = session_duration_minutes(s.start_time, s.end_time)
        for lec in s.course_unit.lecturers.all():
            row = agg[lec.id]
            row["lecturer_id"] = lec.id
            row["name"] = lec.get_full_name() or lec.username
            row["email"] = lec.email or ""
            row["total_minutes"] += mins
            row["session_count"] += 1
            row["by_day"][s.day_of_week] = row["by_day"].get(s.day_of_week, 0) + mins

    result = []
    for row in agg.values():
        by_day = [
            {
                "day_of_week": d,
                "day_label": DAY_LABELS.get(d, ""),
                "minutes": row["by_day"][d],
                "hours": round(row["by_day"][d] / 60, 2),
            }
            for d in sorted(row["by_day"].keys())
        ]
        total_m = row["total_minutes"]
        result.append(
            {
                "lecturer_id": row["lecturer_id"],
                "name": row["name"],
                "email": row["email"],
                "total_minutes": total_m,
                "total_hours": round(total_m / 60, 2),
                "session_count": row["session_count"],
                "by_day": by_day,
            }
        )
    result.sort(key=lambda x: (-x["total_minutes"], x["name"]))
    return result


def resolve_semester_campuses(semester) -> tuple[list[dict], int | None]:
    program = semester.program_batch.program
    campuses = [
        {"id": c.id, "name": c.name, "code": c.code}
        for c in program.campuses.all().order_by("name")
    ]
    suggested = campuses[0]["id"] if len(campuses) == 1 else None
    return campuses, suggested


def parse_delivery_mode(value: str | None) -> str:
    mode = (value or "on_campus").strip().lower()
    if mode not in DELIVERY_MODES:
        raise ValueError(f"delivery_mode must be one of: {', '.join(sorted(DELIVERY_MODES))}.")
    return mode
