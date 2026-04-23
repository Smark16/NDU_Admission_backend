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
        user = request.user

        # Get or create draft
        draft = DraftApplication.objects.filter(
            applicant=user,
            batch_id=data.get('batch')
        ).order_by('-updated_at').first()

        if not draft:
            draft = DraftApplication.objects.create(
                applicant=user,
                batch_id=data.get('batch')
            )

        # ====================== BASIC FIELDS ======================
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
        
        draft.nextOfKinName = data.get('nextOfKinName', '')
        draft.next_of_kin_contact = data.get('nextOfKinContact', '')
        draft.next_of_kin_relationship = data.get('nextOfKinRelationship', '')

        draft.campus_id = data.get('campus') or None
        draft.academic_level_id = data.get('academic_level') or None

        # ====================== JSON FIELDS (Most Important) ======================
        draft.has_olevel = data.get('hasOlevel', False)

        draft.olevel_data = {
            "year": data.get('oLevelYear'),
            "index": data.get('oLevelIndexNumber'),
            "school": data.get('oLevelSchool'),
            "subjects": data.get('oLevelSubjects', [])
        }
        
        draft.has_alevel = data.get('hasAlevel', False)

        draft.alevel_data = {
            "year": data.get('aLevelYear'),
            "index": data.get('aLevelIndexNumber'),
            "school": data.get('aLevelSchool'),
            "combination": data.get('alevel_combination'),
            "subjects": data.get('aLevelSubjects', [])
        }
        
        draft.additional_qualifications = data.get('additionalQualifications', [])

        # ====================== BOOLEAN & OTHER ======================
        draft.application_fee_paid = data.get('application_fee_paid', False)
        draft.application_reference = data.get('externalReference', '')
        draft.status = data.get('status', 'draft')

        # Programs (ManyToMany)
        programs = data.get('programs')
        if programs is not None:
            draft.programs.set(programs)

        # Date of birth
        dob_str = data.get('dateOfBirth')
        if dob_str:
            try:
                draft.date_of_birth = datetime.strptime(dob_str, "%Y-%m-%d").date()
            except ValueError:
                draft.date_of_birth = None

        draft.save()

        return Response({
            "message": "Draft saved successfully",
            "draft_id": draft.id,
            "updated_at": draft.updated_at
        }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Draft save failed: {str(e)}", exc_info=True)
        return Response({"detail": "Failed to save draft"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# GET DRAFT DATA
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_draft_application(request):
    try:
        draft = DraftApplication.objects.filter(
            applicant=request.user,
            batch__isnull=False
        ).order_by('-updated_at').first()

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
        date_of_birth_str = draft.date_of_birth.strftime("%Y-%m-%d") if draft.date_of_birth else ""

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
            "phone": draft.phone or "",
            "email": draft.email or "",
            "address": draft.address or "",
            "disabled": draft.disabled or "",

            # === NEXT OF KIN - FIXED ===
            "nextOfKinName": getattr(draft, 'nextOfKinName', '') or "",
            "nextOfKinContact": getattr(draft, 'next_of_kin_contact', '') or "",
            "nextOfKinRelationship": getattr(draft, 'next_of_kin_relationship', '') or "",

            "campus": str(draft.campus_id) if draft.campus_id else "",
            "academic_level": str(draft.academic_level_id) if draft.academic_level_id else "",
            
            "programs": list(draft.programs.values_list('id', flat=True)) if draft.programs.exists() else [],

            # O-Level
            "hasOlevel": draft.has_olevel or False,
            "oLevelYear": draft.olevel_data.get("year", "") if isinstance(draft.olevel_data, dict) else "",
            "oLevelIndexNumber": draft.olevel_data.get("index", "") if isinstance(draft.olevel_data, dict) else "",
            "oLevelSchool": draft.olevel_data.get("school", "") if isinstance(draft.olevel_data, dict) else "",
            "oLevelSubjects": draft.olevel_data.get("subjects", []) if isinstance(draft.olevel_data, dict) else [],

            # A-Level
            "hasAlevel": draft.has_alevel or False,
            "aLevelYear": draft.alevel_data.get("year", "") if isinstance(draft.alevel_data, dict) else "",
            "aLevelIndexNumber": draft.alevel_data.get("index", "") if isinstance(draft.alevel_data, dict) else "",
            "aLevelSchool": draft.alevel_data.get("school", "") if isinstance(draft.alevel_data, dict) else "",
            "alevel_combination": draft.alevel_data.get("combination", "") if isinstance(draft.alevel_data, dict) else "",
            "aLevelSubjects": draft.alevel_data.get("subjects", []) if isinstance(draft.alevel_data, dict) else [],

            # Additional Qualifications
            "additionalQualifications": draft.additional_qualifications if isinstance(draft.additional_qualifications, list) else [],

            "application_fee_paid": draft.application_fee_paid,
            "externalReference": draft.application_reference or "",
            "status": draft.status,
        }

        return Response({
            "draft_exists": True,
            "data": data,
            "last_updated": draft.updated_at.isoformat() if draft.updated_at else ""
        })

    except Exception as e:
        logger.error(f"Get draft failed: {e}", exc_info=True)
        return Response({
            "message": "Failed to load draft",
            "draft_exists": False
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
