from rest_framework import generics
from rest_framework.permissions import *
from .models import *
from rest_framework.response import Response
from rest_framework.views import APIView
from .serializers import *
from easyaudit.models import CRUDEvent
from rest_framework import generics, filters
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q

class StandardPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200

class ListAuditLogs(generics.ListAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = AuditLogSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]

    search_fields = ['user__username', 'user__email', 'action']
    ordering_fields = ['timestamp', 'user__username', 'action']
    ordering = ['-timestamp']

    def get_queryset(self):
        queryset = AuditLog.objects.select_related('user')

        # Date Range Filter
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')

        if start_date:
            queryset = queryset.filter(timestamp__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(timestamp__date__lte=end_date)

        return queryset

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
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]

    search_fields = ['user__username', 'user__email', 'object_repr', 'changed_fields', 'event_type']
    ordering_fields = ['datetime', 'user__username', 'event_type']
    ordering = ['-datetime']

    def get_queryset(self):
        queryset = CRUDEvent.objects.select_related('user', 'content_type')

        # Date Range Filter
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')

        if start_date:
            queryset = queryset.filter(datetime__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(datetime__date__lte=end_date)

        return queryset
    
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