from rest_framework import generics
from rest_framework.permissions import *
from .models import *
from rest_framework.response import Response
from rest_framework.views import APIView
from .serializers import *
from easyaudit.models import CRUDEvent

class ListAuditLogs(generics.ListAPIView):
    queryset = AuditLog.objects.select_related('user')
    serializer_class = AuditLogSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

# delete logs
class DeleteAuditLogs(generics.RetrieveDestroyAPIView):
    queryset = AuditLog.objects.select_related('user')
    serializer_class = AuditLogSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()

        return Response({"detail":"Auth Logs deleted successfully"})
    
# delete all Auth logs
class DeleteAllAuthLogs(APIView):
    queryset = AuditLog.objects.select_related('user')
    serializer_class = AuditLogSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def delete(self, request, *args, **kwargs):
        authlogs = AuditLog.objects.select_related('user')
        authlogs.delete()

        return Response({"details":"All auth logs have been deleted"})

# =======================================easy audit logs================================
class ListLogsView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = LogSerializer

    def get_queryset(self):
        return CRUDEvent.objects.all()\
            .select_related('user', 'content_type')\
            .prefetch_related('content_type')\
            .order_by('-datetime')
    
# delete crud logs
class DeleteCrudlogs(generics.RetrieveDestroyAPIView):
    queryset = CRUDEvent.objects.all()
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = LogSerializer

    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()

        return Response({"detail":"Crud Logs deleted successfully"})
    
# delete all crud logs
class DeleteAllCrudLogs(APIView):
    queryset = CRUDEvent.objects.all()
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = LogSerializer

    def delete(self, request, *args, **kwargs):
        crudlogs = CRUDEvent.objects.all()\
            .select_related('user', 'content_type')\
            .prefetch_related('content_type')\
            .order_by('-datetime')
        crudlogs.delete()

        return Response({"details":"All crud logs have been deleted"})