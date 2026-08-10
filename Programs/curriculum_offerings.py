"""
Instantiate operational CourseUnits on batch semesters from the curriculum blueprint.

Curriculum lines are the plan; CourseUnits are what a cohort runs. This module
keeps offerings in sync so staff do not need a separate “Load from curriculum”
step for normal setups.
"""
from __future__ import annotations

import logging

from django.db import transaction

logger = logging.getLogger(__name__)


def sync_semester_curriculum_offerings(semester) -> dict:
    """
    Create missing CourseUnits on ``semester`` from active curriculum lines
    matching its (year_of_study, term_number).

    Idempotent: skips codes / curriculum_line FKs already present.
    Returns ``{created, skipped, missing_position, no_version}``.
    """
    from Programs.curriculum_inheritance import (
        curriculum_owner_program,
        resolve_effective_curriculum_version,
    )
    from Programs.models import CourseUnit, ProgramCurriculumLine

    result = {
        "semester_id": getattr(semester, "pk", None),
        "created": 0,
        "skipped": 0,
        "missing_position": False,
        "no_version": False,
    }

    if semester is None or not getattr(semester, "pk", None):
        return result
    if semester.year_of_study is None or semester.term_number is None:
        result["missing_position"] = True
        return result

    batch = semester.program_batch
    if batch is None:
        return result
    program = batch.program
    if program is None:
        return result

    owner = curriculum_owner_program(program)
    curriculum_version = resolve_effective_curriculum_version(program, batch)
    if not curriculum_version:
        result["no_version"] = True
        return result

    lines = list(
        ProgramCurriculumLine.objects.filter(
            program=owner,
            curriculum_version=curriculum_version,
            year_of_study=semester.year_of_study,
            term_number=semester.term_number,
            is_active=True,
        )
        .select_related("catalog_course")
        .order_by("sort_order", "catalog_course__code")
    )
    if not lines:
        return result

    existing_line_ids = set(
        CourseUnit.objects.filter(
            semester=semester, curriculum_line_id__isnull=False
        ).values_list("curriculum_line_id", flat=True)
    )
    existing_codes = {
        (c or "").strip().upper()
        for c in CourseUnit.objects.filter(semester=semester).values_list(
            "code", flat=True
        )
    }

    created_rows = []
    with transaction.atomic():
        for line in lines:
            catalog = line.catalog_course
            if catalog is None:
                result["skipped"] += 1
                continue
            code = (catalog.code or "").strip()
            if not code:
                result["skipped"] += 1
                continue
            code_key = code.upper()
            if line.id in existing_line_ids or code_key in existing_codes:
                result["skipped"] += 1
                continue

            cu = CourseUnit(
                name=(catalog.title or code).strip(),
                code=code,
                credit_units=catalog.credit_units,
                catalog_unit=catalog,
                curriculum_line=line,
                semester=semester,
                program_batch=batch,
                is_active=True,
            )
            created_rows.append(cu)
            existing_line_ids.add(line.id)
            existing_codes.add(code_key)

        if created_rows:
            CourseUnit.objects.bulk_create(created_rows)
            result["created"] = len(created_rows)
            logger.info(
                "Synced %s curriculum offerings onto semester %s (%s Y%sT%s)",
                result["created"],
                semester.pk,
                getattr(program, "short_form", program.pk),
                semester.year_of_study,
                semester.term_number,
            )

    return result


def sync_batch_curriculum_offerings(batch) -> dict:
    """Sync all positioned semesters on a program batch."""
    from Programs.models import Semester

    totals = {"created": 0, "skipped": 0, "semesters": 0}
    if batch is None or not getattr(batch, "pk", None):
        return totals

    semesters = Semester.objects.filter(
        program_batch=batch,
        year_of_study__isnull=False,
        term_number__isnull=False,
    )
    for semester in semesters:
        totals["semesters"] += 1
        r = sync_semester_curriculum_offerings(semester)
        totals["created"] += r["created"]
        totals["skipped"] += r["skipped"]
    return totals


def sync_program_curriculum_offerings(program) -> dict:
    """Sync offerings for every active batch of a programme."""
    from Programs.models import ProgramBatch

    totals = {"created": 0, "skipped": 0, "batches": 0}
    if program is None or not getattr(program, "pk", None):
        return totals

    batches = ProgramBatch.objects.filter(program=program, is_active=True)
    for batch in batches:
        totals["batches"] += 1
        r = sync_batch_curriculum_offerings(batch)
        totals["created"] += r["created"]
        totals["skipped"] += r["skipped"]
    return totals


def _count_missing_offerings_for_semester(semester) -> dict:
    """Return how many curriculum lines would be created on ``semester`` (no writes)."""
    from Programs.curriculum_inheritance import (
        curriculum_owner_program,
        resolve_effective_curriculum_version,
    )
    from Programs.models import CourseUnit, ProgramCurriculumLine

    result = {"would_create": 0, "skipped": 0}
    if semester is None or semester.year_of_study is None or semester.term_number is None:
        return result
    batch = semester.program_batch
    if batch is None or batch.program is None:
        return result

    program = batch.program
    owner = curriculum_owner_program(program)
    version = resolve_effective_curriculum_version(program, batch)
    if not version:
        return result

    lines = ProgramCurriculumLine.objects.filter(
        program=owner,
        curriculum_version=version,
        year_of_study=semester.year_of_study,
        term_number=semester.term_number,
        is_active=True,
    ).select_related("catalog_course")
    existing_line_ids = set(
        CourseUnit.objects.filter(
            semester=semester, curriculum_line_id__isnull=False
        ).values_list("curriculum_line_id", flat=True)
    )
    existing_codes = {
        (c or "").strip().upper()
        for c in CourseUnit.objects.filter(semester=semester).values_list("code", flat=True)
    }
    for line in lines:
        catalog = line.catalog_course
        if catalog is None:
            result["skipped"] += 1
            continue
        code_key = (catalog.code or "").strip().upper()
        if not code_key or line.id in existing_line_ids or code_key in existing_codes:
            result["skipped"] += 1
            continue
        result["would_create"] += 1
    return result


def sync_all_curriculum_offerings(*, program_id=None, batch_id=None, dry_run=False) -> dict:
    """
    Sync missing curriculum CourseUnits onto all positioned semesters.

    Targets semesters that already have year_of_study + term_number set.
    Idempotent: only creates offerings that are still missing.
    """
    from Programs.models import ProgramBatch, Semester

    totals = {
        "created": 0,
        "skipped": 0,
        "programs": 0,
        "batches": 0,
        "semesters": 0,
        "dry_run": bool(dry_run),
    }

    if batch_id:
        batches = ProgramBatch.objects.filter(pk=batch_id, is_active=True).select_related("program")
    elif program_id:
        batches = ProgramBatch.objects.filter(
            program_id=program_id, is_active=True
        ).select_related("program")
    else:
        batches = ProgramBatch.objects.filter(is_active=True).select_related("program")

    seen_programs = set()
    for batch in batches.iterator():
        if batch.program_id not in seen_programs:
            seen_programs.add(batch.program_id)
            totals["programs"] += 1
        totals["batches"] += 1
        semesters = Semester.objects.filter(
            program_batch=batch,
            year_of_study__isnull=False,
            term_number__isnull=False,
        )
        for semester in semesters:
            totals["semesters"] += 1
            if dry_run:
                r = _count_missing_offerings_for_semester(semester)
                totals["created"] += r["would_create"]
                totals["skipped"] += r["skipped"]
            else:
                r = sync_semester_curriculum_offerings(semester)
                totals["created"] += r["created"]
                totals["skipped"] += r["skipped"]

    return totals


def sync_offerings_for_curriculum_line(line) -> dict:
    """
    When a curriculum line is added/updated, push it onto matching semesters
    across active batches of programmes using that curriculum.
    """
    from Programs.curriculum_inheritance import resolve_effective_curriculum_version
    from Programs.models import Program, ProgramBatch, Semester

    totals = {"created": 0, "skipped": 0, "semesters": 0}
    if line is None or not line.is_active:
        return totals
    if not line.year_of_study or not line.term_number:
        return totals

    owner_id = line.program_id
    version_id = line.curriculum_version_id

    # Batches on the owner programme + inheriting programmes that resolve to this version
    candidate_programs = list(
        Program.objects.filter(pk=owner_id)
        | Program.objects.filter(curriculum_source_program_id=owner_id)
    )
    for program in candidate_programs:
        for batch in ProgramBatch.objects.filter(program=program, is_active=True):
            eff = resolve_effective_curriculum_version(program, batch)
            if not eff or eff.id != version_id:
                continue
            semesters = Semester.objects.filter(
                program_batch=batch,
                year_of_study=line.year_of_study,
                term_number=line.term_number,
            )
            for semester in semesters:
                totals["semesters"] += 1
                r = sync_semester_curriculum_offerings(semester)
                totals["created"] += r["created"]
                totals["skipped"] += r["skipped"]
    return totals
