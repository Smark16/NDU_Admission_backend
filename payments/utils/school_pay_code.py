import logging
import re

import requests
from django.conf import settings

from admissions.models import AdmittedStudent
from .schoolpay_auth import build_schoolpay_hash, schoolpay_api_root

logger = logging.getLogger(__name__)


def _schoolpay_gender(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"m", "male"}:
        return "M"
    if normalized in {"f", "female"}:
        return "F"
    return ""

# def _schoolpay_phone(value: str) -> str:
#     """Normalize applicant phone for SchoolPay guardianPhone (local 0XXXXXXXXX)."""
#     phone = re.sub(r"\s+", "", str(value or "").strip())
#     if not phone:
#         return ""

#     # Common data-entry typo: letter O instead of zero at the start.
#     if phone[0] in "Oo" and len(phone) > 1 and phone[1:].isdigit():
#         phone = "0" + phone[1:]

#     if phone.startswith("+256"):
#         phone = "0" + phone[4:]
#     elif phone.startswith("256") and len(phone) > 3:
#         phone = "0" + phone[3:]

#     digits = re.sub(r"\D", "", phone)
#     if digits.startswith("256") and len(digits) >= 12:
#         digits = "0" + digits[3:]
#     if len(digits) == 9 and digits.startswith("7"):
#         return "0" + digits
#     if digits.startswith("0") and len(digits) == 10:
#         return digits
#     return phone

def _schoolpay_phone(value: str) -> str:
    if not value:
        return ""

    phone = str(value).strip()

    # Remove all whitespace
    phone = re.sub(r"\s+", "", phone)

    # Fix common typo: Letter 'O' instead of zero
    phone = re.sub(r'^[Oo]', '0', phone)

    # Extract digits only
    digits = re.sub(r"\D", "", phone)

    # ==================== INTERNATIONAL HANDLING ====================

    # Already in international format (e.g. +25798221328)
    if phone.startswith('+'):
        return phone  # Return as-is for international numbers

    # Starts with country code without + (e.g. 25798221328)
    if digits.startswith(('256', '257', '254', '255', '250', '243')) and len(digits) >= 12:
        return "+" + digits

    # ==================== UGANDA NUMBERS ====================

    # Ugandan numbers starting with 256
    if digits.startswith("256") and len(digits) >= 12:
        digits = "0" + digits[3:]   # convert to local format: 07xxxxxxxx

    # Starts with 7 → add leading 0 (common local format)
    elif len(digits) == 9 and digits.startswith("7"):
        digits = "0" + digits

    # Already in local 10-digit format
    elif len(digits) == 10 and digits.startswith("0"):
        pass  # already good

    # Too short or invalid → return original (SchoolPay might reject it anyway)
    elif len(digits) < 9:
        return phone  # return original so we can log the bad input

    return digits

def _extract_gateway_paycode(data: dict) -> str:
    for key in ("paymentCode", "studentCode", "studentPaymentCode"):
        value = str(data.get(key) or "").strip()
        if value:
            return value
    return ""

def _normalize_person_name(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _schoolpay_student_matches(application, gateway_name: str) -> bool:
    gateway = _normalize_person_name(gateway_name)
    if not gateway:
        return False

    full_name = _normalize_person_name(
        f"{application.first_name or ''} {application.middle_name or ''} {application.last_name or ''}"
    )
    short_name = _normalize_person_name(
        f"{application.first_name or ''} {application.last_name or ''}"
    )
    return gateway in {full_name, short_name}


def register_student_with_schoolpay(admitted_student):
    school_code = settings.SCHOOL_PAY_CODE
    password = settings.SCHOOL_PAY_PASSWORD
    registration_number = str(admitted_student.reg_no).strip()
    if not registration_number:
        return {
            "success": False,
            "error": "Admitted student is missing a registration number.",
        }

    request_hash = build_schoolpay_hash(school_code, registration_number, password)
    url = f"{schoolpay_api_root()}/SyncSchoolStudent/{school_code}/{request_hash}"

    app = admitted_student.application
    payload = {
        "firstName": app.first_name,
        "middleName": app.middle_name or "",
        "lastName": app.last_name,
        "registrationNumber": registration_number,
        "classCode": admitted_student.admitted_batch.name if admitted_student.admitted_batch else "Y1",
        "guardianPhone": _schoolpay_phone(app.phone),
        "gender": _schoolpay_gender(app.gender),
        "dateOfBirth": str(app.date_of_birth) if app.date_of_birth else "",
    }

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=30,
            headers={"Content-Type": "application/json"},
        )
        logger.info(
            "SchoolPay student sync for reg_no=%s status=%s",
            registration_number,
            response.status_code,
        )

        try:
            data = response.json()
        except ValueError:
            logger.warning(
                "SchoolPay student sync returned non-JSON for reg_no=%s: %s",
                registration_number,
                response.text[:800],
            )
            return {
                "success": False,
                "error": "Invalid JSON response from SchoolPay",
                "raw": response.text,
            }

        if data.get("returnCode") != 0:
            message = data.get("returnMessage") or "SchoolPay registration failed"
            logger.warning(
                "SchoolPay registration failed for student %s: %s (guardianPhone=%s)",
                admitted_student.pk,
                message,
                payload.get("guardianPhone"),
            )
            if data.get("returnCode") == 899:
                message = (
                    f"{message}. SchoolPay rejected the registration number format "
                    f"({registration_number}). Ask SchoolPay to allow this format for your school, "
                    "or align the generated reg. no. with their configured pattern."
                )
            return {
                "success": False,
                "error": message,
                "data": data,
            }

        paycode = _extract_gateway_paycode(data)
        if not paycode:
            return {
                "success": False,
                "error": "SchoolPay registration succeeded but no payment code was returned.",
                "data": data,
            }

        gateway_name = str(data.get("studentName") or "").strip()
        if not _schoolpay_student_matches(app, gateway_name):
            return {
                "success": False,
                "error": (
                    "SchoolPay returned a payment code for a different student name. "
                    "This registration number may already exist on the SchoolPay school account."
                ),
                "data": data,
                "expected_name": app.full_name,
                "gateway_name": gateway_name,
                "payment_code": paycode,
            }

        if (
            AdmittedStudent.objects.filter(schoolpay_code=paycode)
            .exclude(pk=admitted_student.pk)
            .exists()
        ):
            return {
                "success": False,
                "error": (
                    f"SchoolPay payment code {paycode} is already linked to another admitted student "
                    "in this portal."
                ),
                "data": data,
            }

        admitted_student.student_id = paycode
        admitted_student.is_registered_with_schoolpay = True
        admitted_student.save(
            update_fields=["student_id", "is_registered_with_schoolpay", "updated_at"]
        )

        return {
            "success": True,
            "data": data,
            "schoolpay_code": paycode,
            "gateway_name": gateway_name,
        }

    except requests.RequestException as exc:
        logger.exception("SchoolPay student sync failed for reg_no=%s", registration_number)
        return {
            "success": False,
            "error": str(exc),
        }