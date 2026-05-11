from django.db.models import Q

from .models import CourseCatalogUnit, CourseUnit


def linked_catalog_offerings(catalog_unit: CourseCatalogUnit):
    return CourseUnit.objects.filter(
        Q(catalog_unit_id=catalog_unit.id)
        | Q(curriculum_line__catalog_course_id=catalog_unit.id)
    )


def count_unlinked_offerings_for_code(old_code: str, catalog_unit_id: int) -> int:
    """Operational rows still using the old code but not linked to this catalog row."""
    return (
        CourseUnit.objects.filter(code__iexact=old_code)
        .exclude(
            Q(catalog_unit_id=catalog_unit_id)
            | Q(curriculum_line__catalog_course_id=catalog_unit_id)
        )
        .count()
    )


def catalog_code_rename_impact(catalog_unit: CourseCatalogUnit, next_code: str) -> dict:
    normalized = (next_code or "").strip().upper()
    current = (catalog_unit.code or "").strip().upper()
    linked_count = linked_catalog_offerings(catalog_unit).count()
    if not normalized or normalized == current:
        return {
            "code_rename": False,
            "previous_code": catalog_unit.code,
            "next_code": catalog_unit.code,
            "linked_operational_count": linked_count,
            "unlinked_old_code_count": 0,
        }
    return {
        "code_rename": True,
        "previous_code": catalog_unit.code,
        "next_code": normalized,
        "linked_operational_count": linked_count,
        "unlinked_old_code_count": count_unlinked_offerings_for_code(
            catalog_unit.code,
            catalog_unit.id,
        ),
    }


def sync_catalog_unit_references(catalog_unit: CourseCatalogUnit, *, previous_code: str | None = None) -> dict:
    """Align linked operational course rows with the catalog code."""
    linked = linked_catalog_offerings(catalog_unit)
    updated = linked.update(code=catalog_unit.code)
    unlinked_left = 0
    if previous_code and previous_code != catalog_unit.code:
        unlinked_left = count_unlinked_offerings_for_code(previous_code, catalog_unit.id)
    return {
        "linked_operational_updated": updated,
        "unlinked_old_code_left": unlinked_left,
    }