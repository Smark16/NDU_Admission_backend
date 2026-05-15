"""
REST API endpoint to get program structure (batches, semesters, course units)
Returns hierarchical structure of program with all its batches, semesters, and course units
"""
from django.db.utils import ProgrammingError
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .permissions import ProgramSchedulingAPIPermission
from django.db.models import Prefetch
from .models import Program, ProgramBatch, Semester, CourseUnit


class ProgramStructureView(APIView):
    """Get program structure with batches, semesters, and course units"""
    permission_classes = [ProgramSchedulingAPIPermission]

    def get(self, request, program_id):
        try:
            # Get the Program with related data
            program = Program.objects.select_related(
                'faculty', 
                'academic_level'
            ).prefetch_related('campuses').get(id=program_id)
            
            # Fetch program batches with semesters and course units
            batches = ProgramBatch.objects.filter(
                program=program,
                is_active=True
            ).prefetch_related(
                Prefetch(
                    'semesters',
                    queryset=Semester.objects.filter(is_active=True).order_by('order', 'start_date').prefetch_related(
                        Prefetch(
                            'course_units',
                            queryset=CourseUnit.objects.filter(is_active=True).prefetch_related('lecturers').order_by('code', 'name')
                        )
                    )
                ),
                Prefetch(
                    'course_units',
                    queryset=CourseUnit.objects.filter(is_active=True, semester__isnull=True).prefetch_related('lecturers').order_by('code', 'name')
                )
            ).order_by('-start_date', 'name')
            
            # Build response structure
            batches_data = []
            total_semesters = 0
            total_course_units = 0
            
            for batch in batches:
                semesters_data = []
                batch_course_units = 0
                
                # Add semesters and their course units
                for semester in batch.semesters.all():
                    course_units_data = []
                    for course_unit in semester.course_units.all():
                        lecturers = [
                            {
                                'id': lecturer.id,
                                'name': lecturer.get_full_name(),
                                'email': lecturer.email
                            }
                            for lecturer in course_unit.lecturers.all()
                        ]
                        course_units_data.append({
                            'id': course_unit.id,
                            'name': course_unit.name,
                            'code': course_unit.code,
                            'is_active': course_unit.is_active,
                            'credit_units': float(course_unit.credit_units) if course_unit.credit_units else None,
                            'lecturers': lecturers,
                            'lecturers_names': [l['name'] for l in lecturers] if lecturers else [],
                        })
                        batch_course_units += 1
                        total_course_units += 1
                    
                    semesters_data.append({
                        'id': semester.id,
                        'name': semester.name,
                        'order': semester.order,
                        # Used by "Load from curriculum" to check semester position
                        'year_of_study': semester.year_of_study,
                        'term_number': semester.term_number,
                        'start_date': semester.start_date.isoformat() if semester.start_date else None,
                        'end_date': semester.end_date.isoformat() if semester.end_date else None,
                        'course_units': course_units_data,
                        'total_course_units': len(course_units_data)
                    })
                    total_semesters += 1
                
                # Add batch-level course units (not assigned to any semester)
                batch_level_units = []
                for course_unit in batch.course_units.all():
                    lecturers = [
                        {
                            'id': lecturer.id,
                            'name': lecturer.get_full_name(),
                            'email': lecturer.email
                        }
                        for lecturer in course_unit.lecturers.all()
                    ]
                    batch_level_units.append({
                        'id': course_unit.id,
                        'name': course_unit.name,
                        'code': course_unit.code,
                        'is_active': course_unit.is_active,
                        'credit_units': float(course_unit.credit_units) if course_unit.credit_units else None,
                        'lecturers': lecturers,
                        'lecturers_names': [l['name'] for l in lecturers] if lecturers else [],
                    })
                    batch_course_units += 1
                    total_course_units += 1
                
                batches_data.append({
                    'id': batch.id,
                    'name': batch.name,
                    'academic_year': batch.academic_year or '',
                    'start_date': batch.start_date.isoformat() if batch.start_date else None,
                    'end_date': batch.end_date.isoformat() if batch.end_date else None,
                    'offer_start_date': batch.offer_start_date.isoformat() if batch.offer_start_date else None,
                    'offer_end_date': batch.offer_end_date.isoformat() if batch.offer_end_date else None,
                    'is_offer_active': batch.is_offer_active,
                    'semesters': semesters_data,
                    'batch_level_course_units': batch_level_units,
                    'total_semesters': len(semesters_data),
                    'total_course_units': batch_course_units
                })
            
            return Response({
                'id': program.id,
                'name': program.name,
                'short_form': program.short_form,
                'code': program.code,
                'faculty': program.faculty.name if program.faculty else None,
                'academic_level': program.academic_level.name if program.academic_level else None,
                'batches': batches_data,
                'total_batches': len(batches_data),
                'total_semesters': total_semesters,
                'total_course_units': total_course_units,
                'available': True
            }, status=status.HTTP_200_OK)
            
        except Program.DoesNotExist:
            return Response(
                {'detail': 'Program not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except ProgrammingError:
            return Response({'batches': [], 'detail': 'Batch management not available on this server.'}, status=status.HTTP_200_OK)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error fetching program structure for program_id={program_id}: {str(e)}")
            
            return Response(
                {
                    'detail': f'Error fetching program structure: {str(e)}',
                    'error_type': type(e).__name__
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
