from django.db.models import Q

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import (
    DjangoModelPermissions,
    IsAuthenticated,
)

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
                Q(student_name__icontains=search)
                |
                Q(student_payment_code__icontains=search)
                |
                Q(
                    schoolpay_receipt_number__icontains=search
                )
            )

        queryset = queryset.order_by(
            "-payment_date_time"
        )

        serializer = TuitionLedgerSerializer(
            queryset,
            many=True
        )

        return Response(serializer.data)

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

#export student tution legder
        