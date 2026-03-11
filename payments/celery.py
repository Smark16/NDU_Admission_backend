# # tasks.py
# from celery import shared_task
# from .models import ApplicationPayment
# from .utils import SchoolPayClient
# from django.utils import timezone
# from datetime import timedelta

# @shared_task
# def poll_pending_payments():
#     client = SchoolPayClient()
#     threshold = timezone.now() - timedelta(minutes=5)
#     pendings = ApplicationPayment.objects.filter(status='PENDING', created_at__lt=threshold)
    
#     for payment in pendings:
#         try:
#             data = client.check_status(payment.payment_reference)
#             if data.get('returnCode') == 0 and data.get('status') == 'PAID':
#                 with transaction.atomic():
#                     payment.status = 'PAID'
#                     payment.receipt_number = data.get('receiptNumber')
#                     payment.transaction_id = data.get('transactionId')
#                     payment.save()
#                     payment.application.application_fee_paid = True
#                     payment.application.save()
#         except ValueError:
#             pass  # Log, continue