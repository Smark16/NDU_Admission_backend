from rest_framework import serializers

from .models import LeaveApproval, LeavePolicy, LeaveRequest, LeaveType, PublicHoliday


class LeaveTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveType
        fields = [
            "id",
            "name",
            "code",
            "description",
            "max_days_per_year",
            "requires_document",
            "is_paid",
            "gender_specific",
            "has_accrual",
            "carry_over_allowed",
            "max_carry_over_days",
            "carry_over_expiry_months",
            "color",
            "is_active",
            "sort_order",
        ]

    def validate_code(self, value):
        code = (value or "").strip().upper()
        if not code:
            raise serializers.ValidationError("Code is required.")
        if len(code) > 10:
            raise serializers.ValidationError("Code must be 10 characters or fewer.")
        return code

    def validate_name(self, value):
        name = (value or "").strip()
        if len(name) < 2:
            raise serializers.ValidationError("Name is required (at least 2 characters).")
        return name


class LeaveRequestListSerializer(serializers.ModelSerializer):
    staff_name = serializers.CharField(source="staff.get_full_name", read_only=True)
    staff_no = serializers.CharField(source="staff.staff_no", read_only=True, default="")
    leave_type_name = serializers.CharField(source="leave_type.name", read_only=True)
    leave_type_color = serializers.CharField(source="leave_type.color", read_only=True)
    has_attachment = serializers.SerializerMethodField()

    class Meta:
        model = LeaveRequest
        fields = [
            "id",
            "request_number",
            "staff_name",
            "staff_no",
            "leave_type_name",
            "leave_type_color",
            "start_date",
            "end_date",
            "total_days",
            "status",
            "request_date",
            "reason",
            "contact_during_leave",
            "has_attachment",
            "can_appeal",
            "appeal_deadline",
        ]

    def get_has_attachment(self, obj):
        return bool(obj.attachment)


class LeaveRequestCreateSerializer(serializers.ModelSerializer):
    staff_id = serializers.IntegerField(write_only=True, required=False)
    attachment = serializers.FileField(required=False, allow_null=True)

    class Meta:
        model = LeaveRequest
        fields = [
            "staff_id",
            "leave_type",
            "start_date",
            "end_date",
            "reason",
            "contact_during_leave",
            "attachment",
        ]

    def validate(self, attrs):
        start = attrs.get("start_date")
        end = attrs.get("end_date")
        if start and end and end < start:
            raise serializers.ValidationError("End date cannot be before start date.")
        leave_type = attrs.get("leave_type")
        if leave_type and leave_type.requires_document and not attrs.get("attachment"):
            raise serializers.ValidationError(
                {"attachment": "A supporting document is required for this leave type."}
            )
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
