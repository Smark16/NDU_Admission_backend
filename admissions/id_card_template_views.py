"""CRUD + PDF field mapper for ID card templates (offer-letter style)."""

from __future__ import annotations

import base64
import logging
import os

import fitz
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateDestroyAPIView
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import IdCardPdfTemplate
from .permissions import ManageIdCardsPermission

logger = logging.getLogger(__name__)


class IdCardPdfTemplateSerializer(serializers.ModelSerializer):
    pdf_url = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = IdCardPdfTemplate
        fields = [
            "id",
            "key",
            "name",
            "template_pdf",
            "pdf_url",
            "field_positions",
            "front_title",
            "institution",
            "issuer_title",
            "issuer_signatory",
            "return_to",
            "tel",
            "email",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "field_positions", "created_at", "updated_at"]

    def get_pdf_url(self, obj: IdCardPdfTemplate):
        request = self.context.get("request")
        if not obj.template_pdf or not request:
            return None
        try:
            return request.build_absolute_uri(obj.template_pdf.url)
        except ValueError:
            return None


class IdCardPdfTemplateListCreateView(ListCreateAPIView):
    permission_classes = [IsAuthenticated, ManageIdCardsPermission]
    parser_classes = [MultiPartParser, FormParser]
    queryset = IdCardPdfTemplate.objects.all().order_by("name")
    serializer_class = IdCardPdfTemplateSerializer


class IdCardPdfTemplateDetailView(RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated, ManageIdCardsPermission]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    queryset = IdCardPdfTemplate.objects.all()
    serializer_class = IdCardPdfTemplateSerializer


class IdCardPdfTemplatePreviewView(APIView):
    permission_classes = [IsAuthenticated, ManageIdCardsPermission]

    def get(self, request, pk: int):
        template = get_object_or_404(IdCardPdfTemplate, pk=pk)
        ext = os.path.splitext(template.template_pdf.name or "")[1].lower()
        if ext != ".pdf":
            return Response({"detail": "Template file must be a PDF."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            doc = fitz.open(template.template_pdf.path)
            page = doc[0]
            pdf_width = page.rect.width
            pdf_height = page.rect.height
            mat = fitz.Matrix(2, 2)
            pix = page.get_pixmap(matrix=mat)
            img_b64 = base64.b64encode(pix.tobytes("png")).decode()
            doc.close()
        except Exception as e:
            logger.error("ID card PDF preview failed for template %s: %s", pk, e, exc_info=True)
            return Response(
                {"detail": "Failed to render PDF preview. Ensure the file is a valid PDF."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response(
            {
                "image": img_b64,
                "pdf_width": pdf_width,
                "pdf_height": pdf_height,
                "field_positions": template.field_positions or {},
            }
        )


class IdCardPdfTemplateSavePositionsView(APIView):
    permission_classes = [IsAuthenticated, ManageIdCardsPermission]

    def post(self, request, pk: int):
        template = get_object_or_404(IdCardPdfTemplate, pk=pk)
        ext = os.path.splitext(template.template_pdf.name or "")[1].lower()
        if ext != ".pdf":
            return Response({"detail": "Template file must be a PDF."}, status=status.HTTP_400_BAD_REQUEST)
        positions = request.data.get("field_positions", {})
        if not isinstance(positions, dict):
            return Response({"detail": "field_positions must be an object."}, status=status.HTTP_400_BAD_REQUEST)
        template.field_positions = positions
        template.save(update_fields=["field_positions", "updated_at"])
        return Response({"detail": "Field positions saved successfully."})
