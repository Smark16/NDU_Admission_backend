from django.urls import path
from .views import *

app_name = 'payments'

urlpatterns = [
    path('create_fee_plan', CreateFeePlan.as_view()),
    path('list_fee_plan', ListFeePlan.as_view()),
    path('update_fee_plan/<int:pk>', UpdateFeePlan.as_view()),
    path('delete_fee_plan/<int:pk>', DeleteFeePlan.as_view())
]


















