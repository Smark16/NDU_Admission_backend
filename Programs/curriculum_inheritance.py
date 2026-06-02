"""Curriculum inheritance between campus-local programme rows."""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Program, ProgramCurriculumLine, ProgramCurriculumVersion


def curriculum_owner_program(program: Program | None) -> Program | None:
    """Programme row that owns or supplies curriculum versions for ``program``."""
    if not program:
        return None
    if (
        program.curriculum_mode == Program.CURRICULUM_MODE_INHERITED
        and program.curriculum_source_program_id
    ):
        return program.curriculum_source_program
    return program


def curriculum_versions_queryset(program: Program):
    """Versions visible for a programme row (owned or inherited)."""
    owner = curriculum_owner_program(program)
    if not owner:
        return ProgramCurriculumVersion.objects.none()
    return ProgramCurriculumVersion.objects.filter(program=owner)


def resolve_effective_curriculum_version(program: Program, batch=None):
    """Curriculum version used for blueprint lookups (Load from Curriculum, etc.).

    Inherited programmes read lines from the master programme. If a batch still
    points at a local (child) curriculum version from before inheritance was
    linked, ignore it and use the master's default version instead.
    """
    from .models import resolve_program_default_curriculum_version

    owner = curriculum_owner_program(program)
    if not owner:
        return None

    version = None
    if batch is not None and getattr(batch, "curriculum_version_id", None):
        version = batch.curriculum_version
        if version.program_id != owner.id:
            version = None

    if version is None:
        version = resolve_program_default_curriculum_version(program)
    return version


def curriculum_version_matches_program(program: Program, version: ProgramCurriculumVersion) -> bool:
    if not program or not version:
        return False
    owner = curriculum_owner_program(program)
    return owner is not None and version.program_id == owner.id


def program_allows_curriculum_writes(program: Program) -> bool:
    return program.curriculum_allows_writes


def assert_program_allows_curriculum_writes(program: Program) -> None:
    if not program_allows_curriculum_writes(program):
        raise ValidationError(
            "This programme inherits its curriculum and cannot be edited until it is forked."
        )


def validate_curriculum_source_assignment(
    program: Program,
    source_program: Program | None,
    *,
    mode: str,
) -> None:
    if mode == Program.CURRICULUM_MODE_INHERITED:
        if source_program is None:
            raise ValidationError({'curriculum_source_program': 'A master programme is required.'})
        if source_program.pk == program.pk:
            raise ValidationError({'curriculum_source_program': 'A programme cannot inherit from itself.'})
        if source_program.curriculum_mode == Program.CURRICULUM_MODE_INHERITED:
            raise ValidationError(
                {'curriculum_source_program': 'Only curriculum masters can be inheritance sources.'}
            )
    elif mode == Program.CURRICULUM_MODE_MASTER:
        if source_program is not None:
            raise ValidationError(
                {'curriculum_source_program': 'Clear the source when switching to master mode.'}
            )
    elif mode == Program.CURRICULUM_MODE_FORKED:
        if source_program is not None:
            raise ValidationError(
                {'curriculum_source_program': 'Forked programmes own their curriculum locally.'}
            )


def link_program_to_curriculum_source(program: Program, source_program: Program) -> Program:
    validate_curriculum_source_assignment(
        program,
        source_program,
        mode=Program.CURRICULUM_MODE_INHERITED,
    )
    program.curriculum_source_program = source_program
    program.curriculum_mode = Program.CURRICULUM_MODE_INHERITED
    program.save(update_fields=['curriculum_source_program', 'curriculum_mode', 'updated_at'])
    return program


def unlink_program_curriculum_source(program: Program) -> Program:
    program.curriculum_source_program = None
    program.curriculum_mode = Program.CURRICULUM_MODE_MASTER
    program.save(update_fields=['curriculum_source_program', 'curriculum_mode', 'updated_at'])
    return program


def relink_forked_program_to_source(program: Program, source_program: Program) -> Program:
    if program.curriculum_mode != Program.CURRICULUM_MODE_FORKED:
        raise ValidationError('Only forked programmes can re-link to a master curriculum.')
    validate_curriculum_source_assignment(
        program,
        source_program,
        mode=Program.CURRICULUM_MODE_INHERITED,
    )
    program.curriculum_source_program = source_program
    program.curriculum_mode = Program.CURRICULUM_MODE_INHERITED
    program.save(update_fields=['curriculum_source_program', 'curriculum_mode', 'updated_at'])
    return program


@transaction.atomic
def fork_curriculum_version(program: Program, source_version_id: int) -> ProgramCurriculumVersion:
    if program.curriculum_mode != Program.CURRICULUM_MODE_INHERITED:
        raise ValidationError('Only inherited programmes can fork curriculum.')

    source_version = ProgramCurriculumVersion.objects.select_related('program').filter(
        pk=source_version_id,
    ).first()
    if not source_version:
        raise ValidationError({'version_id': 'Curriculum version not found.'})

    owner = curriculum_owner_program(program)
    if not owner or source_version.program_id != owner.id:
        raise ValidationError({'version_id': 'Version is not available from the linked master programme.'})

    new_version = ProgramCurriculumVersion.objects.create(
        program=program,
        name=source_version.name,
        description=source_version.description,
        is_active=source_version.is_active,
        is_default=True,
        minimum_graduation_load=source_version.minimum_graduation_load,
        origin_version=source_version,
        is_local_fork=True,
    )
    ProgramCurriculumVersion.objects.filter(program=program).exclude(pk=new_version.pk).update(
        is_default=False,
    )

    line_rows = source_version.lines.all().values(
        'catalog_course_id',
        'year_of_study',
        'term_number',
        'course_type',
        'elective_group',
        'specialization',
        'sort_order',
        'is_active',
    )
    ProgramCurriculumLine.objects.bulk_create(
        [
            ProgramCurriculumLine(
                program=program,
                curriculum_version=new_version,
                **row,
            )
            for row in line_rows
        ]
    )

    program.curriculum_source_program = None
    program.curriculum_mode = Program.CURRICULUM_MODE_FORKED
    program.save(update_fields=['curriculum_source_program', 'curriculum_mode', 'updated_at'])
    return new_version


def curriculum_context_payload(program: Program) -> dict:
    owner = curriculum_owner_program(program)
    source = program.curriculum_source_program
    return {
        'program_id': program.id,
        'curriculum_mode': program.curriculum_mode,
        'curriculum_source_program_id': program.curriculum_source_program_id,
        'curriculum_source_program_name': source.name if source else None,
        'curriculum_owner_program_id': owner.id if owner else program.id,
        'curriculum_is_read_only': not program.curriculum_allows_writes,
        'local_versions_count': program.curriculum_versions.count(),
    }
