"""Course units, student enrollment, lecturers, and semester promotion (academic registration workflow)."""
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from django.db.models import Q

from rest_framework import generics, status
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
# ====================================Course Unit Enrollment==================================================================

class ListCourseUnitEnrollments(generics.ListAPIView):
    """List all students enrolled in a specific course unit"""
    permission_classes = [IsAdminUser]
    
    def get_queryset(self):
        course_unit_id = self.kwargs.get('course_unit_id')
        from .models import StudentCourseUnitEnrollment
        return StudentCourseUnitEnrollment.objects.filter(
            course_unit_id=course_unit_id
        ).select_related('student', 'student__application', 'course_unit')
    
    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        data = []
        for enrollment in queryset:
            student = enrollment.student
            data.append({
                'id': enrollment.id,
                'student_id': student.student_id,
                'reg_no': student.reg_no,
                'name': student.full_name,
                'enrollment_date': enrollment.enrollment_date,
                'status': enrollment.status,
                'grade': enrollment.grade,
            })
        return Response(data, status=status.HTTP_200_OK)

class GetAvailableStudentsForCourseUnit(APIView):
    """Get list of students available for enrollment in a course unit"""
    permission_classes = [IsAdminUser]
    
    def get(self, request, course_unit_id):
        from .models import CourseUnit, StudentCourseUnitEnrollment
        from admissions.models import AdmittedStudent
        
        try:
            course_unit = CourseUnit.objects.get(id=course_unit_id)
        except CourseUnit.DoesNotExist:
            return Response({'detail': 'Course unit not found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Get the program batch from the course unit
        program_batch = course_unit.program_batch
        if not program_batch:
            return Response({'detail': 'Course unit is not associated with a program batch'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Get all admitted students for the same program
        program = program_batch.program
        admitted_students = AdmittedStudent.objects.filter(
            admitted_program=program,
            is_admitted=True
        ).select_related('application', 'application__applicant')
        
        # Get already enrolled student IDs
        enrolled_student_ids = StudentCourseUnitEnrollment.objects.filter(
            course_unit=course_unit
        ).values_list('student_id', flat=True)
        
        # Filter out already enrolled students
        available_students = admitted_students.exclude(id__in=enrolled_student_ids)
        
        data = []
        for student in available_students:
            data.append({
                'id': student.id,
                'student_id': student.student_id,
                'reg_no': student.reg_no,
                'name': student.full_name,
            })
        
        return Response(data, status=status.HTTP_200_OK)

class EnrollStudentsInCourseUnit(APIView):
    """Enroll one or more students in a course unit"""
    permission_classes = [IsAdminUser]
    
    def post(self, request, course_unit_id):
        from .models import CourseUnit, StudentCourseUnitEnrollment
        from admissions.models import AdmittedStudent
        
        student_ids = request.data.get('student_ids', [])
        if not student_ids:
            return Response({'detail': 'No student IDs provided'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            course_unit = CourseUnit.objects.get(id=course_unit_id)
        except CourseUnit.DoesNotExist:
            return Response({'detail': 'Course unit not found'}, status=status.HTTP_404_NOT_FOUND)
        
        enrolled = []
        errors = []
        
        with transaction.atomic():
            for student_id in student_ids:
                try:
                    student = AdmittedStudent.objects.get(id=student_id)
                    # Check if already enrolled
                    if StudentCourseUnitEnrollment.objects.filter(
                        student=student,
                        course_unit=course_unit
                    ).exists():
                        errors.append(f"Student {student.student_id} is already enrolled")
                        continue
                    
                    enrollment = StudentCourseUnitEnrollment.objects.create(
                        student=student,
                        course_unit=course_unit,
                        status='enrolled'
                    )
                    enrolled.append({
                        'id': enrollment.id,
                        'student_id': student.student_id,
                        'name': student.full_name,
                    })
                except AdmittedStudent.DoesNotExist:
                    errors.append(f"Student with ID {student_id} not found")
                except Exception as e:
                    errors.append(f"Error enrolling student {student_id}: {str(e)}")
        
        return Response({
            'enrolled': enrolled,
            'errors': errors,
            'message': f'Successfully enrolled {len(enrolled)} student(s)'
        }, status=status.HTTP_201_CREATED)

class AssignLecturersToCourseUnit(APIView):
    """Assign lecturers (staff) to a course unit"""
    permission_classes = [IsAdminUser]
    
    def post(self, request, course_unit_id):
        from .models import CourseUnit
        from accounts.models import User
        
        lecturer_ids = request.data.get('lecturer_ids', [])
        
        if not lecturer_ids:
            return Response({'detail': 'No lecturers selected'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            course_unit = CourseUnit.objects.get(id=course_unit_id)
        except CourseUnit.DoesNotExist:
            return Response({'detail': 'Course unit not found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Validate that all IDs are staff members
        lecturers = User.objects.filter(id__in=lecturer_ids, is_staff=True, is_active=True)
        if lecturers.count() != len(lecturer_ids):
            return Response({'detail': 'Some selected users are not active staff members'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Assign lecturers
        # Get previously assigned lecturers before the update
        previous_lecturers = set(course_unit.lecturers.values_list('id', flat=True))
        course_unit.lecturers.set(lecturers)

        # Mark newly assigned users as lecturers
        lecturers.update(is_lecturer=True)

        # Remove is_lecturer flag from users who were unassigned and have no other courses
        removed_ids = previous_lecturers - set(lecturer_ids)
        if removed_ids:
            from .models import CourseUnit as CU
            for uid in removed_ids:
                still_has_courses = CU.objects.filter(lecturers__id=uid).exists()
                if not still_has_courses:
                    User.objects.filter(id=uid).update(is_lecturer=False)

        return Response({
            'message': f'Successfully assigned {lecturers.count()} lecturer(s) to {course_unit.name}',
            'lecturers': [{'id': l.id, 'name': l.get_full_name(), 'email': l.email} for l in lecturers]
        }, status=status.HTTP_200_OK)

class RemoveLecturerFromCourseUnit(APIView):
    """Remove a lecturer from a course unit"""
    permission_classes = [IsAdminUser]
    
    def post(self, request, course_unit_id):
        from .models import CourseUnit
        from accounts.models import User
        
        lecturer_id = request.data.get('lecturer_id')
        
        if not lecturer_id:
            return Response({'detail': 'Lecturer ID is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            course_unit = CourseUnit.objects.get(id=course_unit_id)
            lecturer = User.objects.get(id=lecturer_id, is_staff=True)
        except CourseUnit.DoesNotExist:
            return Response({'detail': 'Course unit not found'}, status=status.HTTP_404_NOT_FOUND)
        except User.DoesNotExist:
            return Response({'detail': 'Lecturer not found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Remove lecturer
        course_unit.lecturers.remove(lecturer)

        # Clear is_lecturer if no other courses remain
        from .models import CourseUnit as CU
        if not CU.objects.filter(lecturers=lecturer).exists():
            lecturer.is_lecturer = False
            lecturer.save(update_fields=['is_lecturer'])

        return Response({
            'message': f'Successfully removed {lecturer.get_full_name()} from {course_unit.name}'
        }, status=status.HTTP_200_OK)

class GetCourseUnitLecturers(APIView):
    """Get all lecturers assigned to a course unit"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request, course_unit_id):
        from .models import CourseUnit
        
        try:
            course_unit = CourseUnit.objects.prefetch_related('lecturers').get(id=course_unit_id)
        except CourseUnit.DoesNotExist:
            return Response({'detail': 'Course unit not found'}, status=status.HTTP_404_NOT_FOUND)
        
        lecturers = [
            {
                'id': lecturer.id,
                'name': lecturer.get_full_name(),
                'email': lecturer.email,
                'phone': lecturer.phone,
                'role': lecturer.role
            }
            for lecturer in course_unit.lecturers.all()
        ]
        
        return Response({'lecturers': lecturers}, status=status.HTTP_200_OK)

class GetAvailableCoursesForRegistration(APIView):
    """Get available courses that a student can register for.

    Course context is derived from StudentProgrammeEnrollment (commitment-fee gate):
      - program_batch  → which batch the student belongs to
      - current_year_of_study + current_term_number → which Semester to scope to

    Courses are filtered to those where admin has enrolled the student
    (StudentCourseUnitEnrollment) but the student has not yet registered
    (registration_date is null).

    Falls back to the old StudentSemesterProgression method only when no
    StudentProgrammeEnrollment record exists (backward compatibility).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .models import (
            CourseUnit,
            Semester,
            StudentCourseUnitEnrollment,
            StudentProgrammeEnrollment,
            StudentSemesterProgression,
        )
        from admissions.models import AdmittedStudent

        user = request.user

        try:
            from django.db.models import Q
            student = AdmittedStudent.objects.select_related(
                'admitted_program', 'admitted_batch'
            ).filter(
                Q(application__applicant=user) | Q(student_user=user) | Q(reg_no=user.username),
                is_admitted=True,
            ).first()
            if not student:
                raise AdmittedStudent.DoesNotExist
        except AdmittedStudent.DoesNotExist:
            return Response({'detail': 'You are not an admitted student'}, status=status.HTTP_403_FORBIDDEN)

        from .models import StudentCurriculumOverride, ProgramCurriculumLine

        # ── Resolve StudentProgrammeEnrollment ────────────────────────────────
        spe = None
        using_spe = False
        try:
            spe = StudentProgrammeEnrollment.objects.select_related(
                'program_batch', 'program', 'curriculum_version'
            ).get(student=student)
            using_spe = spe.is_enrolled
        except StudentProgrammeEnrollment.DoesNotExist:
            pass

        # ── Already registered course ids (always excluded) ───────────────────
        registered_course_ids = set(StudentCourseUnitEnrollment.objects.filter(
            student=student,
            registration_date__isnull=False,
        ).values_list('course_unit_id', flat=True))

        # ── Collect available CourseUnit ids via override-aware logic ─────────
        available_course_unit_ids = set()
        overrides = {}

        if using_spe:
            from .specialization_rules import compute_specialization_course_gate, normalize_specialization

            curr_year = spe.current_year_of_study
            curr_term = spe.current_term_number
            selected_specialization = normalize_specialization(spe.specialization)
            curriculum_version = spe.curriculum_version
            if curriculum_version is None:
                curriculum_version = (
                    spe.program_batch.curriculum_version
                    if spe.program_batch_id and spe.program_batch.curriculum_version_id
                    else None
                )
                if curriculum_version is None:
                    from .models import resolve_program_default_curriculum_version
                    curriculum_version = resolve_program_default_curriculum_version(spe.program)
                if curriculum_version is not None:
                    spe.curriculum_version = curriculum_version
                    spe.save(update_fields=['curriculum_version', 'updated_at'])

            # ── Step 1: Load all overrides for this enrollment ────────────────
            overrides = {
                o.curriculum_line_id: o
                for o in StudentCurriculumOverride.objects.filter(enrollment=spe)
            }
            excluded_line_ids = {
                lid for lid, o in overrides.items()
                if o.override_type in ('exempted', 'transferred', 'deferred')
            }

            # ── Step 1b: specialization requirement (same rule as expected courses) ──
            gate = compute_specialization_course_gate(
                spe.program,
                curriculum_version,
                curr_year,
                curr_term,
                spe.specialization,
            )
            if gate['requires_specialization']:
                sel = normalize_specialization(spe.specialization)
                detail = (
                    'This term has specialization-specific courses. Choose your specialization first.'
                    if not sel
                    else (
                        f"Your selected specialization '{sel}' is not valid for this programme. "
                        'Please update your specialization.'
                    )
                )
                return Response(
                    {
                        'detail': detail,
                        'requires_specialization': True,
                        'available_specializations': gate['available_specializations'],
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # ── Step 2: Standard courses (blueprint year/term = current) ──────
            # Curriculum lines at current position with no blocking override
            standard_lines = ProgramCurriculumLine.objects.filter(
                program=spe.program,
                curriculum_version=curriculum_version,
                year_of_study=curr_year,
                term_number=curr_term,
                is_active=True,
            ).exclude(id__in=excluded_line_ids)
            if selected_specialization:
                standard_lines = standard_lines.filter(
                    Q(specialization__isnull=True)
                    | Q(specialization='')
                    | Q(specialization__iexact=selected_specialization)
                )

            # Find the operational Semester for current position
            current_semester = Semester.objects.filter(
                program_batch=spe.program_batch,
                year_of_study=curr_year,
                term_number=curr_term,
                is_active=True,
            ).first()

            if current_semester:
                # Map code → CourseUnit for fast lookup
                cu_map = {
                    cu.code: cu.id
                    for cu in CourseUnit.objects.filter(
                        semester=current_semester, is_active=True
                    )
                }
                for line in standard_lines:
                    cid = cu_map.get(line.catalog_course.code)
                    if cid:
                        available_course_unit_ids.add(cid)

            # ── Step 3: Deferred / backlog overrides effective NOW ────────────
            active_overrides = [
                o for o in overrides.values()
                if o.override_type in ('deferred', 'backlog')
                and o.effective_year_of_study == curr_year
                and o.effective_term_number == curr_term
            ]
            for override in active_overrides:
                # Find operational semester for the override's blueprint position
                blueprint_year = override.curriculum_line.year_of_study
                blueprint_term = override.curriculum_line.term_number
                target_semester = Semester.objects.filter(
                    program_batch=spe.program_batch,
                    year_of_study=blueprint_year,
                    term_number=blueprint_term,
                    is_active=True,
                ).first()
                if target_semester:
                    cu = CourseUnit.objects.filter(
                        code=override.curriculum_line.catalog_course.code,
                        semester=target_semester,
                        is_active=True,
                    ).first()
                    if cu:
                        available_course_unit_ids.add(cu.id)
                else:
                    # No semester for the original blueprint term — look in current semester
                    if current_semester:
                        cu = CourseUnit.objects.filter(
                            code=override.curriculum_line.catalog_course.code,
                            semester=current_semester,
                            is_active=True,
                        ).first()
                        if cu:
                            available_course_unit_ids.add(cu.id)

            # ── Step 4: If no semester found, fall back to whole batch ─────────
            if not available_course_unit_ids and not current_semester:
                available_course_unit_ids = set(
                    CourseUnit.objects.filter(
                        program_batch=spe.program_batch,
                        is_active=True,
                    ).exclude(id__in=registered_course_ids)
                    .values_list('id', flat=True)
                )

        else:
            # ── Legacy fallback (no SPE): use old StudentSemesterProgression ──
            fallback_semesters = list(
                StudentSemesterProgression.objects.filter(
                    student=student, status='active'
                ).values_list('semester_id', flat=True)
            )
            if fallback_semesters:
                available_course_unit_ids = set(
                    CourseUnit.objects.filter(
                        semester_id__in=fallback_semesters,
                        is_active=True,
                    ).values_list('id', flat=True)
                )
            else:
                # Last resort: admin-assigned but unregistered
                available_course_unit_ids = set(
                    StudentCourseUnitEnrollment.objects.filter(
                        student=student,
                        registration_date__isnull=True,
                    ).values_list('course_unit_id', flat=True)
                )

        # ── Remove already-registered ─────────────────────────────────────────
        available_course_unit_ids -= registered_course_ids

        # ── Fetch final queryset ──────────────────────────────────────────────
        available_courses = CourseUnit.objects.filter(
            id__in=available_course_unit_ids,
        ).select_related(
            'semester', 'program_batch', 'program_batch__program',
        ).prefetch_related('lecturers')

        courses_data = [
            {
                'id': course.id,
                'code': course.code,
                'name': course.name,
                'credit_units': float(course.credit_units) if course.credit_units else None,
                'semester': {
                    'id': course.semester.id if course.semester else None,
                    'name': course.semester.name if course.semester else None,
                },
                'program_batch': {
                    'id': course.program_batch.id if course.program_batch else None,
                    'name': course.program_batch.name if course.program_batch else None,
                },
                'lecturers': [
                    {'id': lec.id, 'name': lec.get_full_name()}
                    for lec in course.lecturers.all()
                ],
            }
            for course in available_courses
        ]

        debug_info = {}
        if settings.DEBUG:
            debug_info = {
                'student_id': student.student_id,
                'using_spe': using_spe,
                'spe_status': spe.status if spe else None,
                'spe_year': spe.current_year_of_study if spe else None,
                'spe_term': spe.current_term_number if spe else None,
                'spe_specialization': spe.specialization if spe else None,
                'entry_year': spe.entry_year_of_study if spe else None,
                'entry_term': spe.entry_term_number if spe else None,
                'override_count': len(overrides),
                'already_registered': len(registered_course_ids),
                'total_available': len(courses_data),
            }

        return Response({
            'available_courses': courses_data,
            'total_available': len(courses_data),
            'debug': debug_info,
        }, status=status.HTTP_200_OK)

class GetStudentEnrolledCourses(APIView):
    """Get all courses enrolled by the logged-in student"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .models import (
            StudentCourseUnitEnrollment,
            StudentProgrammeEnrollment,
            StudentCurriculumOverride,
        )
        from admissions.models import AdmittedStudent

        user = request.user

        try:
            from django.db.models import Q
            admitted_student = AdmittedStudent.objects.select_related(
                'admitted_program',
                'admitted_campus',
                'admitted_batch'
            ).filter(
                Q(application__applicant=user) | Q(student_user=user) | Q(reg_no=user.username)
            ).first()
            if not admitted_student:
                raise AdmittedStudent.DoesNotExist
        except AdmittedStudent.DoesNotExist:
            return Response({
                'detail': 'You are not an admitted student',
                'enrolled_courses': []
            }, status=status.HTTP_200_OK)

        # ── Academic position ─────────────────────────────────────────────
        current_year = None
        current_term = None
        spe = None
        try:
            spe = StudentProgrammeEnrollment.objects.get(student=admitted_student)
            current_year = spe.current_year_of_study
            current_term = spe.current_term_number
        except StudentProgrammeEnrollment.DoesNotExist:
            pass

        # ── Deferred courses: sourced directly from StudentCurriculumOverride ──
        # Do NOT attempt to match against StudentCourseUnitEnrollment — deferred
        # overrides exist at the blueprint (ProgramCurriculumLine) level and may
        # have no corresponding CourseUnit enrollment at all. Even when a CourseUnit
        # exists, CourseUnit.curriculum_line is SET_NULL/nullable so matching by
        # curriculum_line_id against enrollment rows is unreliable.
        deferred_courses = []
        deferred_cl_ids = set()  # used below to exclude these from active list

        if spe:
            deferred_overrides = StudentCurriculumOverride.objects.filter(
                enrollment=spe,
                override_type='deferred',
            ).select_related(
                'curriculum_line',
                'curriculum_line__catalog_course',
            )
            for ov in deferred_overrides:
                cl = ov.curriculum_line
                if not cl:
                    continue
                cat = cl.catalog_course
                deferred_cl_ids.add(cl.id)
                deferred_courses.append({
                    'curriculum_line_id': cl.id,
                    'course_code': cat.code if cat else '—',
                    'course_name': cat.title if cat else '—',
                    'credit_units': float(cat.credit_units) if cat and cat.credit_units else None,
                    'blueprint_year': cl.year_of_study,
                    'blueprint_term': cl.term_number,
                    'deferred_until': {
                        'year': ov.effective_year_of_study,
                        'term': ov.effective_term_number,
                    },
                })

        # ── Active enrollments: from StudentCourseUnitEnrollment ─────────────
        enrollments = StudentCourseUnitEnrollment.objects.filter(
            student=admitted_student
        ).select_related(
            'course_unit',
            'course_unit__semester',
            'course_unit__semester__program_batch',
            'course_unit__program_batch',
            'course_unit__program_batch__program'
        ).prefetch_related('course_unit__lecturers').order_by('-enrollment_date')

        active_courses = []

        for enrollment in enrollments:
            course_unit = enrollment.course_unit

            # Skip if this enrollment corresponds to a deferred curriculum line
            if course_unit.curriculum_line_id and course_unit.curriculum_line_id in deferred_cl_ids:
                continue

            semester = course_unit.semester
            program_batch = course_unit.program_batch or (semester.program_batch if semester else None)

            lecturers = [
                {
                    'id': lecturer.id,
                    'name': lecturer.get_full_name(),
                    'email': lecturer.email
                }
                for lecturer in course_unit.lecturers.all()
            ]

            active_courses.append({
                'enrollment_id': enrollment.id,
                'course_unit_id': course_unit.id,
                'course_code': course_unit.code,
                'course_name': course_unit.name,
                'credit_units': float(course_unit.credit_units) if course_unit.credit_units else None,
                'semester': {
                    'id': semester.id if semester else None,
                    'name': semester.name if semester else None,
                    'order': semester.order if semester else None,
                } if semester else None,
                'program_batch': {
                    'id': program_batch.id if program_batch else None,
                    'name': program_batch.name if program_batch else None,
                } if program_batch else None,
                'program': {
                    'id': program_batch.program.id if program_batch and program_batch.program else None,
                    'name': program_batch.program.name if program_batch and program_batch.program else None,
                } if program_batch and program_batch.program else None,
                'lecturers': lecturers,
                'enrollment_date': enrollment.enrollment_date,
                'registration_date': enrollment.registration_date.isoformat() if enrollment.registration_date else None,
                'is_registered': enrollment.registration_date is not None,
                'status': enrollment.status,
                'grade': enrollment.grade,
            })

        registered_courses = [c for c in active_courses if c['is_registered']]

        # Build passport photo URL if available
        photo_url = None
        try:
            photo = admitted_student.application.passport_photo
            if photo and photo.name:
                photo_url = request.build_absolute_uri(photo.url)
        except Exception:
            pass

        return Response({
            'student_id': admitted_student.student_id,
            'reg_no': admitted_student.reg_no,
            'student_name': admitted_student.full_name,
            'program': admitted_student.admitted_program.name if admitted_student.admitted_program else None,
            'campus': admitted_student.admitted_campus.name if admitted_student.admitted_campus else None,
            'passport_photo': photo_url,
            'current_year_of_study': current_year,
            'current_term_number': current_term,
            'enrolled_courses': active_courses,
            'deferred_courses': deferred_courses,
            'registered_courses': registered_courses,
            'total_enrolled': len(active_courses),
            'total_deferred': len(deferred_courses),
            'total_registered': len(registered_courses),
            'total_courses': len(active_courses) + len(deferred_courses),
        }, status=status.HTTP_200_OK)

class CheckLecturerStatus(APIView):
    """Check if the logged-in user is a lecturer"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user = request.user
        
        # Lecturer access can be granted either by:
        # - explicit flag (set by admin or by course-unit assignment flows), OR
        # - being assigned the "Lecturer" role group, OR
        # - having course units assigned
        in_lecturer_group = False
        try:
            in_lecturer_group = user.groups.filter(name__iexact="Lecturer").exists()
        except Exception:
            in_lecturer_group = False

        is_lecturer = bool(user.is_lecturer) or in_lecturer_group or user.course_units.exists()
        
        return Response({
            'is_lecturer': is_lecturer,
            'lecturer_name': user.get_full_name() if is_lecturer else None,
            'email': user.email if is_lecturer else None,
        }, status=status.HTTP_200_OK)

class GetLecturerCourses(APIView):
    """Get all courses assigned to the logged-in lecturer"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        from .models import StudentCourseUnitEnrollment
        
        user = request.user
        
        # Get all course units assigned to this lecturer
        course_units = user.course_units.filter(is_active=True).select_related(
            'semester',
            'semester__program_batch',
            'program_batch',
            'program_batch__program'
        ).prefetch_related('student_enrollments__student').order_by('code', 'name')
        
        if not course_units.exists():
            return Response({
                'lecturer_name': user.get_full_name(),
                'email': user.email,
                'total_courses': 0,
                'total_students': 0,
                'assigned_courses': []
            }, status=status.HTTP_200_OK)
        
        assigned_courses = []
        total_students = 0
        
        for course_unit in course_units:
            semester = course_unit.semester
            program_batch = course_unit.program_batch or (semester.program_batch if semester else None)
            
            # Get enrolled students count
            enrollments = StudentCourseUnitEnrollment.objects.filter(
                course_unit=course_unit,
                status='enrolled'
            ).select_related('student')
            
            students_count = enrollments.count()
            total_students += students_count
            
            # Get student details
            students = []
            for enrollment in enrollments[:50]:  # Limit to first 50 for performance
                student = enrollment.student
                students.append({
                    'student_id': student.student_id,
                    'reg_no': student.reg_no,
                    'name': student.full_name,
                    'enrollment_date': enrollment.enrollment_date,
                    'status': enrollment.status,
                })
            
            assigned_courses.append({
                'course_unit_id': course_unit.id,
                'course_code': course_unit.code,
                'course_name': course_unit.name,
                'credit_units': float(course_unit.credit_units) if course_unit.credit_units else None,
                'semester': {
                    'id': semester.id if semester else None,
                    'name': semester.name if semester else None,
                    'order': semester.order if semester else None,
                } if semester else None,
                'program_batch': {
                    'id': program_batch.id if program_batch else None,
                    'name': program_batch.name if program_batch else None,
                } if program_batch else None,
                'program': {
                    'id': program_batch.program.id if program_batch and program_batch.program else None,
                    'name': program_batch.program.name if program_batch and program_batch.program else None,
                    'short_form': program_batch.program.short_form if program_batch and program_batch.program else None,
                } if program_batch and program_batch.program else None,
                'students_count': students_count,
                'students': students,
            })
        
        return Response({
            'lecturer_name': user.get_full_name(),
            'email': user.email,
            'total_courses': len(assigned_courses),
            'total_students': total_students,
            'assigned_courses': assigned_courses
        }, status=status.HTTP_200_OK)

class AdminRegisterStudentForCourses(APIView):
    """Admin endpoint to register a student for courses"""
    permission_classes = [IsAdminUser]
    
    def post(self, request, student_id):
        from .models import CourseUnit, StudentCourseUnitEnrollment
        from admissions.models import AdmittedStudent
        from django.utils import timezone
        
        course_unit_ids = request.data.get('course_unit_ids', [])
        if not course_unit_ids:
            return Response({'detail': 'No course unit IDs provided'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            student = AdmittedStudent.objects.get(id=student_id, is_admitted=True)
        except AdmittedStudent.DoesNotExist:
            return Response({'detail': 'Student not found'}, status=status.HTTP_404_NOT_FOUND)
        
        registered = []
        errors = []
        registration_time = timezone.now()
        
        with transaction.atomic():
            for course_unit_id in course_unit_ids:
                try:
                    course_unit = CourseUnit.objects.get(id=course_unit_id)
                    
                    # Check if student has been enrolled (by admin) in this course
                    enrollment = StudentCourseUnitEnrollment.objects.filter(
                        student=student, 
                        course_unit=course_unit
                    ).first()
                    
                    if not enrollment:
                        errors.append(f"Student has not been enrolled in {course_unit.code}. Please enroll first.")
                        continue
                    
                    # Check if already registered
                    if enrollment.registration_date:
                        errors.append(f"Student already registered for {course_unit.code}")
                        continue
                    
                    # Mark as registered
                    enrollment.registration_date = registration_time
                    enrollment.save()
                    
                    registered.append({
                        'id': enrollment.id,
                        'course_code': course_unit.code,
                        'course_name': course_unit.name,
                    })
                except CourseUnit.DoesNotExist:
                    errors.append(f"Course unit {course_unit_id} not found")
                except Exception as e:
                    errors.append(f"Error registering student for course {course_unit_id}: {str(e)}")
        
        # Update student registration status
        if registered:
            student.is_registered = True
            if not student.registration_date:
                student.registration_date = registration_time
            student.save()
        
        return Response({
            'message': f'Successfully registered student for {len(registered)} course(s)',
            'registered': registered,
            'errors': errors,
        }, status=status.HTTP_201_CREATED)

class AdminDeregisterStudentFromCourses(APIView):
    """Admin endpoint to deregister a student from courses"""
    permission_classes = [IsAdminUser]
    
    def post(self, request, student_id):
        from .models import CourseUnit, StudentCourseUnitEnrollment
        from admissions.models import AdmittedStudent
        
        course_unit_ids = request.data.get('course_unit_ids', [])
        if not course_unit_ids:
            return Response({'detail': 'No course unit IDs provided'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            student = AdmittedStudent.objects.get(id=student_id, is_admitted=True)
        except AdmittedStudent.DoesNotExist:
            return Response({'detail': 'Student not found'}, status=status.HTTP_404_NOT_FOUND)
        
        deregistered = []
        errors = []
        
        with transaction.atomic():
            for course_unit_id in course_unit_ids:
                try:
                    course_unit = CourseUnit.objects.get(id=course_unit_id)
                    
                    # Get enrollment
                    enrollment = StudentCourseUnitEnrollment.objects.filter(
                        student=student, 
                        course_unit=course_unit
                    ).first()
                    
                    if not enrollment:
                        errors.append(f"Student is not enrolled in {course_unit.code}")
                        continue
                    
                    # Check if registered
                    if not enrollment.registration_date:
                        errors.append(f"Student is not registered for {course_unit.code}")
                        continue
                    
                    # Deregister by clearing registration_date
                    enrollment.registration_date = None
                    enrollment.save()
                    
                    deregistered.append({
                        'id': enrollment.id,
                        'course_code': course_unit.code,
                        'course_name': course_unit.name,
                    })
                except CourseUnit.DoesNotExist:
                    errors.append(f"Course unit {course_unit_id} not found")
                except Exception as e:
                    errors.append(f"Error deregistering student from course {course_unit_id}: {str(e)}")
        
        # Update student registration status if no registered courses remain
        if deregistered:
            remaining_registered = StudentCourseUnitEnrollment.objects.filter(
                student=student,
                registration_date__isnull=False
            ).exists()
            
            if not remaining_registered:
                student.is_registered = False
                student.save()
        
        return Response({
            'message': f'Successfully deregistered student from {len(deregistered)} course(s)',
            'deregistered': deregistered,
            'errors': errors,
        }, status=status.HTTP_200_OK)

class RemoveStudentFromCourseUnit(APIView):
    """Remove a student from a course unit"""
    permission_classes = [IsAdminUser]
    
    def delete(self, request, enrollment_id):
        from .models import StudentCourseUnitEnrollment
        
        try:
            enrollment = StudentCourseUnitEnrollment.objects.get(id=enrollment_id)
            student_id = enrollment.student.student_id
            enrollment.delete()
            return Response({
                'message': f'Student {student_id} removed from course unit'
            }, status=status.HTTP_200_OK)
        except StudentCourseUnitEnrollment.DoesNotExist:
            return Response({'detail': 'Enrollment not found'}, status=status.HTTP_404_NOT_FOUND)

# ====================================Student Promotion==================================================================

class ListStudentsInSemester(APIView):
    """List all students in a specific semester (including those enrolled in course units)"""
    permission_classes = [IsAdminUser]
    
    def get(self, request, semester_id):
        from .models import Semester, StudentSemesterProgression, StudentCourseUnitEnrollment, CourseUnit
        from admissions.models import AdmittedStudent
        from django.utils import timezone
        
        try:
            semester = Semester.objects.select_related('program_batch', 'program_batch__program').get(id=semester_id)
        except Semester.DoesNotExist:
            return Response({'detail': 'Semester not found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Get all course units in this semester
        course_units = CourseUnit.objects.filter(semester=semester)
        
        # Get students enrolled in course units of this semester
        course_unit_enrollments = StudentCourseUnitEnrollment.objects.filter(
            course_unit__in=course_units
        ).select_related('student', 'student__application', 'student__application__applicant')
        
        # Get unique students from course unit enrollments
        students_from_course_units = {}
        for enrollment in course_unit_enrollments:
            student = enrollment.student
            if student.id not in students_from_course_units:
                students_from_course_units[student.id] = student
        
        # Get existing progressions
        progressions = StudentSemesterProgression.objects.filter(
            semester=semester
        ).select_related('student', 'student__application', 'student__application__applicant')
        
        # Create a map of student_id -> progression
        progression_map = {p.student.id: p for p in progressions}
        
        # Build response data
        data = []
        processed_student_ids = set()
        
        # First, add students with progressions
        for progression in progressions:
            student = progression.student
            processed_student_ids.add(student.id)
            data.append({
                'id': progression.id,
                'student_id': student.student_id,
                'student_db_id': student.id,  # Include student database ID
                'reg_no': student.reg_no,
                'name': student.full_name,
                'status': progression.status,
                'enrollment_date': progression.enrollment_date,
                'completion_date': progression.completion_date,
                'notes': progression.notes,
            })
        
        # Then, add students enrolled in course units but without progression records
        for student_id, student in students_from_course_units.items():
            if student_id not in processed_student_ids:
                # Create a virtual progression entry (will be created when promoted/detained)
                data.append({
                    'id': None,  # No progression ID yet
                    'student_id': student.student_id,
                    'student_db_id': student.id,  # Include student database ID for promotion/detention
                    'reg_no': student.reg_no,
                    'name': student.full_name,
                    'status': 'active',  # Default status
                    'enrollment_date': timezone.now().isoformat(),
                    'completion_date': None,
                    'notes': '',
                })
        
        return Response(data, status=status.HTTP_200_OK)

class PromoteStudentsToNextSemester(APIView):
    """Promote selected students to the next semester"""
    permission_classes = [IsAdminUser]
    
    def post(self, request, semester_id):
        from .models import Semester, StudentSemesterProgression
        from .promotion_utils import get_next_semester_in_batch, normalize_id_list
        from admissions.models import AdmittedStudent
        from django.utils import timezone
        
        progression_ids = normalize_id_list(request.data.get("progression_ids"))
        student_ids = normalize_id_list(request.data.get("student_ids"))
        
        if not progression_ids and not student_ids:
            return Response({'detail': 'No students selected'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            current_semester = Semester.objects.select_related('program_batch').get(id=semester_id)
        except Semester.DoesNotExist:
            return Response({'detail': 'Semester not found'}, status=status.HTTP_404_NOT_FOUND)
        
        next_semester, seq_error = get_next_semester_in_batch(current_semester)
        if not next_semester:
            from .models import Semester as SemModel

            batch = current_semester.program_batch
            overview = list(
                SemModel.objects.filter(program_batch=batch, is_active=True)
                .order_by("order", "start_date", "id")
                .values("id", "name", "order")
            )
            return Response(
                {
                    "detail": seq_error or "No next semester in this batch.",
                    "semesters_in_batch": overview,
                    "current_semester_id": current_semester.id,
                    "current_order": current_semester.order,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        
        promoted = []
        errors = []
        
        # Whether next_semester carries curriculum-position fields.
        # If both are set we will advance the student's SPE; otherwise we
        # leave SPE position unchanged (backward-compat for old semester records).
        next_year = next_semester.year_of_study
        next_term = next_semester.term_number
        can_advance_spe = next_year is not None and next_term is not None

        def _advance_spe(student_obj):
            """Update StudentProgrammeEnrollment position if the next semester
            carries year_of_study / term_number."""
            if not can_advance_spe:
                return
            try:
                spe = StudentProgrammeEnrollment.objects.get(student=student_obj)
                spe.current_year_of_study = next_year
                spe.current_term_number = next_term
                spe.save(update_fields=['current_year_of_study', 'current_term_number', 'updated_at'])
            except StudentProgrammeEnrollment.DoesNotExist:
                pass  # no SPE to update

        with transaction.atomic():
            # Process by progression_id first
            for progression_id in progression_ids:
                if progression_id is None:
                    continue
                try:
                    progression = StudentSemesterProgression.objects.select_related('student').get(
                        id=progression_id,
                        semester=current_semester
                    )
                    student = progression.student

                    # Update current semester progression to 'promoted'
                    progression.status = 'promoted'
                    progression.promotion_date = timezone.now()
                    progression.save()

                    # Check if student already has progression in next semester
                    existing = StudentSemesterProgression.objects.filter(
                        student=student,
                        semester=next_semester
                    ).first()

                    if existing:
                        existing.status = 'active'
                        existing.enrollment_date = timezone.now()
                        existing.save()
                        promoted.append({
                            'student_id': student.student_id,
                            'name': student.full_name,
                            'from_semester': current_semester.name,
                            'to_semester': next_semester.name,
                            'status': 'updated_existing'
                        })
                    else:
                        StudentSemesterProgression.objects.create(
                            student=student,
                            semester=next_semester,
                            program_batch=current_semester.program_batch,
                            status='active',
                            enrollment_date=timezone.now()
                        )
                        promoted.append({
                            'student_id': student.student_id,
                            'name': student.full_name,
                            'from_semester': current_semester.name,
                            'to_semester': next_semester.name,
                            'status': 'promoted'
                        })

                    # Advance SPE current position
                    _advance_spe(student)

                except StudentSemesterProgression.DoesNotExist:
                    errors.append(f"Progression with ID {progression_id} not found")
                except Exception as e:
                    errors.append(f"Error promoting student {progression_id}: {str(e)}")

            # Process by student_id (for students without progression records)
            for student_id in student_ids:
                try:
                    student = AdmittedStudent.objects.get(id=student_id)

                    # Get or create progression for current semester
                    progression, created = StudentSemesterProgression.objects.get_or_create(
                        student=student,
                        semester=current_semester,
                        defaults={
                            'program_batch': current_semester.program_batch,
                            'status': 'promoted',
                            'promotion_date': timezone.now(),
                            'enrollment_date': timezone.now()
                        }
                    )

                    if not created:
                        progression.status = 'promoted'
                        progression.promotion_date = timezone.now()
                        progression.save()

                    # Check if student already has progression in next semester
                    existing = StudentSemesterProgression.objects.filter(
                        student=student,
                        semester=next_semester
                    ).first()

                    if existing:
                        existing.status = 'active'
                        existing.enrollment_date = timezone.now()
                        existing.save()
                        promoted.append({
                            'student_id': student.student_id,
                            'name': student.full_name,
                            'from_semester': current_semester.name,
                            'to_semester': next_semester.name,
                            'status': 'updated_existing'
                        })
                    else:
                        StudentSemesterProgression.objects.create(
                            student=student,
                            semester=next_semester,
                            program_batch=current_semester.program_batch,
                            status='active',
                            enrollment_date=timezone.now()
                        )
                        promoted.append({
                            'student_id': student.student_id,
                            'name': student.full_name,
                            'from_semester': current_semester.name,
                            'to_semester': next_semester.name,
                            'status': 'promoted'
                        })

                    # Advance SPE current position
                    _advance_spe(student)

                except AdmittedStudent.DoesNotExist:
                    errors.append(f"Student with ID {student_id} not found")
                except Exception as e:
                    errors.append(f"Error promoting student {student_id}: {str(e)}")
        
        return Response({
            'promoted': promoted,
            'errors': errors,
            'message': f'Successfully promoted {len(promoted)} student(s) to {next_semester.name}'
        }, status=status.HTTP_200_OK)

class DetainStudentsInSemester(APIView):
    """Detain selected students in the current semester (prevent promotion)"""
    permission_classes = [IsAdminUser]
    
    def post(self, request, semester_id):
        from .models import Semester, StudentSemesterProgression
        from django.utils import timezone
        
        # Accept both progression_ids and student_ids
        progression_ids = request.data.get('progression_ids', [])
        student_ids = request.data.get('student_ids', [])
        notes = request.data.get('notes', '')
        
        if not progression_ids and not student_ids:
            return Response({'detail': 'No students selected'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            semester = Semester.objects.select_related('program_batch').get(id=semester_id)
        except Semester.DoesNotExist:
            return Response({'detail': 'Semester not found'}, status=status.HTTP_404_NOT_FOUND)
        
        detained = []
        errors = []
        
        with transaction.atomic():
            # Process by progression_id first
            for progression_id in progression_ids:
                if progression_id is None:
                    continue
                try:
                    progression = StudentSemesterProgression.objects.select_related('student').get(
                        id=progression_id,
                        semester=semester
                    )
                    
                    progression.status = 'detained'
                    progression.detained_date = timezone.now()
                    if notes:
                        progression.notes = notes
                    progression.save()
                    
                    detained.append({
                        'student_id': progression.student.student_id,
                        'name': progression.student.full_name,
                        'semester': semester.name,
                    })
                except StudentSemesterProgression.DoesNotExist:
                    errors.append(f"Progression with ID {progression_id} not found")
                except Exception as e:
                    errors.append(f"Error detaining student {progression_id}: {str(e)}")
            
            # Process by student_id (for students without progression records)
            for student_id in student_ids:
                try:
                    from admissions.models import AdmittedStudent
                    student = AdmittedStudent.objects.get(id=student_id)
                    
                    # Get or create progression
                    progression, created = StudentSemesterProgression.objects.get_or_create(
                        student=student,
                        semester=semester,
                        defaults={
                            'program_batch': semester.program_batch,
                            'status': 'detained',
                            'detained_date': timezone.now(),
                            'enrollment_date': timezone.now(),
                            'notes': notes
                        }
                    )
                    
                    if not created:
                        progression.status = 'detained'
                        progression.detained_date = timezone.now()
                        if notes:
                            progression.notes = notes
                        progression.save()
                    
                    detained.append({
                        'student_id': student.student_id,
                        'name': student.full_name,
                        'semester': semester.name,
                    })
                except AdmittedStudent.DoesNotExist:
                    errors.append(f"Student with ID {student_id} not found")
                except Exception as e:
                    errors.append(f"Error detaining student {student_id}: {str(e)}")
        
        return Response({
            'detained': detained,
            'errors': errors,
            'message': f'Successfully detained {len(detained)} student(s) in {semester.name}'
        }, status=status.HTTP_200_OK)


# ====================================Student Academic Tracker==================================================================

class StudentAcademicTrackerView(APIView):
    """
    Lightweight academic status tracker for the student portal.

    Aggregates from StudentProgrammeEnrollment, StudentCurriculumOverride,
    StudentCourseUnitEnrollment, and StudentSemesterProgression.

    Does NOT compute GPA, grades, or exam results — those belong to a later phase.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .models import (
            StudentCourseUnitEnrollment,
            StudentCurriculumOverride,
            StudentProgrammeEnrollment,
            StudentSemesterProgression,
        )
        from admissions.models import AdmittedStudent
        from django.db.models import Q

        user = request.user

        # ── Locate admitted student ──────────────────────────────────────────
        try:
            admitted_student = AdmittedStudent.objects.select_related(
                'admitted_program', 'admitted_campus'
            ).filter(
                Q(application__applicant=user) | Q(student_user=user) | Q(reg_no=user.username)
            ).first()
            if not admitted_student:
                raise AdmittedStudent.DoesNotExist
        except AdmittedStudent.DoesNotExist:
            return Response(
                {'detail': 'No admitted student record found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # ── Academic enrollment record ───────────────────────────────────────
        try:
            spe = StudentProgrammeEnrollment.objects.select_related(
                'program', 'program_batch', 'curriculum_version'
            ).get(student=admitted_student)
        except StudentProgrammeEnrollment.DoesNotExist:
            return Response(
                {'detail': 'No academic enrollment record found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        program = spe.program
        cal = program.calendar_type   # 'semester' or 'trimester'
        term_label = 'Trimester' if cal == 'trimester' else 'Semester'

        # ── Deferred courses ─────────────────────────────────────────────────
        deferred_overrides = list(
            StudentCurriculumOverride.objects.filter(
                enrollment=spe,
                override_type='deferred',
            ).select_related('curriculum_line', 'curriculum_line__catalog_course')
        )
        deferred_cl_ids = set()
        deferred_list = []
        for ov in deferred_overrides:
            cl = ov.curriculum_line
            if not cl:
                continue
            deferred_cl_ids.add(cl.id)
            cat = cl.catalog_course
            deferred_list.append({
                'course_code': cat.code if cat else '—',
                'course_name': cat.title if cat else '—',
                'original_year': cl.year_of_study,
                'original_term': cl.term_number,
                'deferred_to_year': ov.effective_year_of_study,
                'deferred_to_term': ov.effective_term_number,
            })

        # ── Registration status ──────────────────────────────────────────────
        # Count active (non-deferred) course unit enrollments and how many
        # of those have been registered (registration_date IS NOT NULL).
        active_qs = StudentCourseUnitEnrollment.objects.filter(
            student=admitted_student
        )
        if deferred_cl_ids:
            active_qs = active_qs.exclude(
                course_unit__curriculum_line_id__in=deferred_cl_ids
            )
        active_count = active_qs.count()
        registered_count = active_qs.filter(registration_date__isnull=False).count()

        if not spe.is_enrolled:
            reg_status = 'not_eligible'
            reg_label = 'Not Eligible'
        elif active_count == 0:
            reg_status = 'no_courses'
            reg_label = 'No Courses Enrolled'
        elif registered_count == 0:
            reg_status = 'pending'
            reg_label = 'Pending Registration'
        elif registered_count < active_count:
            reg_status = 'partial'
            reg_label = f'Partially Registered ({registered_count}/{active_count})'
        else:
            reg_status = 'registered'
            reg_label = 'Fully Registered'

        has_spec = program.has_specialization
        spec_entry_year = program.specialization_entry_year
        spec_entry_term = program.specialization_entry_term

        # ── Last promotion record ────────────────────────────────────────────
        # StudentSemesterProgression.promotion_date is set by PromoteStudentsToNextSemester.
        # If the admin promoted via the tool before the SPE-sync fix was deployed,
        # the SPE position may still be stale. Detect this by finding the most
        # recent active progression whose semester carries a later year/term.
        last_progression = (
            StudentSemesterProgression.objects
            .filter(student=admitted_student, promotion_date__isnull=False)
            .select_related('semester')
            .order_by('-promotion_date')
            .first()
        )

        # Effective position: prefer SPE, but upgrade from active progression
        # if the progression's semester is ahead of what the SPE records.
        effective_year = spe.current_year_of_study
        effective_term = spe.current_term_number

        latest_active = (
            StudentSemesterProgression.objects
            .filter(
                student=admitted_student,
                status='active',
                semester__year_of_study__isnull=False,
                semester__term_number__isnull=False,
            )
            .select_related('semester')
            .order_by('-semester__year_of_study', '-semester__term_number', '-enrollment_date')
            .first()
        )
        if latest_active:
            prog_year = latest_active.semester.year_of_study
            prog_term = latest_active.semester.term_number
            if (prog_year, prog_term) > (effective_year, effective_term):
                effective_year = prog_year
                effective_term = prog_term
                # Silently sync the SPE so all other pages pick up the correct
                # position without requiring a separate admin action.
                try:
                    spe.current_year_of_study = effective_year
                    spe.current_term_number = effective_term
                    spe.save(update_fields=['current_year_of_study', 'current_term_number', 'updated_at'])
                except Exception:
                    pass  # non-fatal; position is reported correctly either way

        # ── Specialization (same gate as expected courses / registration) ──
        from .models import resolve_program_default_curriculum_version
        from .specialization_rules import compute_specialization_course_gate, normalize_specialization

        curriculum_version = spe.curriculum_version
        if curriculum_version is None:
            curriculum_version = (
                spe.program_batch.curriculum_version
                if spe.program_batch_id and spe.program_batch.curriculum_version_id
                else resolve_program_default_curriculum_version(program)
            )

        spec_gate = compute_specialization_course_gate(
            program,
            curriculum_version,
            effective_year,
            effective_term,
            spe.specialization,
        )
        selected_spec = normalize_specialization(spe.specialization) or None
        spec_required_now = spec_gate['requires_specialization']

        return Response({
            'academic_position': {
                'year_of_study': effective_year,
                'term_number': effective_term,
                'term_label': term_label,
                'program': program.name,
                'program_short': program.short_form,
                'batch': spe.program_batch.name,
                'calendar_type': cal,
                'max_years': program.max_years,
                'entry_year': spe.entry_year_of_study,
                'entry_term': spe.entry_term_number,
            },
            'enrollment': {
                'status': spe.status,
                'status_display': spe.get_status_display(),
                'is_enrolled': spe.is_enrolled,
                'enrolled_at': spe.enrolled_at.isoformat() if spe.enrolled_at else None,
            },
            'registration': {
                'status': reg_status,
                'label': reg_label,
                'active_count': active_count,
                'registered_count': registered_count,
            },
            'deferred': {
                'count': len(deferred_list),
                'courses': deferred_list,
            },
            'specialization': {
                'program_has_specialization': has_spec,
                'entry_year': spec_entry_year,
                'entry_term': spec_entry_term,
                'selected': selected_spec,
                'required_now': spec_required_now,
                'is_missing': spec_required_now,
                'before_specialization_entry': spec_gate['before_entry'],
                'available_specializations': spec_gate['available_specializations'],
            },
            'promotion': {
                'has_record': last_progression is not None,
                'last_promoted_at': (
                    last_progression.promotion_date.isoformat()
                    if last_progression and last_progression.promotion_date
                    else None
                ),
                'promoted_to_semester': (
                    # Use the current *active* progression's semester (destination),
                    # not last_progression's semester (which is the source/from semester
                    # — PromoteStudentsToNextSemester sets promotion_date on the FROM row).
                    (latest_active.semester.name if latest_active else None)
                    if last_progression
                    else None
                ),
            },
        }, status=status.HTTP_200_OK)
