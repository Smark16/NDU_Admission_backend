from rest_framework.permissions import *
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from .serializers import *
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
import json
import uuid

from .models import ApplicationFee, ApplicationPayment, StudentTuitionPayment
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.db import transaction
from .models import ApplicationPayment
from .utils.schoolpay import SchoolPayClient
from django.utils import timezone
from datetime import timedelta
from .serializers import ApplicationPaymentSerializer
from admissions.models import Application
from payments.utils.school_pay_code import register_student_with_schoolpay
from accounts.models import User
from rest_framework.decorators import api_view, permission_classes
from django.shortcuts import get_object_or_404

# caching
from django.core.cache import cache
# ====================================fees====================================================

# create fee plan
class CreateFeePlan(generics.CreateAPIView):
    queryset = ApplicationFee.objects.all()
    serializer_class = ApplicationFeeSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

# list fee plan
class ListFeePlan(generics.ListAPIView):
    queryset = ApplicationFee.objects.select_related(
        'admission_period'
    ).prefetch_related('academic_level')
    
    serializer_class = ListApplicationFeeSerializer
    # Applicants must read active fee rows to pay and submit; model permissions would block them.
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        cache_key = 'all_fee_plans_list'

        # Try cache first
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return Response(cached_data)

        # Get fresh data
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        data = serializer.data

        # Cache for 24 hours (86,400 seconds)
        cache.set(cache_key, data, timeout=60 * 60 * 24)

        return Response(data)

# edit fee plan
class UpdateFeePlan(generics.UpdateAPIView):
    queryset = ApplicationFee.objects.all()
    serializer_class = ApplicationFeeSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    
# delete fee plan
class DeleteFeePlan(generics.DestroyAPIView):
    queryset = ApplicationFee.objects.all()
    serializer_class = ApplicationFeeSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

# ========================================================schoolpay====================================================
# Initiate Payment
class InitiatePayment(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        phone = request.data.get('phone')
        first_name = request.data.get('first_name')
        last_name = request.data.get('last_name')
        amount = request.data.get('amount')
        reason = "Application Fee"

        if settings.DEBUG:
          callBackUrl = "https://4ddf-196-43-131-1.ngrok-free.app/api/payments/webhook/" 
        else:
          callBackUrl = f"{settings.BACKEND_URL}/api/payments/webhook/"

        # EXPIRE OLD PAYMENTS
        ApplicationPayment.objects.filter(
            user=request.user,
            status='PENDING',
            created_at__lt=timezone.now() - timedelta(minutes=10)
        ).update(status='FAILED')

        # PREVENT DUPLICATE PENDING PAYMENTS
        existing_payment = ApplicationPayment.objects.filter(
            user=request.user,
            status='PENDING'
        ).first()

        if existing_payment:
            return Response({
                'error': 'You already have a pending payment'
            }, status=400)

        ext_ref = f"APP-{uuid.uuid4().hex.upper()}"

        client = SchoolPayClient()

        response_data = client.request_payment(
            amount=amount,
            phone=phone,
            ext_ref=ext_ref,
            first_name=first_name,
            last_name=last_name,
            reason=reason,
            callBackUrl=callBackUrl
        )

        if response_data.get('returnCode') != 0:
            return Response(
                {'error': response_data.get('returnMessage')},
                status=status.HTTP_400_BAD_REQUEST
            )

        payment = ApplicationPayment.objects.create(
            user=request.user,
            external_reference=ext_ref,
            payment_reference=response_data.get('paymentReference'),
            amount=amount,
            phone_number=phone,
            fee_type=reason,
            status='PENDING'
        )

        return Response({
            'payment_reference': payment.payment_reference,
            'external_reference': ext_ref,
            'status': payment.status
        })

# Webhook
import logging
logger = logging.getLogger(__name__)

@csrf_exempt
@require_POST
def schoolpay_webhook(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        logger.error("SchoolPay webhook: Invalid JSON received")
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error("SchoolPay webhook: Error reading body - %s", str(e))
        return JsonResponse({'error': 'Bad request'}, status=400)

    # === LOG EVERYTHING SO YOU CAN SEE WHAT ARRIVES ===
    logger.info("SchoolPay webhook received: %s", json.dumps(data, indent=2))
    print("=== SCHOOLPAY WEBHOOK ===")
    print(json.dumps(data, indent=2))
    print("=========================")

    # For admission/application fees, SchoolPay usually sends a simple payload
    status = data.get('status')
    payment_ref = data.get('paymentReference')

    if not payment_ref:
        logger.warning("Webhook received without paymentReference")
        return JsonResponse({'status': 'ignored'}, status=200)

    if status != 'PAID':
        logger.info("Payment not yet PAID. Status: %s", status)
        return JsonResponse({'status': 'ignored'}, status=200)

    # ── Try ApplicationPayment first (application fees) ──────────────────────
    try:
        with transaction.atomic():
            app_payment = ApplicationPayment.objects.select_for_update().filter(
                payment_reference=payment_ref
            ).first()

            if app_payment:
                if app_payment.status == 'PAID':
                    logger.info("ApplicationPayment %s already PAID", payment_ref)
                    return JsonResponse({'status': 'duplicate'}, status=200)
                app_payment.status = 'PAID'
                app_payment.receipt_number = data.get('receiptNumber')
                app_payment.transaction_id = data.get('transactionId')
                app_payment.save()
                logger.info("✅ ApplicationPayment %s marked PAID", payment_ref)

                # ── Link payment back to the application ──────────────────
                # Find the applicant's most recent submitted application and
                # stamp it as fee-paid so admins can see it is confirmed.
                from admissions.models import Application as App
                linked_app = (
                    App.objects.filter(applicant=app_payment.user)
                    .exclude(status='draft')
                    .order_by('-created_at')
                    .first()
                )
                if linked_app and not linked_app.application_fee_paid:
                    linked_app.application_fee_paid = True
                    linked_app.application_fee_amount = app_payment.amount
                    if not linked_app.application_reference:
                        linked_app.application_reference = app_payment.external_reference
                    linked_app.save(update_fields=[
                        'application_fee_paid',
                        'application_fee_amount',
                        'application_reference',
                    ])
                    logger.info("✅ Application %s marked fee_paid", linked_app.id)
                # ─────────────────────────────────────────────────────────

                return JsonResponse({'status': 'ok'}, status=200)

    except Exception as e:
        logger.exception("Error processing ApplicationPayment for ref %s", payment_ref)
        return JsonResponse({'error': 'Internal server error'}, status=500)

    # ── Try StudentTuitionPayment (tuition / portal-initiated) ───────────────
    try:
        with transaction.atomic():
            tuition_payment = StudentTuitionPayment.objects.select_for_update().filter(
                payment_reference=payment_ref
            ).first()

            if tuition_payment:
                if tuition_payment.status == 'completed':
                    logger.info("StudentTuitionPayment %s already completed", payment_ref)
                    return JsonResponse({'status': 'duplicate'}, status=200)
                from django.utils import timezone as tz
                tuition_payment.status = 'completed'
                tuition_payment.receipt_number = data.get('receiptNumber', '')
                tuition_payment.paid_at = tz.now()
                tuition_payment.notes = (
                    tuition_payment.notes + f"\nSchoolPay transactionId: {data.get('transactionId', '')}"
                ).strip()
                tuition_payment.save()
                logger.info("✅ StudentTuitionPayment %s marked completed", payment_ref)
                return JsonResponse({'status': 'ok'}, status=200)

    except Exception as e:
        logger.exception("Error processing StudentTuitionPayment for ref %s", payment_ref)
        return JsonResponse({'error': 'Internal server error'}, status=500)

    logger.warning("No matching payment found for reference: %s", payment_ref)
    return JsonResponse({'status': 'unknown'}, status=200)

# Status Check (for frontend polling or Celery task)
class CheckPaymentStatus(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, payment_ref):
        payment = ApplicationPayment.objects.get(
            payment_reference=payment_ref,
            user=request.user
        )

        if payment.status == 'PAID':
            return Response({
                'status': 'PAID',
                "transactionId":payment.transaction_id,
                })

        client = SchoolPayClient()
        data = client.check_status(payment.payment_reference) 

        if data.get('returnCode') == 0:
            if data.get('status') == 'PAID':
                with transaction.atomic():
                    payment.status = 'PAID'
                    payment.receipt_number = data.get('receiptNumber')
                    payment.transaction_id = data.get('transactionId')
                    payment.save()

            elif data.get('status') in ['FAILED', 'CANCELLED']:
                payment.status = 'FAILED'
                payment.save()

        return Response({
            'status': payment.status,
            "transactionId":payment.transaction_id,
            })
# ========================================================end schoolpay====================================================

# ==================================Payments==============================

# list payments
class ListPayments(generics.ListAPIView):
    serializer_class = ApplicationPaymentSerializer

    def get_queryset(self):
        return ApplicationPayment.objects.select_related(
            'application',
            'application__batch',
            'user'
        ).all()
    
# School pay code generation
# @api_view(['POST'])
# @permission_classes([IsAuthenticated])
# def generate_paycode(request, student_id):
#     student = get_object_or_404(AdmittedStudent, id=student_id)

#     if student.is_registered_with_schoolpay:
#         return Response({
#             "detail": "Already registered with SchoolPay",
#             "schoolpay_code": student.student_id
#         })

#     result = register_student_with_schoolpay(student)

#     print("RESULT OF SCHOOLPAY REGISTRATION:", result)

#     if not result["success"]:
#         return Response({
#             "error": "SchoolPay registration failed",
#             "details": result.get("error") or result.get("data")
#         }, status=400)

#     return Response({
#         "detail": "Paycode generated successfully",
#         "schoolpay_code": student.student_id
#     })


# School pay code generation
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def generate_paycode(request, student_id):
    student = get_object_or_404(AdmittedStudent, id=student_id)

    if student.is_registered_with_schoolpay:
        return Response({
            "detail": "Already registered with SchoolPay",
            "schoolpay_code": student.student_id,
            "student_name": student.full_name,
        })

    result = register_student_with_schoolpay(student)
    logger.info("SchoolPay registration for admitted student %s: %s", student_id, result.get("success"))

    if not result["success"]:
        return Response({
            "error": "SchoolPay registration failed",
            "details": result.get("error") or result.get("data"),
            "expected_name": result.get("expected_name"),
            "gateway_name": result.get("gateway_name"),
            "payment_code": result.get("payment_code"),
        }, status=400)

    student.refresh_from_db()
    return Response({
        "detail": "Paycode generated successfully",
        "schoolpay_code": student.student_id,
        "student_name": student.full_name,
        "gateway_name": result.get("gateway_name"),
    })








