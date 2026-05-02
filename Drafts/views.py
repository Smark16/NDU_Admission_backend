from accounts.models import Campus
from .models import *
from rest_framework.views import APIView
from rest_framework import generics, status
from rest_framework.permissions import *
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.decorators import api_view, permission_classes, parser_classes
from django.db import transaction
from django.db.utils import OperationalError
from datetime import datetime
import time
from django.conf import settings

import logging
import json

logger = logging.getLogger(__name__)

# Create your views here.
# save draft application
@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def save_draft_applications(request):
    # SQLite can throw "database is locked" if multiple autosaves overlap.
    # Use a small retry/backoff so the UX doesn't fail for transient locks.
    for attempt in range(4):
        try:
            data = request.data

            batch_raw = data.get("batch")
            batch_id = None
            try:
                if batch_raw not in (None, "", "undefined", "null"):
                    batch_id = int(batch_raw)
            except Exception:
                batch_id = None

            def _parse_json_field(val, default):
                if isinstance(val, (list, dict)):
                    return val
                if isinstance(val, str):
                    try:
                        return json.loads(val)
                    except Exception:
                        pass
                return default

            with transaction.atomic():
                # Get latest draft or create new (batch can be null)
                draft = (
                    DraftApplication.objects
                    .filter(applicant=request.user, batch_id=batch_id)
                    .order_by("-updated_at")
                    .first()
                )

                if not draft:
                    draft = DraftApplication.objects.create(
                        applicant=request.user,
                        batch_id=batch_id,
                    )

                # === MAP FRONTEND → BACKEND ===
                draft.first_name = data.get("firstName", "")
                draft.last_name = data.get("lastName", "")
                draft.middle_name = data.get("middleName", "")
                draft.gender = data.get("gender", "")
                draft.nationality = data.get("nationality", "")
                draft.nin = data.get("nin", "")
                draft.passport_number = data.get("passportNumber", "")
                draft.phone = data.get("phone", "")
                draft.email = data.get("email", "")
                draft.address = data.get("address", "")
                draft.disabled = data.get("disabled", "")

                # Safe date conversion for date_of_birth
                dob_str = data.get("dateOfBirth")
                if dob_str:
                    try:
                        draft.date_of_birth = datetime.strptime(dob_str, "%Y-%m-%d").date()
                    except ValueError:
                        draft.date_of_birth = None
                else:
                    draft.date_of_birth = None

                draft.next_of_kin_name = data.get("nextOfKinName", "")
                draft.next_of_kin_contact = data.get("nextOfKinContact", "")
                draft.next_of_kin_relationship = data.get("nextOfKinRelationship", "")

                draft.campus_id = data.get("campus") or None
                draft.academic_level_id = data.get("academic_level") or None

                draft.olevel_data = {
                    "year": data.get("oLevelYear"),
                    "index": data.get("oLevelIndexNumber"),
                    "school": data.get("oLevelSchool"),
                    "subjects": _parse_json_field(data.get("oLevelSubjects"), []),
                }

                draft.alevel_data = {
                    "year": data.get("aLevelYear"),
                    "index": data.get("aLevelIndexNumber"),
                    "school": data.get("aLevelSchool"),
                    "combination": data.get("alevel_combination"),
                    "subjects": _parse_json_field(data.get("aLevelSubjects"), []),
                }

                aq = data.get("additionalQualifications", [])
                if isinstance(aq, str):
                    try:
                        aq = json.loads(aq)
                    except Exception:
                        aq = []
                draft.additional_qualifications = aq

                # Save programs (ManyToMany) — may arrive as repeated fields or JSON string
                programs_raw = data.getlist("programs") if hasattr(data, "getlist") else data.get("programs", [])
                # Common cases:
                # - multipart: ["1","2"] or ["[1,2]"] or ["[]"]
                # - json: [1,2] or "[]"
                if isinstance(programs_raw, list) and len(programs_raw) == 1 and isinstance(programs_raw[0], str):
                    s = programs_raw[0].strip()
                    if s.startswith("[") and s.endswith("]"):
                        try:
                            programs_raw = json.loads(s)
                        except Exception:
                            programs_raw = []
                elif isinstance(programs_raw, str):
                    try:
                        programs_raw = json.loads(programs_raw)
                    except Exception:
                        programs_raw = []

                # Normalize to list[int]
                if not isinstance(programs_raw, list):
                    programs_raw = []
                programs_ids: list[int] = []
                for v in programs_raw:
                    try:
                        if v in (None, "", "null", "undefined"):
                            continue
                        programs_ids.append(int(v))
                    except Exception:
                        continue

                # Files — only overwrite if a new file was actually uploaded
                if "passportPhoto" in request.FILES:
                    draft.draft_passport_photo = request.FILES["passportPhoto"]
                if "oLevelDocuments" in request.FILES:
                    draft.draft_olevel_doc = request.FILES["oLevelDocuments"]
                if "aLevelDocuments" in request.FILES:
                    draft.draft_alevel_doc = request.FILES["aLevelDocuments"]
                if "otherInstitutionDocuments" in request.FILES:
                    draft.draft_other_doc = request.FILES["otherInstitutionDocuments"]

                draft.save()

                # M2M set after save
                # Always set (clears when empty) so draft reflects latest selection
                draft.programs.set(programs_ids)

            return Response(
                {"message": "Draft saved successfully", "draft_id": draft.id, "draft_saved": True},
                status=200,
            )

        except OperationalError as e:
            msg = str(e).lower()
            if "database is locked" in msg and attempt < 5:
                time.sleep(0.4 * (attempt + 1))
                continue
            logger.error(f"Draft save failed (db): {e}", exc_info=True)
            return Response({"detail": "Failed to save draft"}, status=500)
        except Exception as e:
            logger.error(f"Draft save failed: {e}", exc_info=True)
            if getattr(settings, "DEBUG", False):
                return Response({"detail": f"Failed to save draft: {str(e)}"}, status=500)
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

            # Files — return URLs for saved draft files so the frontend can display them
            "passportPhoto": None,
            "oLevelDocuments": None,
            "aLevelDocuments": None,
            "otherInstitutionDocuments": None,
            # Saved draft file URLs (separate keys so frontend can show "previously uploaded")
            "draft_passport_photo_url": request.build_absolute_uri(draft.draft_passport_photo.url) if draft.draft_passport_photo else None,
            "draft_olevel_doc_url":     request.build_absolute_uri(draft.draft_olevel_doc.url)     if draft.draft_olevel_doc     else None,
            "draft_alevel_doc_url":     request.build_absolute_uri(draft.draft_alevel_doc.url)     if draft.draft_alevel_doc     else None,
            "draft_other_doc_url":      request.build_absolute_uri(draft.draft_other_doc.url)      if draft.draft_other_doc      else None,

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