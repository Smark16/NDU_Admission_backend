from rest_framework import serializers

from .models import LeaveApproval, LeavePolicy, LeaveRequest, LeaveType, PublicHoliday


class LeaveTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveType
        fields = ["id", "name", "code", "max_days_per_year", "is_active"]


class LeaveRequestListSerializer(serializers.ModelSerializer):
    staff_name = serializers.CharField(source="staff.get_full_name", read_only=True)
    leave_type_name = serializers.CharField(source="leave_type.name", read_only=True)

    class Meta:
        model = LeaveRequest
        fields = [
            "id",
            "request_number",
            "staff_name",
            "leave_type_name",
            "start_date",
            "end_date",
            "total_days",
            "status",
            "request_date",
            "can_appeal",
            "appeal_deadline",
        ]


class LeaveRequestCreateSerializer(serializers.ModelSerializer):
    staff_id = serializers.IntegerField(write_only=True, required=False)

    class Meta:
        model = LeaveRequest
        fields = [
            "staff_id",
            "leave_type",
            "start_date",
            "end_date",
            "reason",
            "contact_during_leave",
        ]

    def validate(self, attrs):
        start = attrs.get("start_date")
        end = attrs.get("end_date")
        if start and end and end < start:
            raise serializers.ValidationError("End date cannot be before start date.")
        return attrs


class LeaveApprovalListSerializer(serializers.ModelSerializer):
    request_number = serializers.CharField(source="leave_request.request_number", read_only=True)
    staff_name = serializers.CharField(source="leave_request.staff.get_full_name", read_only=True)
    leave_type_name = serializers.CharField(source="leave_request.leave_type.name", read_only=True)
    start_date = serializers.DateField(source="leave_request.start_date", read_only=True)
    end_date = serializers.DateField(source="leave_request.end_date", read_only=True)
    total_days = serializers.DecimalField(
        source="leave_request.total_days", max_digits=5, decimal_places=1, read_only=True
    )

    class Meta:
        model = LeaveApproval
        fields = [
            "id",
            "request_number",
            "staff_name",
            "leave_type_name",
            "start_date",
            "end_date",
            "total_days",
            "approver_role",
            "status",
            "is_current",
        ]


class LeavePolicySerializer(serializers.ModelSerializer):
    campus_name = serializers.CharField(source="campus.name", read_only=True)
    leave_type_name = serializers.CharField(source="leave_type.name", read_only=True)

    class Meta:
        model = LeavePolicy
        fields = [
            "id",
            "campus",
            "campus_name",
            "leave_type",
            "leave_type_name",
            "position_category",
            "annual_entitlement_days",
            "accrual_method",
            "min_notice_days",
            "max_consecutive_days",
            "effective_date",
            "expiry_date",
            "is_active",
        ]


class PublicHolidaySerializer(serializers.ModelSerializer):
    campus_name = serializers.CharField(source="campus.name", read_only=True)

    class Meta:
        model = PublicHoliday
        fields = [
            "id",
            "name",
            "date",
            "campus",
            "campus_name",
            "is_recurring",
            "is_active",
        ]
