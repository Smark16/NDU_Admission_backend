from rest_framework.permissions import *
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from .serializers import *
from Drafts.models import *
import json
import logging
import uuid

from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import ApplicationFee, ApplicationPayment, StudentTuitionPayment
from .utils.schoolpay import SchoolPayClient
from django.utils import timezone
from datetime import timedelta
from .serializers import ApplicationPaymentSerializer
from admissions.models import Application
from payments.utils.school_pay_code import register_student_with_schoolpay
from accounts.models import User
from rest_framework.decorators import api_view, permission_classes
from django.shortcuts import get_object_or_404

logger = logging.getLogger(__name__)

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
# Cancel Payment
class CancelPayment(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            ApplicationPayment.objects.filter(
                user=request.user,
                status='PENDING',
            ).update(status='FAILED')

            return Response({
                'detail': "Pending payment cancelled successfully"
            })
        
        except Exception as e:
            logger.exception("Error cancelling payment for user")
            return Response({
            'detail': "canceling pending payment failed"
        }, status=400)
     
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
          callBackUrl = "https://320f-41-75-173-243.ngrok-free.app/api/payments/webhook/" 
        else:
          callBackUrl = request.build_absolute_uri("/api/payments/webhook/")

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
                draft = DraftApplication.objects.filter(
                    applicant=app_payment.user,
                ).order_by('-updated_at').first()

                if app_payment.status == 'PAID':
                    logger.info("ApplicationPayment %s already PAID", payment_ref)
                    return JsonResponse({'status': 'duplicate'}, status=200)
                app_payment.status = 'PAID'
                app_payment.receipt_number = data.get('receiptNumber')
                app_payment.transaction_id = data.get('transactionId')
                app_payment.save(update_fields=['status','receipt_number','transaction_id'])
                logger.info("✅ ApplicationPayment %s marked PAID", payment_ref)

                # manage draft
                if draft:
                    draft.application_fee_paid = True
                    draft.application_reference = app_payment.external_reference
                    draft.save(update_fields=['application_fee_paid', 'application_reference'])

                return JsonResponse({'status': 'ok'}, status=200)

    except Exception as e:
        logger.exception("Error processing ApplicationPayment for ref %s", payment_ref)
        return JsonResponse({'error': 'Internal server error'}, status=500)

    logger.warning("No matching payment found for reference: %s", payment_ref)
    return JsonResponse({'status': 'unknown'}, status=200)

# Status Check (for frontend polling or Celery task)
class CheckPaymentStatus(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, payment_ref):

        payment = ApplicationPayment.objects.filter(
            payment_reference=payment_ref,
            user=request.user
        ).first()

        # Get or create draft
        draft = DraftApplication.objects.filter(
                applicant=request.user,
            ).order_by('-updated_at').first()

        if payment.status == 'PAID':
            return Response({
                'status': 'PAID',
                'transactionId': payment.transaction_id,
                'external_reference': payment.external_reference,

                # IMPORTANT
                'application_fee_paid': True,
                'draft_updated': True,
            })

        client = SchoolPayClient()
        data = client.check_status(payment.payment_reference) 

        if data.get('returnCode') == 0:
            if data.get('status') == 'PAID':
                with transaction.atomic():
                    payment.status = 'PAID'
                    payment.receipt_number = data.get('receiptNumber')
                    payment.transaction_id = data.get('transactionId')
                    payment.save(update_fields=['status', 'receipt_number', 'transaction_id'])

                    # manage draft
                    if draft:
                        draft.application_fee_paid = True
                        draft.application_reference = payment.external_reference
                        draft.save(update_fields=['application_fee_paid', 'application_reference'])

            elif data.get('status') in ['FAILED', 'CANCELLED']:
                payment.status = 'FAILED'
                payment.save(update_fields=['status'])

        # IMPORTANT
        payment.refresh_from_db()

        if draft:
            draft.refresh_from_db()

        return Response({
            'status': payment.status,
            'transactionId': payment.transaction_id,
            'external_reference': payment.external_reference,

            # IMPORTANT
            'application_fee_paid': draft.application_fee_paid if draft else False,
            'draft_updated': bool(
                draft and draft.application_fee_paid
            ),
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








