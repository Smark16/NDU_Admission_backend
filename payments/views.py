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

from .models import ApplicationFee, ApplicationPayment
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
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

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
        callBackUrl = "https://e577-196-43-131-1.ngrok-free.app/api/payments/webhook/"
        # callBackUrl = request.build_absolute_uri('/api/payments/webhook/')

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

    # Process the successful payment
    try:
        with transaction.atomic():
            payment = ApplicationPayment.objects.select_for_update().filter(
                payment_reference=payment_ref
            ).first()

            if not payment:
                logger.warning("No matching ApplicationPayment found for reference: %s", payment_ref)
                return JsonResponse({'status': 'unknown'}, status=200)

            # Idempotency - already paid
            if payment.status == 'PAID':
                logger.info("Payment %s already marked as PAID", payment_ref)
                return JsonResponse({'status': 'duplicate'}, status=200)

            # Update payment record
            payment.status = 'PAID'
            payment.receipt_number = data.get('receiptNumber')
            payment.transaction_id = data.get('transactionId')
            payment.save()

            logger.info("✅ Payment %s successfully marked as PAID", payment_ref)

        return JsonResponse({'status': 'ok'}, status=200)

    except Exception as e:
        logger.exception("Error processing SchoolPay webhook for ref %s", payment_ref)
        return JsonResponse({'error': 'Internal server error'}, status=500)

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











