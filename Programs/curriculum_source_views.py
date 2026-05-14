from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from rest_framework import status
from .permissions import CurriculumAPIPermission
from rest_framework.response import Response
from rest_framework.views import APIView

from .curriculum_inheritance import (
    curriculum_context_payload,
    fork_curriculum_version,
    link_program_to_curriculum_source,
    relink_forked_program_to_source,
    unlink_program_curriculum_source,
    validate_curriculum_source_assignment,
)
from .models import Program, ProgramCurriculumVersion
from .serializers import ProgramCurriculumVersionSerializer


class ProgramCurriculumSourceView(APIView):
    """Read or update curriculum inheritance settings for a programme row."""

    permission_classes = [CurriculumAPIPermission]

    def get(self, request, program_id):
        program = get_object_or_404(Program, pk=program_id)
        payload = curriculum_context_payload(program)
        origin_version = (
            ProgramCurriculumVersion.objects.filter(program=program, is_local_fork=True)
            .select_related('origin_version')
            .order_by('-created_at')
            .first()
        )
        payload['origin_version_id'] = origin_version.origin_version_id if origin_version else None
        payload['origin_version_name'] = (
            origin_version.origin_version.name
            if origin_version and origin_version.origin_version_id
            else None
        )
        return Response(payload)

    def patch(self, request, program_id):
        program = get_object_or_404(Program, pk=program_id)
        action = (request.data.get('action') or '').strip().lower()

        try:
            if action == 'link':
                source_id = request.data.get('curriculum_source_program_id')
                if not source_id:
                    return Response(
                        {'detail': 'curriculum_source_program_id is required.'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                source = get_object_or_404(Program, pk=int(source_id))
                local_count = program.curriculum_versions.count()
                link_program_to_curriculum_source(program, source)
                return Response({
                    **curriculum_context_payload(program),
                    'warning': (
                        f'This programme had {local_count} local curriculum version(s). '
                        'They are hidden while inheritance is active.'
                    ) if local_count else None,
                })
            if action == 'unlink':
                unlink_program_curriculum_source(program)
                local_count = program.curriculum_versions.count()
                return Response({
                    **curriculum_context_payload(program),
                    'warning': (
                        'No local curriculum versions exist for this programme.'
                    ) if local_count == 0 else None,
                })
            if action == 'relink':
                source_id = request.data.get('curriculum_source_program_id')
                if not source_id:
                    return Response(
                        {'detail': 'curriculum_source_program_id is required.'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                source = get_object_or_404(Program, pk=int(source_id))
                local_count = program.curriculum_versions.count()
                relink_forked_program_to_source(program, source)
                return Response({
                    **curriculum_context_payload(program),
                    'warning': (
                        f'{local_count} local fork version(s) are hidden while inheritance is active.'
                    ) if local_count else None,
                })
        except DjangoValidationError as exc:
            detail = getattr(exc, 'message_dict', None) or getattr(exc, 'messages', None) or str(exc)
            return Response({'detail': detail}, status=status.HTTP_400_BAD_REQUEST)

        return Response({'detail': 'action must be link, unlink, or relink.'}, status=status.HTTP_400_BAD_REQUEST)


class ProgramCurriculumForkView(APIView):
    permission_classes = [CurriculumAPIPermission]

    def post(self, request, program_id):
        program = get_object_or_404(Program, pk=program_id)
        version_id = request.data.get('version_id')
        if not version_id:
            return Response({'detail': 'version_id is required.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            new_version = fork_curriculum_version(program, int(version_id))
        except DjangoValidationError as exc:
            detail = getattr(exc, 'message_dict', None) or getattr(exc, 'messages', None) or str(exc)
            return Response({'detail': detail}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                **curriculum_context_payload(program),
                'version': ProgramCurriculumVersionSerializer(new_version).data,
            },
            status=status.HTTP_201_CREATED,
        )
