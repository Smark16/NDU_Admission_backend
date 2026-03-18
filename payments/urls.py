from django.urls import path
from .views import *

app_name = 'payments'

urlpatterns = [
    path('create_fee_plan', CreateFeePlan.as_view()),
    path('list_fee_plan', ListFeePlan.as_view()),
    path('update_fee_plan/<int:pk>', UpdateFeePlan.as_view()),
    path('delete_fee_plan/<int:pk>', DeleteFeePlan.as_view()),

    # school payment
    path('initiate_payment/', InitiatePayment.as_view()),
    path('webhook/', schoolpay_webhook, name='schoolpay_webhook'),
    path('check_payment_status/<str:payment_ref>/', CheckPaymentStatus.as_view()),

]


















