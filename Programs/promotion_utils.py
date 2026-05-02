"""Helpers for student promotion / semester sequencing."""


def normalize_id_list(raw):
    """Coerce progression_ids / student_ids from JSON (may include strings) to int list."""
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        try:
            return [int(raw)]
        except (TypeError, ValueError):
            return []
    out = []
    for v in raw:
        if v is None or v == "":
            continue
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            continue
    return out


def get_next_semester_in_batch(current_semester):
    """
    Next semester in the same batch, using the same ordering as ProgramStructureView:
    order, start_date, id.
    Returns (next_semester_or_None, error_message_or_None).
    """
    from .models import Semester

    batch = current_semester.program_batch
    semesters = list(
        Semester.objects.filter(program_batch=batch, is_active=True).order_by(
            "order", "start_date", "id"
        )
    )
    if not semesters:
        return None, "No active semesters in this batch."

    ids = [s.id for s in semesters]
    try:
        idx = ids.index(current_semester.id)
    except ValueError:
        return (
            None,
            "This semester is not in the active sequence for its batch. "
            "Check that the semester is active.",
        )

    if idx + 1 >= len(semesters):
        seq = ", ".join(f"{s.name} (order {s.order})" for s in semesters)
        return (
            None,
            f"You are on the last semester in this batch. Semesters in order: {seq}. "
            "Add a new semester with a higher order, then refresh.",
        )

    return semesters[idx + 1], None
