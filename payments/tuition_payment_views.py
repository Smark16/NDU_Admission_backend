from django.db.models import Q

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import (
    DjangoModelPermissions,
    IsAuthenticated,
)

from payments.models import TuitionLedger
from payments.serializers import (
    TuitionLedgerSerializer
)


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