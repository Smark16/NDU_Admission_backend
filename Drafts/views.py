from accounts.models import Campus
from .models import *
from rest_framework.views import APIView
from rest_framework import generics, status
from rest_framework.permissions import *
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.decorators import api_view, permission_classes
from django.db import transaction
from datetime import datetime

import logging
import json

logger = logging.getLogger(__name__)

# Create your views here.
# save draft application
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def save_draft_applications(request):
    try:
        data = request.data

        # Get latest draft or create new
        draft = DraftApplication.objects.filter(
            applicant=request.user,
            batch_id=data.get('batch')
        ).order_by('-updated_at').first()

        if not draft:
            draft = DraftApplication.objects.create(
                applicant=request.user,
                batch_id=data.get('batch')
            )

        # === MAP FRONTEND → BACKEND ===
        draft.first_name = data.get('firstName', '')
        draft.last_name = data.get('lastName', '')
        draft.middle_name = data.get('middleName', '')
        draft.gender = data.get('gender', '')
        draft.nationality = data.get('nationality', '')
        draft.nin = data.get('nin', '')
        draft.passport_number = data.get('passportNumber', '')
        draft.phone = data.get('phone', '')
        draft.email = data.get('email', '')
        draft.address = data.get('address', '')
        draft.disabled = data.get('disabled', '')

        # Safe date conversion for date_of_birth
        dob_str = data.get('dateOfBirth')
        if dob_str:
            try:
                draft.date_of_birth = datetime.strptime(dob_str, "%Y-%m-%d").date()
            except ValueError:
                draft.date_of_birth = None
        else:
            draft.date_of_birth = None

        draft.next_of_kin_name = data.get('nextOfKinName', '')
        draft.next_of_kin_contact = data.get('nextOfKinContact', '')
        draft.next_of_kin_relationship = data.get('nextOfKinRelationship', '')

        draft.campus_id = data.get('campus') or None
        draft.academic_level_id = data.get('academic_level') or None

        # Academic Results as JSON
        draft.olevel_data = {
            "year": data.get('oLevelYear'),
            "index": data.get('oLevelIndexNumber'),
            "school": data.get('oLevelSchool'),
            "subjects": data.get('oLevelSubjects', [])
        }

        draft.alevel_data = {
            "year": data.get('aLevelYear'),
            "index": data.get('aLevelIndexNumber'),
            "school": data.get('aLevelSchool'),
            "combination": data.get('alevel_combination'),
            "subjects": data.get('aLevelSubjects', [])
        }

        draft.additional_qualifications = data.get('additionalQualifications', [])

        # Save programs (ManyToMany)
        if data.get('programs'):
            draft.programs.set(data.get('programs'))

        draft.save()

        return Response({
            "message": "Draft saved successfully",
            "draft_id": draft.id,
            "draft_saved": True
        }, status=200)

    except Exception as e:
        logger.error(f"Draft save failed: {e}", exc_info=True)
        return Response({"detail": "Failed to save draft"}, status=500)

# GET DRAFT DATA
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_draft_application(request):
    try:
        # Get the most recent draft that has a batch (preferred)
        draft = DraftApplication.objects.filter(
            applicant=request.user,
            batch__isnull=False
        ).order_by('-updated_at').first()

        # Fallback: get any latest draft
        if not draft:
            draft = DraftApplication.objects.filter(
                applicant=request.user
            ).order_by('-updated_at').first()

        if not draft:
            return Response({
                "message": "No draft found",
                "draft_exists": False
            }, status=status.HTTP_200_OK)

        # Safe date formatting
        date_of_birth_str = ""
        if draft.date_of_birth:
            if isinstance(draft.date_of_birth, str):
                date_of_birth_str = draft.date_of_birth
            else:
                date_of_birth_str = draft.date_of_birth.strftime("%Y-%m-%d")

        # Safe last_updated formatting
        last_updated_str = ""
        if draft.updated_at:
            if isinstance(draft.updated_at, str):
                last_updated_str = draft.updated_at
            else:
                last_updated_str = draft.updated_at.isoformat()

        # Build the exact FormData structure
        data = {
            "applicant": draft.applicant_id,
            "batch": draft.batch_id,
            "firstName": draft.first_name or "",
            "lastName": draft.last_name or "",
            "middleName": draft.middle_name or "",
            "dateOfBirth": date_of_birth_str,
            "gender": draft.gender or "",
            "nationality": draft.nationality or "",
            "nin": draft.nin or "",
            "passportNumber": draft.passport_number or "",
            "phone": draft.phone or 0,
            "email": draft.email or "",
            "address": draft.address or "",
            "nextOfKinName": draft.next_of_kin_name or "",
            "nextOfKinContact": draft.next_of_kin_contact or "",
            "nextOfKinRelationship": draft.next_of_kin_relationship or "",
            "campus": str(draft.campus_id) if draft.campus_id else "",
            "programs": list(draft.programs.values_list('id', flat=True)) if hasattr(draft, 'programs') and draft.programs.exists() else [],
            "academic_level": str(draft.academic_level_id) if draft.academic_level_id else "",
            "disabled": draft.disabled or "",

            # O-Level
            "oLevelYear": draft.olevel_data.get("year", "") if isinstance(draft.olevel_data, dict) else "",
            "oLevelIndexNumber": draft.olevel_data.get("index", "") if isinstance(draft.olevel_data, dict) else "",
            "oLevelSchool": draft.olevel_data.get("school", "") if isinstance(draft.olevel_data, dict) else "",
            "oLevelSubjects": draft.olevel_data.get("subjects", []) if isinstance(draft.olevel_data, dict) else [
                {"id": "1", "subject": "", "grade": ""},
                {"id": "2", "subject": "", "grade": ""}
            ],

            # A-Level
            "aLevelYear": draft.alevel_data.get("year", "") if isinstance(draft.alevel_data, dict) else "",
            "aLevelIndexNumber": draft.alevel_data.get("index", "") if isinstance(draft.alevel_data, dict) else "",
            "aLevelSchool": draft.alevel_data.get("school", "") if isinstance(draft.alevel_data, dict) else "",
            "alevel_combination": draft.alevel_data.get("combination", "") if isinstance(draft.alevel_data, dict) else "",
            "aLevelSubjects": draft.alevel_data.get("subjects", []) if isinstance(draft.alevel_data, dict) else [{"id": "1", "subject": "", "grade": ""}],

            # Additional Qualifications
            "additionalQualifications": draft.additional_qualifications if isinstance(draft.additional_qualifications, list) else [],

            # Files
            "passportPhoto": None,
            "oLevelDocuments": None,
            "aLevelDocuments": None,
            "otherInstitutionDocuments": None,

            "application_fee_paid": False,
            "externalReference": "",
            "status": "draft",
        }

        return Response({
            "draft_exists": True,
            "data": data,
            "last_updated": last_updated_str
        }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Get draft failed: {e}", exc_info=True)
        return Response({
            "message": "Failed to load draft",
            "draft_exists": False
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)