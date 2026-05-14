"""
Student Programme Enrollment API
----------------------------------
Academic enrollment is triggered by commitment fee payment confirmation.
It is NOT semester registration (that requires ≥60% tuition payment).

ADMIN endpoints (require IsAuthenticated staff):
  POST   admin/student/<student_id>/enroll            — create or reactivate enrollment
  GET    admin/enrollments                             — list all enrollments
  GET    admin/enrollment/<pk>                         — retrieve one
  PATCH  admin/enrollment/<pk>                         — update status / position
  DELETE admin/enrollment/<pk>                         — hard delete (use only on errors)

STUDENT endpoints (require IsAuthenticated; must be the enrolled student):
  GET    my_enrollment                                 — own enrollment record
  GET    my_enrollment/specializations                 — list available tracks for current term
  POST   my_enrollment/select_specialization           — save chosen track
  GET    my_enrollment/expected_courses                — curriculum lines for current term
         ?include_operational=true                     — also show CourseUnit availability
"""
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from Programs.permissions import AcademicEnrollmentAdminPermission
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from admissions.models import AdmittedStudent

from .curriculum_inheritance import curriculum_owner_program
from .models import (
    CourseUnit,
    Program,
    ProgramBatch,
    ProgramCurriculumLine,
    ProgramCurriculumVersion,
    Semester,
    StudentCurriculumOverride,
    StudentProgrammeEnrollment,
    resolve_program_default_curriculum_version,
)
from .serializers import (
    StudentProgrammeEnrollmentReadSerializer,
    StudentProgrammeEnrollmentSerializer,
)
from .specialization_rules import (
    MSG_EARLY_SPECIALIZATION,
    allowed_specialization_names_for_validation,
    compute_specialization_course_gate,
    has_complete_specialization_entry,
    is_before_specialization_entry,
    normalize_specialization,
    resolve_specialization_for_program,
)


# ===========================================================================
# Admin views
# ===========================================================================

class AdminCreateEnrollmentView(APIView):
    """Create (or re-activate) academic enrollment for a student.

    Called by admin after verifying the student has paid the commitment fee.
    Idempotent: if a record already exists, its status + position are updated
    rather than raising an error.
    """
    permission_classes = [AcademicEnrollmentAdminPermission]

    def post(self, request, student_id):
        try:
            student = AdmittedStudent.objects.select_related(
                'admitted_program', 'application'
            ).get(pk=student_id)
        except AdmittedStudent.DoesNotExist:
            return Response({'detail': 'Student not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not student.is_admitted:
            return Response(
                {'detail': 'Student must be admitted before academic enrollment can be created.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        program_id       = request.data.get('program')
        program_batch_id = request.data.get('program_batch')
        curriculum_version_id = request.data.get('curriculum_version')
        year_of_study    = request.data.get('current_year_of_study', 1)
        term_number      = request.data.get('current_term_number', 1)
        enroll_status    = request.data.get('status', 'enrolled')
        specialization_in_payload = request.data.get('specialization', None)
        specialization = (
            (normalize_specialization(specialization_in_payload) or None)
            if specialization_in_payload is not None
            else None
        )
        notes            = request.data.get('notes', '')

        if not program_id:
            # Fall back to the student's admitted program
            if student.admitted_program_id:
                program_id = student.admitted_program_id
            else:
                return Response({'detail': 'program is required.'}, status=status.HTTP_400_BAD_REQUEST)

        if not program_batch_id:
            return Response({'detail': 'program_batch is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            program = Program.objects.get(pk=program_id)
        except Program.DoesNotExist:
            return Response({'detail': 'Program not found.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            program_batch = ProgramBatch.objects.get(pk=program_batch_id, program=program)
        except ProgramBatch.DoesNotExist:
            return Response(
                {'detail': 'ProgramBatch not found or does not belong to this programme.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        curriculum_version = None
        if curriculum_version_id:
            try:
                curriculum_version = ProgramCurriculumVersion.objects.get(
                    pk=curriculum_version_id,
                    program=program,
                )
            except ProgramCurriculumVersion.DoesNotExist:
                return Response(
                    {'detail': 'curriculum_version not found for this programme.'},
                    status=status.HTTP_404_NOT_FOUND,
                )
        elif program_batch.curriculum_version_id:
            curriculum_version = program_batch.curriculum_version
        else:
            curriculum_version = resolve_program_default_curriculum_version(program)
        if curriculum_version is None:
            return Response(
                {'detail': 'No curriculum version is configured for this programme.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if specialization:
            matched, spec_err = resolve_specialization_for_program(program, specialization)
            if spec_err:
                return Response(
                    {
                        'detail': spec_err,
                        'available_specializations': allowed_specialization_names_for_validation(program),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            specialization = matched

        # Validate position
        try:
            year_of_study = int(year_of_study)
            term_number   = int(term_number)
        except (ValueError, TypeError):
            return Response(
                {'detail': 'current_year_of_study and current_term_number must be integers.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if year_of_study < 1 or year_of_study > program.max_years:
            return Response(
                {'detail': f'current_year_of_study must be between 1 and {program.max_years}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        max_terms = program.max_terms_per_year
        if term_number not in range(1, max_terms + 1):
            return Response(
                {'detail': f'current_term_number must be between 1 and {max_terms} for a {program.calendar_type}-based programme.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if enroll_status not in dict(StudentProgrammeEnrollment.STATUS_CHOICES):
            return Response(
                {'detail': f'Invalid status. Choices: {list(dict(StudentProgrammeEnrollment.STATUS_CHOICES).keys())}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Idempotent create-or-update
        enrollment, created = StudentProgrammeEnrollment.objects.get_or_create(
            student=student,
            defaults={
                'program': program,
                'program_batch': program_batch,
                'current_year_of_study': year_of_study,
                'current_term_number': term_number,
                'curriculum_version': curriculum_version,
                'specialization': specialization,
                'status': enroll_status,
                'enrolled_by': request.user,
                'notes': notes,
            },
        )

        if not created:
            # Update existing record
            enrollment.program               = program
            enrollment.program_batch         = program_batch
            enrollment.current_year_of_study = year_of_study
            enrollment.current_term_number   = term_number
            enrollment.curriculum_version    = curriculum_version
            enrollment.status                = enroll_status
            enrollment.enrolled_by           = request.user
            if specialization_in_payload is not None:
                enrollment.specialization = specialization
            if notes:
                enrollment.notes = notes
            enrollment.save()

        serializer = StudentProgrammeEnrollmentSerializer(enrollment)
        http_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(
            {**serializer.data, 'created': created},
            status=http_status,
        )


class AdminListEnrollmentsView(APIView):
    """List all student programme enrollments with optional filters."""
    permission_classes = [AcademicEnrollmentAdminPermission]

    def get(self, request):
        qs = StudentProgrammeEnrollment.objects.select_related(
            'student__application',
            'program',
            'program_batch',
            'enrolled_by',
        )

        # Filters
        filter_status = request.query_params.get('status')
        program_id    = request.query_params.get('program')
        batch_id      = request.query_params.get('program_batch')

        if filter_status:
            qs = qs.filter(status=filter_status)
        if program_id:
            qs = qs.filter(program_id=program_id)
        if batch_id:
            qs = qs.filter(program_batch_id=batch_id)

        serializer = StudentProgrammeEnrollmentSerializer(qs, many=True)
        return Response({
            'count': qs.count(),
            'results': serializer.data,
        })


class AdminEnrollmentDetailView(APIView):
    """Retrieve, partially update, or delete an enrollment record."""
    permission_classes = [AcademicEnrollmentAdminPermission]

    def _get(self, pk):
        return get_object_or_404(
            StudentProgrammeEnrollment.objects.select_related(
                'student__application', 'program', 'program_batch', 'enrolled_by'
            ),
            pk=pk,
        )

    def get(self, request, pk):
        return Response(StudentProgrammeEnrollmentSerializer(self._get(pk)).data)

    def patch(self, request, pk):
        enrollment = self._get(pk)

        # Only allow certain fields to be patched
        allowed = {
            'status', 'current_year_of_study', 'current_term_number',
            'program_batch', 'curriculum_version', 'specialization', 'notes',
        }
        data = {k: v for k, v in request.data.items() if k in allowed}

        # If status is being changed to 'enrolled', record who did it
        if data.get('status') == 'enrolled' and enrollment.status != 'enrolled':
            # enrolled_at is auto-stamped in model.save()
            data['enrolled_by'] = request.user.id

        serializer = StudentProgrammeEnrollmentSerializer(enrollment, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        enrollment = self._get(pk)
        student_id = enrollment.student.student_id
        enrollment.delete()
        return Response(
            {'detail': f'Enrollment for student {student_id} deleted.'},
            status=status.HTTP_204_NO_CONTENT,
        )


# ===========================================================================
# Student views (read-only — student sees their own data)
# ===========================================================================

class MyEnrollmentView(APIView):
    """Return the logged-in student's academic enrollment record."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            student = AdmittedStudent.objects.get(
                Q(application__applicant=request.user)
                | Q(student_user=request.user)
                | Q(reg_no=request.user.username),
                is_admitted=True,
            )
        except AdmittedStudent.DoesNotExist:
            return Response(
                {'detail': 'No admitted student record found for this user.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            enrollment = StudentProgrammeEnrollment.objects.select_related(
                'program', 'program_batch', 'curriculum_version'
            ).get(student=student)
        except StudentProgrammeEnrollment.DoesNotExist:
            return Response(
                {'detail': 'No academic enrollment found. Please contact the admissions office.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if enrollment.curriculum_version_id is None:
            fallback_version = (
                enrollment.program_batch.curriculum_version
                if enrollment.program_batch_id and enrollment.program_batch.curriculum_version_id
                else resolve_program_default_curriculum_version(enrollment.program)
            )
            if fallback_version:
                enrollment.curriculum_version = fallback_version
                enrollment.save(update_fields=['curriculum_version', 'updated_at'])

        return Response(StudentProgrammeEnrollmentReadSerializer(enrollment).data)


class MyAvailableSpecializationsView(APIView):
    """Return specialization options for the student's current year/term."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            student = AdmittedStudent.objects.get(
                Q(application__applicant=request.user)
                | Q(student_user=request.user)
                | Q(reg_no=request.user.username),
                is_admitted=True,
            )
        except AdmittedStudent.DoesNotExist:
            return Response(
                {'detail': 'No admitted student record found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            enrollment = StudentProgrammeEnrollment.objects.select_related(
                'program', 'program_batch', 'curriculum_version'
            ).get(student=student)
        except StudentProgrammeEnrollment.DoesNotExist:
            return Response(
                {'detail': 'No academic enrollment found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        if enrollment.curriculum_version_id is None:
            fallback_version = (
                enrollment.program_batch.curriculum_version
                if enrollment.program_batch_id and enrollment.program_batch.curriculum_version_id
                else resolve_program_default_curriculum_version(enrollment.program)
            )
            if fallback_version:
                enrollment.curriculum_version = fallback_version
                enrollment.save(update_fields=['curriculum_version', 'updated_at'])

        gate = compute_specialization_course_gate(
            enrollment.program,
            enrollment.curriculum_version,
            enrollment.current_year_of_study,
            enrollment.current_term_number,
            enrollment.specialization,
        )
        selected = normalize_specialization(enrollment.specialization) or None
        program = enrollment.program
        return Response(
            {
                'enrollment_id': enrollment.id,
                'program': program.name,
                'program_id': program.id,
                'year_of_study': enrollment.current_year_of_study,
                'term_number': enrollment.current_term_number,
                'selected_specialization': selected,
                'available_specializations': gate['available_specializations'],
                'requires_specialization': gate['requires_specialization'],
                'before_specialization_entry': gate['before_entry'],
                # Programme-level config
                'program_has_specialization': program.has_specialization,
                'specialization_entry_year': program.specialization_entry_year,
                'specialization_entry_term': program.specialization_entry_term,
            }
        )


class MySelectSpecializationView(APIView):
    """Persist the student's chosen specialization track."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            student = AdmittedStudent.objects.get(
                Q(application__applicant=request.user)
                | Q(student_user=request.user)
                | Q(reg_no=request.user.username),
                is_admitted=True,
            )
        except AdmittedStudent.DoesNotExist:
            return Response(
                {'detail': 'No admitted student record found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            enrollment = StudentProgrammeEnrollment.objects.select_related(
                'program', 'program_batch', 'curriculum_version'
            ).get(student=student)
        except StudentProgrammeEnrollment.DoesNotExist:
            return Response(
                {'detail': 'No academic enrollment found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        if enrollment.curriculum_version_id is None:
            fallback_version = (
                enrollment.program_batch.curriculum_version
                if enrollment.program_batch_id and enrollment.program_batch.curriculum_version_id
                else resolve_program_default_curriculum_version(enrollment.program)
            )
            if fallback_version:
                enrollment.curriculum_version = fallback_version
                enrollment.save(update_fields=['curriculum_version', 'updated_at'])

        requested = normalize_specialization(request.data.get('specialization'))
        if not requested:
            return Response(
                {'detail': 'specialization is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        program = enrollment.program
        if program.has_specialization and not has_complete_specialization_entry(program):
            return Response(
                {
                    'detail': (
                        'This programme is missing specialization entry configuration '
                        '(year and term). Please contact the registrar.'
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if is_before_specialization_entry(
            program,
            enrollment.current_year_of_study,
            enrollment.current_term_number,
        ):
            return Response(
                {'detail': MSG_EARLY_SPECIALIZATION},
                status=status.HTTP_400_BAD_REQUEST,
            )

        all_options = allowed_specialization_names_for_validation(program)
        if not all_options:
            return Response(
                {
                    'detail': 'This programme has no specialization tracks configured.',
                    'available_specializations': [],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        matched, spec_err = resolve_specialization_for_program(program, requested)
        if spec_err:
            return Response(
                {
                    'detail': spec_err,
                    'available_specializations': all_options,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        old_specialization = enrollment.specialization
        enrollment.specialization = matched
        enrollment.save(update_fields=['specialization', 'updated_at'])

        return Response(
            {
                'message': 'Specialization saved successfully.',
                'specialization': enrollment.specialization,
                'previous_specialization': old_specialization,
            },
            status=status.HTTP_200_OK,
        )


class MyExpectedCoursesView(APIView):
    """Return the expected courses for the student's current term.

    Reads ProgramCurriculumLine for their programme, year_of_study, and
    term_number.  Optionally includes operational CourseUnit availability
    (whether the admin has created a CourseUnit in the batch's semester).

    Query params:
      include_operational=true  — also show operational CourseUnit details
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            student = AdmittedStudent.objects.get(
                Q(application__applicant=request.user)
                | Q(student_user=request.user)
                | Q(reg_no=request.user.username),
                is_admitted=True,
            )
        except AdmittedStudent.DoesNotExist:
            return Response(
                {'detail': 'No admitted student record found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            enrollment = StudentProgrammeEnrollment.objects.select_related(
                'program', 'program_batch', 'curriculum_version'
            ).get(student=student)
        except StudentProgrammeEnrollment.DoesNotExist:
            return Response(
                {'detail': 'No academic enrollment found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not enrollment.is_enrolled:
            return Response(
                {
                    'detail': (
                        f'Your enrollment is currently "{enrollment.get_status_display()}". '
                        'Course access is only available when your enrollment status is "Enrolled".'
                    )
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        if enrollment.curriculum_version_id is None:
            fallback_version = (
                enrollment.program_batch.curriculum_version
                if enrollment.program_batch_id and enrollment.program_batch.curriculum_version_id
                else resolve_program_default_curriculum_version(enrollment.program)
            )
            if fallback_version:
                enrollment.curriculum_version = fallback_version
                enrollment.save(update_fields=['curriculum_version', 'updated_at'])

        gate = compute_specialization_course_gate(
            enrollment.program,
            enrollment.curriculum_version,
            enrollment.current_year_of_study,
            enrollment.current_term_number,
            enrollment.specialization,
        )
        selected_specialization = normalize_specialization(enrollment.specialization)
        available_specializations = gate['available_specializations']
        requires_specialization = gate['requires_specialization']
        if gate['requires_specialization']:
            detail = (
                'This term has specialization-specific courses. Choose your specialization first.'
                if not selected_specialization
                else (
                    f"Your selected specialization '{selected_specialization}' is not valid for this programme. "
                    'Please update your specialization.'
                )
            )
            return Response(
                {
                    'detail': detail,
                    'requires_specialization': True,
                    'available_specializations': available_specializations,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Pull curriculum lines for the current position
        lines = (
            ProgramCurriculumLine.objects
            .filter(
                program=curriculum_owner_program(enrollment.program),
                curriculum_version=enrollment.curriculum_version,
                year_of_study=enrollment.current_year_of_study,
                term_number=enrollment.current_term_number,
                is_active=True,
            )
        )
        if selected_specialization:
            lines = lines.filter(
                Q(specialization__isnull=True)
                | Q(specialization='')
                | Q(specialization__iexact=selected_specialization)
            )
        lines = lines.select_related('catalog_course').order_by('sort_order', 'catalog_course__code')

        include_operational = (
            request.query_params.get('include_operational', 'false').lower() == 'true'
        )

        # Build operational lookup only if requested — find the matching semester
        operational_map = {}
        matched_semester = None
        if include_operational:
            matched_semester = Semester.objects.filter(
                program_batch=enrollment.program_batch,
                year_of_study=enrollment.current_year_of_study,
                term_number=enrollment.current_term_number,
                is_active=True,
            ).first()
            if matched_semester:
                for cu in CourseUnit.objects.filter(semester=matched_semester, is_active=True):
                    operational_map[cu.code] = cu
                    if cu.curriculum_line_id:
                        operational_map[cu.curriculum_line_id] = cu

        # Build a set of curriculum-line IDs that are deferred for this student.
        # This must override is_available_in_portal so the portal never shows
        # a deferred course as "Available".
        deferred_line_ids = set(
            StudentCurriculumOverride.objects
            .filter(enrollment=enrollment, override_type='deferred')
            .values_list('curriculum_line_id', flat=True)
        )

        courses = []
        for line in lines:
            is_deferred = line.id in deferred_line_ids
            entry = {
                'curriculum_line_id': line.id,
                'code':               line.catalog_course.code,
                'title':              line.catalog_course.title,
                'credit_units':       str(line.catalog_course.credit_units),
                'course_type':        line.course_type,
                'elective_group':     line.elective_group,
                'specialization':     line.specialization,
                'sort_order':         line.sort_order,
                'is_deferred':        is_deferred,
            }
            if include_operational:
                cu = operational_map.get(line.id) or operational_map.get(line.catalog_course.code)
                entry['course_unit_id']       = cu.id if cu else None
                entry['course_unit_name']     = cu.name if cu else None
                # A deferred course must never appear as Available, even if a
                # matching CourseUnit exists in this semester.
                entry['is_available_in_portal'] = (cu is not None) and not is_deferred
            courses.append(entry)

        mandatory = [c for c in courses if c['course_type'] == 'mandatory']
        elective  = [c for c in courses if c['course_type'] == 'elective']

        response = {
            'enrollment_id':      enrollment.id,
            'program':            enrollment.program.name,
            'program_short':      enrollment.program.short_form,
            'program_batch':      enrollment.program_batch.name,
            'year_of_study':      enrollment.current_year_of_study,
            'term_number':        enrollment.current_term_number,
            'selected_specialization': selected_specialization or None,
            'available_specializations': available_specializations,
            'requires_specialization': requires_specialization,
            'calendar_type':      enrollment.program.calendar_type,
            'total_courses':      len(courses),
            'mandatory_count':    len(mandatory),
            'elective_count':     len(elective),
            'courses':            courses,
        }

        if include_operational:
            response['semester_id']   = matched_semester.id if matched_semester else None
            response['semester_name'] = matched_semester.name if matched_semester else None
            response['semester_found'] = matched_semester is not None

        return Response(response)
