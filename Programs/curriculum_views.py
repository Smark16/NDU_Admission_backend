"""
Programme Curriculum Mapping API
---------------------------------
Endpoints (wired in Programs/urls.py under api/program/):

  GET  program/<program_id>/curriculum              — list all lines for a programme
       ?grouped=true                                — nest by year → term
       ?year=1                                      — filter by year_of_study
       ?term=2                                      — filter by term_number
       ?course_type=mandatory|elective              — filter by type
       ?specialization=Accounting                    — filter by track name (case-insensitive)
       ?active_only=true                            — only is_active=True lines (default false)

  POST program/<program_id>/curriculum              — add a new curriculum line

  GET  program/<program_id>/curriculum/summary      — credit completeness summary only

  GET  semester/<semester_id>/curriculum_suggestions
         Shows which curriculum courses match this semester's year/term position
         and whether each one is already present as a CourseUnit in this semester.
         Requires the semester to have year_of_study + term_number set.

  GET  curriculum/<pk>                              — retrieve one line
  PATCH curriculum/<pk>                             — partial update
  DELETE curriculum/<pk>                            — remove a line
"""
from collections import defaultdict

from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    CourseCatalogUnit,
    CourseUnit,
    Program,
    ProgramCurriculumLine,
    ProgramCurriculumVersion,
    Semester,
    resolve_program_default_curriculum_version,
)
from .serializers import ProgramCurriculumLineSerializer, ProgramCurriculumVersionSerializer


class ListCreateCurriculumView(APIView):
    """List or create curriculum lines for a specific programme."""

    permission_classes = [IsAuthenticated]

    @staticmethod
    def _resolve_version(program, request):
        version_id = request.query_params.get('curriculum_version') or request.data.get('curriculum_version')
        if version_id:
            try:
                version = ProgramCurriculumVersion.objects.get(pk=int(version_id), program=program)
            except (ValueError, ProgramCurriculumVersion.DoesNotExist):
                return None, Response(
                    {'detail': 'Invalid curriculum_version for this programme.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return version, None

        version = resolve_program_default_curriculum_version(program)
        if not version:
            return None, Response(
                {'detail': 'No curriculum version exists for this programme. Create one first.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return version, None

    def get(self, request, program_id):
        program = get_object_or_404(Program, pk=program_id)
        curriculum_version, error = self._resolve_version(program, request)
        if error:
            return error

        qs = ProgramCurriculumLine.objects.select_related(
            'catalog_course',
            'curriculum_version',
        ).filter(
            program=program,
            curriculum_version=curriculum_version,
        )

        # --- optional filters ---
        year = request.query_params.get('year')
        term = request.query_params.get('term')
        course_type = request.query_params.get('course_type')
        specialization = request.query_params.get('specialization')
        active_only = request.query_params.get('active_only', 'false').lower() == 'true'

        if year:
            try:
                qs = qs.filter(year_of_study=int(year))
            except ValueError:
                return Response(
                    {'detail': 'year must be an integer.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        if term:
            try:
                qs = qs.filter(term_number=int(term))
            except ValueError:
                return Response(
                    {'detail': 'term must be an integer.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        if course_type:
            if course_type not in ('mandatory', 'elective'):
                return Response(
                    {'detail': 'course_type must be "mandatory" or "elective".'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            qs = qs.filter(course_type=course_type)
        if specialization is not None:
            specialization = specialization.strip()
            if specialization == "":
                qs = qs.filter(Q(specialization__isnull=True) | Q(specialization=''))
            else:
                qs = qs.filter(specialization__iexact=specialization)
        if active_only:
            qs = qs.filter(is_active=True)

        serializer = ProgramCurriculumLineSerializer(qs, many=True)
        flat_data = serializer.data

        # credit summary is always included (single aggregation query)
        credit_summary = program.credit_summary(curriculum_version=curriculum_version)

        # --- grouped response ---
        grouped = request.query_params.get('grouped', 'false').lower() == 'true'
        if grouped:
            return Response(self._build_grouped(program, curriculum_version, flat_data, credit_summary))

        return Response({
            'program_id': program.id,
            'program_name': program.name,
            'program_short_form': program.short_form,
            'curriculum_version': ProgramCurriculumVersionSerializer(curriculum_version).data,
            'calendar_type': program.calendar_type,
            'credit_summary': credit_summary,
            'count': len(flat_data),
            'results': flat_data,
        })

    def post(self, request, program_id):
        program = get_object_or_404(Program, pk=program_id)
        curriculum_version, error = ListCreateCurriculumView._resolve_version(program, request)
        if error:
            return error
        curriculum_version, error = self._resolve_version(program, request)
        if error:
            return error

        # inject program into payload so the serializer can validate against it
        data = request.data.copy()
        data['program'] = program.id
        data['curriculum_version'] = curriculum_version.id

        serializer = ProgramCurriculumLineSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _build_grouped(program, curriculum_version, flat_data, credit_summary):
        """
        Returns nested structure:
        {
            program_id: ...,
            calendar_type: ...,
            credit_summary: { ... },
            curriculum: [
                {
                    year_of_study: 1,
                    terms: [
                        {
                            term_number: 1,
                            courses: [ <line>, ... ]
                        },
                        ...
                    ]
                },
                ...
            ]
        }
        """
        # year → term → [lines]
        tree = defaultdict(lambda: defaultdict(list))
        for line in flat_data:
            tree[line['year_of_study']][line['term_number']].append(line)

        curriculum = []
        for yr in sorted(tree.keys()):
            terms = []
            for term in sorted(tree[yr].keys()):
                terms.append({
                    'term_number': term,
                    'courses': tree[yr][term],
                })
            curriculum.append({
                'year_of_study': yr,
                'terms': terms,
            })

        return {
            'program_id': program.id,
            'program_name': program.name,
            'program_short_form': program.short_form,
            'curriculum_version': ProgramCurriculumVersionSerializer(curriculum_version).data,
            'calendar_type': program.calendar_type,
            'credit_summary': credit_summary,
            'curriculum': curriculum,
        }


class CurriculumSummaryView(APIView):
    """Return only the credit completeness summary for a programme's curriculum."""

    permission_classes = [IsAuthenticated]

    def get(self, request, program_id):
        program = get_object_or_404(Program, pk=program_id)
        curriculum_version, error = ListCreateCurriculumView._resolve_version(program, request)
        if error:
            return error
        return Response({
            'program_id': program.id,
            'program_name': program.name,
            'program_short_form': program.short_form,
            'curriculum_version': ProgramCurriculumVersionSerializer(curriculum_version).data,
            'calendar_type': program.calendar_type,
            'credit_summary': program.credit_summary(curriculum_version=curriculum_version),
        })


class CurriculumVersionListCreateView(APIView):
    """List/create curriculum versions for a programme."""

    permission_classes = [IsAuthenticated]

    def get(self, request, program_id):
        program = get_object_or_404(Program, pk=program_id)
        qs = ProgramCurriculumVersion.objects.filter(program=program).order_by('-is_default', 'name')
        active_only = request.query_params.get('active_only', 'false').lower() == 'true'
        if active_only:
            qs = qs.filter(is_active=True)
        return Response({
            'program_id': program.id,
            'count': qs.count(),
            'versions': ProgramCurriculumVersionSerializer(qs, many=True).data,
        })

    def post(self, request, program_id):
        program = get_object_or_404(Program, pk=program_id)
        data = request.data.copy()
        data['program'] = program.id
        clone_from_id = data.pop('clone_from_version_id', None) or request.data.get('clone_from_version_id')
        serializer = ProgramCurriculumVersionSerializer(data=data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        version = serializer.save()
        requested_default = str(request.data.get('is_default')).lower() in ('1', 'true', 'yes')

        # Ensure at least one default per programme.
        if requested_default:
            ProgramCurriculumVersion.objects.filter(program=program).exclude(pk=version.pk).update(is_default=False)
            if not version.is_default:
                version.is_default = True
                version.save(update_fields=['is_default', 'updated_at'])
        elif not program.curriculum_versions.exclude(pk=version.pk).exists():
            version.is_default = True
            version.save(update_fields=['is_default', 'updated_at'])

        if clone_from_id:
            try:
                source = ProgramCurriculumVersion.objects.get(pk=int(clone_from_id), program=program)
            except (ValueError, ProgramCurriculumVersion.DoesNotExist):
                version.delete()
                return Response(
                    {'detail': 'clone_from_version_id is invalid for this programme.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            rows = source.lines.all().values(
                'program_id',
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
                [ProgramCurriculumLine(curriculum_version=version, **r) for r in rows]
            )

        return Response(
            ProgramCurriculumVersionSerializer(version).data,
            status=status.HTTP_201_CREATED,
        )


class CurriculumVersionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _get(self, pk):
        return get_object_or_404(ProgramCurriculumVersion, pk=pk)

    def patch(self, request, pk):
        version = self._get(pk)
        serializer = ProgramCurriculumVersionSerializer(version, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        updated = serializer.save()

        # If marked as default, clear default from siblings.
        is_default_in_payload = str(request.data.get('is_default')).lower() in ('1', 'true', 'yes')
        if is_default_in_payload:
            ProgramCurriculumVersion.objects.filter(program=updated.program).exclude(pk=updated.pk).update(is_default=False)
            if not updated.is_default:
                updated.is_default = True
                updated.save(update_fields=['is_default', 'updated_at'])

        # Never allow programme to have zero defaults.
        if not updated.program.curriculum_versions.filter(is_default=True).exists():
            updated.is_default = True
            updated.save(update_fields=['is_default', 'updated_at'])

        return Response(ProgramCurriculumVersionSerializer(updated).data)

    def delete(self, request, pk):
        version = self._get(pk)
        if version.program_batches.exists() or version.student_enrollments.exists():
            return Response(
                {'detail': 'Cannot delete version mapped to program batches or student enrollments.'},
                status=status.HTTP_409_CONFLICT,
            )
        was_default = version.is_default
        program = version.program
        version.delete()
        if was_default:
            replacement = program.curriculum_versions.order_by('id').first()
            if replacement:
                replacement.is_default = True
                replacement.save(update_fields=['is_default', 'updated_at'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class CurriculumSuggestionsForSemesterView(APIView):
    """Show which curriculum courses belong to a semester's position.

    For each active ProgramCurriculumLine that matches the semester's
    (program, year_of_study, term_number), reports whether a CourseUnit
    already exists in this semester for it.  This is the practical
    "load from curriculum" helper for the admin UI.

    Requires the semester to have year_of_study + term_number set.
    Returns HTTP 400 if the semester has no curriculum position.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, semester_id):
        semester = get_object_or_404(
            Semester.objects.select_related('program_batch__program'),
            pk=semester_id,
        )

        if semester.year_of_study is None or semester.term_number is None:
            return Response(
                {
                    'detail': (
                        "This semester has no curriculum position set. "
                        "Set year_of_study and term_number on the semester first."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        program = semester.program_batch.program
        curriculum_version = (
            semester.program_batch.curriculum_version
            or resolve_program_default_curriculum_version(program)
        )
        if not curriculum_version:
            return Response(
                {'detail': 'No curriculum version configured for this programme/batch.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # All active curriculum lines for this programme at this position
        curriculum_lines = (
            ProgramCurriculumLine.objects
            .filter(
                program=program,
                curriculum_version=curriculum_version,
                year_of_study=semester.year_of_study,
                term_number=semester.term_number,
                is_active=True,
            )
            .select_related('catalog_course')
            .order_by('sort_order', 'catalog_course__code')
        )

        # CourseUnits already in this semester that are curriculum-linked
        # Key: curriculum_line_id → course_unit id
        existing_map = {
            cu.curriculum_line_id: cu.id
            for cu in CourseUnit.objects.filter(
                semester=semester,
                curriculum_line__isnull=False,
            ).only('id', 'curriculum_line_id')
        }

        # Also check by code — handles courses added manually without the FK
        existing_codes = set(
            CourseUnit.objects.filter(semester=semester)
            .values_list('code', flat=True)
        )

        suggestions = []
        for line in curriculum_lines:
            course_unit_id = existing_map.get(line.id)
            already_added_by_code = line.catalog_course.code in existing_codes
            suggestions.append({
                'curriculum_line_id': line.id,
                'catalog_course_id': line.catalog_course.id,
                'code': line.catalog_course.code,
                'title': line.catalog_course.title,
                'credit_units': str(line.catalog_course.credit_units),
                'course_type': line.course_type,
                'elective_group': line.elective_group,
                'sort_order': line.sort_order,
                # True if a CourseUnit with the curriculum_line FK exists in this semester
                'already_linked': course_unit_id is not None,
                # True if any CourseUnit with this code exists (linked or manual)
                'already_present': already_added_by_code,
                'course_unit_id': course_unit_id,
            })

        return Response({
            'semester_id': semester.id,
            'semester_name': semester.name,
            'year_of_study': semester.year_of_study,
            'term_number': semester.term_number,
            'program_id': program.id,
            'program_name': program.name,
            'program_short_form': program.short_form,
            'curriculum_version': ProgramCurriculumVersionSerializer(curriculum_version).data,
            'calendar_type': program.calendar_type,
            'total_curriculum_lines': len(suggestions),
            'total_already_present': sum(1 for s in suggestions if s['already_present']),
            'total_missing': sum(1 for s in suggestions if not s['already_present']),
            'suggestions': suggestions,
        })


class CurriculumLineDetailView(APIView):
    """Retrieve, partially update, or delete a single curriculum line."""

    permission_classes = [IsAuthenticated]

    def _get_object(self, pk):
        return get_object_or_404(ProgramCurriculumLine, pk=pk)

    def get(self, request, pk):
        line = self._get_object(pk)
        return Response(ProgramCurriculumLineSerializer(line).data)

    def patch(self, request, pk):
        line = self._get_object(pk)
        serializer = ProgramCurriculumLineSerializer(
            line, data=request.data, partial=True
        )
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        line = self._get_object(pk)

        # ── Operational-use guard ─────────────────────────────────────────────
        # Check whether any live academic work already depends on this line.
        offered_units = line.offered_course_units.all()

        has_enrollments = offered_units.filter(student_enrollments__isnull=False).exists()
        has_lecturers   = offered_units.filter(lecturers__isnull=False).exists()
        has_overrides   = line.student_overrides.exists()
        has_course_units = offered_units.exists()

        if has_enrollments:
            return Response(
                {
                    'detail': (
                        "This curriculum course cannot be deleted because it is already in active "
                        "academic use. Students are already enrolled in course units created from it."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )

        if has_overrides:
            return Response(
                {
                    'detail': (
                        "This curriculum course cannot be deleted because one or more students have "
                        "academic overrides (exemptions, deferrals, or credit transfers) linked to it."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )

        if has_lecturers:
            return Response(
                {
                    'detail': (
                        "This curriculum course cannot be deleted because lecturers are already "
                        "assigned to course units created from it."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )

        if has_course_units:
            return Response(
                {
                    'detail': (
                        "This curriculum course cannot be deleted because semester course units "
                        "have already been created from it. Deactivate the line instead."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )
        # ─────────────────────────────────────────────────────────────────────

        line.delete()
        return Response(
            {'detail': 'Curriculum line removed.'},
            status=status.HTTP_204_NO_CONTENT,
        )


class BulkUploadCurriculumView(APIView):
    """
    POST /api/program/program/<program_id>/curriculum/bulk_upload

    Accepts a multipart CSV file (field name: "file") with columns:
      course_code*, year_of_study*, term_number*, course_type*,
      elective_group, specialization, sort_order
    (* = required)

    Rows whose (catalog_course, year, term) already exist for this programme
    are skipped (no error). Rows with unknown course codes or bad values are
    reported in the errors list.  All valid rows are bulk-created atomically.

    Returns:
      {
        created: <int>,
        skipped: <int>,
        error_count: <int>,
        skipped_detail: [{ row, course_code, reason }],
        errors:         [{ row, course_code, reason }],
      }
    """

    permission_classes = [IsAuthenticated]

    REQUIRED_COLS = {'course_code', 'year_of_study', 'term_number', 'course_type'}

    def post(self, request, program_id):
        import csv
        import io
        from django.db import transaction as db_transaction

        program = get_object_or_404(Program, pk=program_id)

        uploaded = request.FILES.get('file')
        if not uploaded:
            return Response(
                {'detail': 'No file received. Send the CSV as multipart field "file".'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not uploaded.name.lower().endswith('.csv'):
            return Response(
                {'detail': 'Only .csv files are accepted.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            text = uploaded.read().decode('utf-8-sig')   # strip BOM if present
        except UnicodeDecodeError:
            return Response(
                {'detail': 'Could not decode file — ensure it is UTF-8 encoded.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        reader = csv.DictReader(io.StringIO(text))

        if not reader.fieldnames:
            return Response(
                {'detail': 'CSV file is empty or has no header row.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        headers = {h.strip().lower() for h in reader.fieldnames}
        missing_cols = self.REQUIRED_COLS - headers
        if missing_cols:
            return Response(
                {'detail': f'Missing required columns: {", ".join(sorted(missing_cols))}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Build catalog lookup (upper-cased code → instance)
        catalog_lookup = {
            c.code.upper(): c
            for c in CourseCatalogUnit.objects.all()
        }

        # Existing mappings for this programme (to skip duplicates)
        existing = set(
            ProgramCurriculumLine.objects
            .filter(program=program, curriculum_version=curriculum_version)
            .values_list('catalog_course_id', 'year_of_study', 'term_number')
        )

        to_create = []
        skipped = []
        errors = []

        for row_num, raw in enumerate(reader, start=2):  # row 1 = header
            row = {k.strip().lower(): (v or '').strip() for k, v in raw.items() if k}

            course_code = row.get('course_code', '').upper()

            if not course_code:
                errors.append({'row': row_num, 'course_code': '', 'reason': 'course_code is blank'})
                continue

            catalog_course = catalog_lookup.get(course_code)
            if not catalog_course:
                errors.append({
                    'row': row_num,
                    'course_code': course_code,
                    'reason': f'"{course_code}" not found in the course catalog',
                })
                continue

            try:
                year = int(row['year_of_study'])
                term = int(row['term_number'])
            except (KeyError, ValueError):
                errors.append({
                    'row': row_num,
                    'course_code': course_code,
                    'reason': 'year_of_study and term_number must be whole numbers',
                })
                continue

            course_type = row.get('course_type', '').lower()
            if course_type not in ('mandatory', 'elective'):
                errors.append({
                    'row': row_num,
                    'course_code': course_code,
                    'reason': f'course_type must be "mandatory" or "elective", got "{course_type}"',
                })
                continue

            key = (catalog_course.id, year, term)
            if key in existing:
                skipped.append({
                    'row': row_num,
                    'course_code': course_code,
                    'reason': 'Already mapped for this programme / year / term',
                })
                continue

            try:
                sort_order = int(row.get('sort_order') or '0')
            except ValueError:
                sort_order = 0

            elective_group  = row.get('elective_group') or None
            specialization  = row.get('specialization') or None

            to_create.append(ProgramCurriculumLine(
                program=program,
                curriculum_version=curriculum_version,
                catalog_course=catalog_course,
                year_of_study=year,
                term_number=term,
                course_type=course_type,
                elective_group=elective_group,
                specialization=specialization,
                sort_order=sort_order,
            ))
            existing.add(key)   # prevent intra-file duplicates

        if to_create:
            with db_transaction.atomic():
                ProgramCurriculumLine.objects.bulk_create(to_create)

        return Response({
            'curriculum_version_id': curriculum_version.id,
            'created': len(to_create),
            'skipped': len(skipped),
            'error_count': len(errors),
            'skipped_detail': skipped,
            'errors': errors,
        }, status=status.HTTP_200_OK)
