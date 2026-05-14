from __future__ import annotations

from collections import defaultdict
from typing import Any

PROGRAM_CORE_SUMMARY_SQL = """
SELECT
    pc.id AS program_core_id,
    pc.name AS program_core_name,
    pc.minimumDuration AS minimum_duration,
    COUNT(DISTINCT p.id) AS campus_program_count,
    COUNT(DISTINCT c.id) AS course_count
FROM program_core pc
LEFT JOIN program p ON p.programCoreId = pc.id
LEFT JOIN course c ON c.programId = p.id
GROUP BY pc.id, pc.name, pc.minimumDuration
ORDER BY pc.name
"""

PROGRAM_CORE_CAMPUS_SQL = """
SELECT
    pc.id AS program_core_id,
    pc.name AS program_core_name,
    p.id AS program_id,
    p.code AS program_code,
    p.programNumber AS program_number,
    camp.id AS campus_id,
    camp.name AS campus_name,
    COUNT(DISTINCT c.id) AS course_count
FROM program_core pc
JOIN program p ON p.programCoreId = pc.id
JOIN campus camp ON camp.id = p.campusId
LEFT JOIN course c ON c.programId = p.id
WHERE pc.id = %s
GROUP BY
    pc.id, pc.name, p.id, p.code, p.programNumber, camp.id, camp.name
ORDER BY camp.name, p.code
"""

COURSE_SLOT_SQL = """
SELECT
    p.id AS program_id,
    camp.name AS campus_name,
    p.code AS program_code,
    c.id AS course_id,
    c.code AS course_code,
    c.name AS course_name,
    c.creditUnits AS credit_units,
    c.courseType AS course_type,
    c.status AS course_status,
    c.isSpecial AS is_special,
    sl.level AS year_of_study,
    sl.semesterSession AS term_number,
    sc.name AS specialization_name
FROM program p
JOIN campus camp ON camp.id = p.campusId
JOIN course c ON c.programId = p.id
JOIN semester_level sl ON sl.id = c.semesterLevelId
LEFT JOIN specialisation sp ON sp.id = c.specialisationId
LEFT JOIN specialisation_core sc ON sc.id = sp.specialisationCoreId
WHERE p.programCoreId = %s
ORDER BY camp.name, p.code, sl.level, sl.semesterSession, c.code
"""

SPECIALISATION_CORE_SQL = """
SELECT id, name, description
FROM specialisation_core
WHERE programCoreId = %s
ORDER BY name
"""


def _slot_key(row: dict[str, Any]) -> tuple:
    return (
        (row.get("course_code") or "").strip().upper(),
        int(row.get("year_of_study") or 0),
        int(row.get("term_number") or 0),
        (row.get("specialization_name") or "").strip().lower(),
    )


def compare_campus_curricula(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_program: dict[int, list[dict[str, Any]]] = defaultdict(list)
    program_meta: dict[int, dict[str, Any]] = {}
    for row in rows:
        program_id = int(row["program_id"])
        by_program[program_id].append(row)
        program_meta[program_id] = {
            "program_id": program_id,
            "campus_name": row.get("campus_name"),
            "program_code": row.get("program_code"),
        }

    comparisons: list[dict[str, Any]] = []
    program_ids = sorted(by_program.keys())
    for left_id in program_ids:
        left_slots = {_slot_key(row) for row in by_program[left_id]}
        for right_id in program_ids:
            if right_id <= left_id:
                continue
            right_slots = {_slot_key(row) for row in by_program[right_id]}
            shared = left_slots & right_slots
            only_left = left_slots - right_slots
            only_right = right_slots - left_slots
            union = left_slots | right_slots
            comparisons.append(
                {
                    "left": program_meta[left_id],
                    "right": program_meta[right_id],
                    "shared_slots": len(shared),
                    "only_left": len(only_left),
                    "only_right": len(only_right),
                    "overlap_pct": round((len(shared) / len(union) * 100.0), 1) if union else 100.0,
                }
            )
    return comparisons


def map_legacy_course_type(course_type: Any) -> str:
    """Map ARMS courseType enum to portal curriculum line course_type."""
    try:
        value = int(course_type)
    except (TypeError, ValueError):
        return "mandatory"
    # ARMS CourseType: common pattern Mandatory=0, Elective=1 (verify on live DB).
    return "elective" if value == 1 else "mandatory"
