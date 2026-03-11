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
from .serializers import ApplicationPaymentSerializer
from admissions.models import Application
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
# Initiate Payment (called from frontend when user clicks "Pay")
class InitiatePayment(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        phone = request.data.get('phone')
        first_name = request.data.get('first_name')
        last_name = request.data.get('last_name')

        amount = request.data.get('amount')
        reason = "Application Fee"

        ext_ref = f"APP-{uuid.uuid4().hex.upper()}"

        client = SchoolPayClient()

        response_data = client.request_payment(
            amount=amount,
            phone=phone,
            ext_ref=ext_ref,
            first_name=first_name,
            last_name=last_name,
            reason=reason
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
            status='PENDING'
        )

        return Response({
            'payment_reference': payment.payment_reference,
            'external_reference': ext_ref,
            'status': payment.status
        })

# Webhook
@csrf_exempt
@require_POST
def schoolpay_webhook(request):
    data = json.loads(request.body)

    if data.get('status') != 'PAID':
        return JsonResponse({'status': 'ignored'}, status=200)

    payment_ref = data.get('paymentReference')

    with transaction.atomic():
        payment = ApplicationPayment.objects.select_for_update().filter(
            payment_reference=payment_ref,
            status='PENDING'
        ).first()

        if not payment:
            return JsonResponse({'status': 'unknown_or_duplicate'}, status=200)

        payment.status = 'PAID'
        payment.receipt_number = data.get('receiptNumber')
        payment.transaction_id = data.get('transactionId')
        payment.save()

    return JsonResponse({'status': 'ok'}, status=200)

# Status Check (for frontend polling or Celery task)
class CheckPaymentStatus(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, payment_ref):
        payment = ApplicationPayment.objects.get(
            payment_reference=payment_ref,
            user=request.user
        )

        if payment.status == 'PAID':
            return Response({'status': 'PAID'})

        client = SchoolPayClient()
        data = client.check_status(payment.external_reference)

        if data.get('returnCode') == 0 and data.get('status') == 'PAID':
            with transaction.atomic():
                payment.status = 'PAID'
                payment.receipt_number = data.get('receiptNumber')
                payment.transaction_id = data.get('transactionId')
                payment.save()

        return Response({'status': payment.status})
# ========================================================end schoolpay====================================================

















