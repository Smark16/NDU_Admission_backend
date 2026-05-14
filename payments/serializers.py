from rest_framework import serializers
from .models import *
from admissions.serializers import *
from rest_framework import serializers

from payments.models import TuitionLedger

# application serilazer
class ApplicationFeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApplicationFee
        fields = '__all__'
  
# list serializer
class ListApplicationFeeSerializer(serializers.ModelSerializer):
    admission_period = serializers.CharField(source="admission_period.name")
    admission_id = serializers.IntegerField(source="admission_period.id")
    academic_year = serializers.CharField(source="admission_period.academic_year")
    class Meta:
        model = ApplicationFee
        fields = '__all__'

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response['academic_level'] = AcademicLevelSerializer(instance.academic_level.all(), many=True).data
        return response

# ==============payments==============
class ApplicationPaymentSerializer(serializers.ModelSerializer):
    studentName = serializers.SerializerMethodField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    paymentDate = serializers.SerializerMethodField()
    paymentTime = serializers.SerializerMethodField()
    feeDescription = serializers.SerializerMethodField()
    transactionStatus = serializers.SerializerMethodField()
    intake = serializers.SerializerMethodField()
    currencyType = serializers.SerializerMethodField()

    class Meta:
        model = ApplicationPayment
        fields = [
            'id',
            'studentName',
            'amount',
            'paymentDate',
            'paymentTime',
            'feeDescription',
            'transactionStatus',
            'intake',
            'currencyType',
        ]

    # ============================
    # COMPUTED FIELDS
    # ============================

    def get_studentName(self, obj):
        if obj.application:
            return f"{obj.application.first_name} {obj.application.last_name}"
        return f"{obj.user.first_name} {obj.user.last_name}"

    def get_paymentDate(self, obj):
        return obj.created_at.strftime('%Y-%m-%d') if obj.created_at else None

    def get_paymentTime(self, obj):
        return obj.created_at.strftime('%H:%M:%S') if obj.created_at else None

    def get_feeDescription(self, obj):
        return "Application Fee"

    def get_transactionStatus(self, obj):
        return obj.status.lower()  # "PAID" → "paid"

    def get_intake(self, obj):
        if obj.application and obj.application.batch:
            batch = obj.application.batch
            return f"{batch.name} ({batch.academic_year})"
        return None

    def get_currencyType(self, obj):
        if obj.application and obj.application.nationality:
            if obj.application.nationality.lower() == 'uganda':
                return 'local'
            return 'international'
        return 'unknown'
    
# transaction sync serializer
class TuitionLedgerSerializer(serializers.ModelSerializer):
    student_full_name = serializers.SerializerMethodField()
    class Meta:
        model = TuitionLedger

        fields = [
            "id",
            "student_full_name",
            "student_name",
            "student_payment_code",
            "amount",
            "payment_date_time",
            "schoolpay_receipt_number",
            "settlement_bank_code",
            "source_payment_channel",
            "transaction_completion_status",
            "reconciled",
            "created_at",
        ]

    def get_student_full_name(self, obj):
        if obj.student and obj.student.student_user:
            return (
                f"{obj.student.student_user.first_name} "
                f"{obj.student.student_user.last_name}"
            )

        return None
