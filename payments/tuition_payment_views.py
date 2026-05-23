from django.db.models import Q

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import (
    DjangoModelPermissions,
    IsAuthenticated,
)
from rest_framework.pagination import PageNumberPagination
from django.utils import timezone
from datetime import timedelta, datetime

from payments.models import TuitionLedger
from datetime import datetime
from datetime import timedelta

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import (
    IsAuthenticated,
    IsAdminUser
)

from payments.utils.Transaction_sync import (
    fetch_transactions_by_range, reconcile_transactions
)

from payments.serializers import (
    TuitionLedgerSerializer
)

class StandardPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = 'page_size'
    max_page_size = 100

# fetch all transactions with filters and search
class TuitionLedgerListView(APIView):
    queryset = TuitionLedger.objects.all()

    permission_classes = [
        IsAuthenticated,
        DjangoModelPermissions
    ]

    def get(self, request):

        queryset = (
            TuitionLedger.objects
            .select_related(
                "student",
                "user"
            )
            .all()
        )

        # FILTER BY PAYMENT CODE
        payment_code = request.GET.get(
            "payment_code"
        )

        if payment_code:
            queryset = queryset.filter(
                student_payment_code=payment_code
            )

        # FILTER BY RECEIPT NUMBER
        receipt_number = request.GET.get(
            "receipt_number"
        )

        if receipt_number:
            queryset = queryset.filter(
                schoolpay_receipt_number=receipt_number
            )

        # FILTER BY STATUS
        status_param = request.GET.get(
            "status"
        )

        if status_param:
            queryset = queryset.filter(
                transaction_completion_status=status_param
            )

        # FILTER BY DATE RANGE
        from_date = request.GET.get(
            "from_date"
        )

        to_date = request.GET.get(
            "to_date"
        )

        if from_date and to_date:

            queryset = queryset.filter(
                payment_date_time__date__range=[
                    from_date,
                    to_date
                ]
            )

        # SEARCH
        search = request.GET.get("search")

        if search:

            queryset = queryset.filter(
                Q(student_name__icontains=search) |
                Q(student_payment_code__icontains=search) |
                Q(schoolpay_receipt_number__icontains=search) |
                Q(student_registration_number__icontains=search)
            )

        # ===================== TIME PERIOD FILTER =====================
        time_period = request.query_params.get("time_period")

        today = timezone.now().date()

        if time_period:
            if time_period == "today":
                queryset = queryset.filter(payment_date_time__date=today)

            elif time_period == "yesterday":
                yesterday = today - timedelta(days=1)
                queryset = queryset.filter(payment_date_time__date=yesterday)

            elif time_period == "this_month":
                queryset = queryset.filter(
                    payment_date_time__year=today.year,
                    payment_date_time__month=today.month
                )

            elif time_period == "last_month":
                last_month = today.replace(day=1) - timedelta(days=1)
                queryset = queryset.filter(
                    payment_date_time__year=last_month.year,
                    payment_date_time__month=last_month.month
                )

            elif time_period == "this_year":
                queryset = queryset.filter(payment_date_time__year=today.year)

            elif time_period == "last_year":
                queryset = queryset.filter(payment_date_time__year=today.year - 1)

        queryset = queryset.order_by(
            "-payment_date_time"
        )

        # Pagination
        paginator = StandardPagination()
        paginated_queryset = paginator.paginate_queryset(queryset, request)

        serializer = TuitionLedgerSerializer(paginated_queryset, many=True)

        return paginator.get_paginated_response(serializer.data)
        
# manual transaction sync
class ManualHistoricalReconciliationView(
    APIView
):
    permission_classes = [
        IsAuthenticated,
        IsAdminUser
    ]

    def get(self, request):

        from_date = request.GET.get(
            "from_date"
        )

        to_date = request.GET.get(
            "to_date"
        )

        # VALIDATION
        if not from_date or not to_date:

            return Response({
                "error":
                    "from_date and to_date are required"
            }, status=400)

        try:

            start_date = datetime.strptime(
                from_date,
                "%Y-%m-%d"
            ).date()

            end_date = datetime.strptime(
                to_date,
                "%Y-%m-%d"
            ).date()

        except ValueError:

            return Response({
                "error":
                    "Invalid date format. Use YYYY-MM-DD"
            }, status=400)

        total_synced = 0

        current_start = start_date

        # SCHOOLPAY MAX = 31 DAYS
        while current_start <= end_date:

            current_end = min(
                current_start + timedelta(days=30),
                end_date
            )

            data = fetch_transactions_by_range(
                from_date=current_start.strftime(
                    "%Y-%m-%d"
                ),
                to_date=current_end.strftime(
                    "%Y-%m-%d"
                )
            )

            synced = reconcile_transactions(
                data
            )

            total_synced += synced

            current_start = (
                current_end + timedelta(days=1)
            )

        return Response({

            "message":
                "Historical reconciliation completed successfully",

            "from_date":
                from_date,

            "to_date":
                to_date,

            "total_transactions_synced":
                total_synced
        })

# individual student transactions
class StudentTransactions(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request):

        transactions = (
            TuitionLedger.objects
            .filter(
                user=request.user
            )
            .select_related(
                "student",
                "user"
            )
            .order_by(
                "-payment_date_time"
            )
        )

        serializer = TuitionLedgerSerializer(
            transactions,
            many=True
        )

        return Response(serializer.data)