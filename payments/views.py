from django.shortcuts import render, redirect, get_object_or_404
from rest_framework.permissions import *
from rest_framework import generics
from rest_framework.response import Response
from .serializers import *
from django.utils import timezone
import requests
import json

from payments.models import ApplicationFee
from audit.utils import log_audit_event

# ====================================fees====================================================

# create fee plan
class CreateFeePlan(generics.CreateAPIView):
    queryset = ApplicationFee.objects.all()
    serializer_class = ApplicationFeeSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

# list fee plan
class ListFeePlan(generics.ListAPIView):
    queryset = ApplicationFee.objects.select_related(
        'admission_period', 'admission_period__created_by'
        ).prefetch_related('academic_level', 'admission_period__programs', 'admission_period__programs__campuses')
    serializer_class = ApplicationFeeSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

# edit fee plan
class UpdateFeePlan(generics.UpdateAPIView):
    queryset = ApplicationFee.objects.all()
    serializer_class = ApplicationFeeSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def put(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.serializer_class(instance, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(serializer.data, status=200)
    
# delete fee plan
class DeleteFeePlan(generics.UpdateAPIView):
    queryset = ApplicationFee.objects.all()
    serializer_class = ApplicationFeeSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()

        return Response({"detail":"fee plan deleted successfully"}, status=200)

















