"""DELETE semester within a batch (used by Batch Management UI)."""
from rest_framework import status
from .permissions import ProgramSchedulingAPIPermission
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ProgramBatch, Semester


class DeleteSemesterForBatchView(APIView):
    permission_classes = [ProgramSchedulingAPIPermission]

    def delete(self, request, batch_id, semester_id):
        try:
            batch = ProgramBatch.objects.get(pk=batch_id)
        except ProgramBatch.DoesNotExist:
            return Response({"detail": "Batch not found"}, status=status.HTTP_404_NOT_FOUND)
        try:
            semester = Semester.objects.get(pk=semester_id, program_batch=batch)
        except Semester.DoesNotExist:
            return Response(
                {"detail": "Semester not found for this batch"},
                status=status.HTTP_404_NOT_FOUND,
            )
        semester.delete()
        return Response({"detail": "Semester deleted successfully"}, status=status.HTTP_200_OK)
