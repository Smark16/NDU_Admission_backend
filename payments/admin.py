from django.contrib import admin
from django.contrib import messages
from .models import (
    ApplicationPayment,
    ApplicationFee,
    TuitionLedger,
    BursarWeeklyReportSettings,
    BursarWeeklyReportRecipient,
    ExemptionFormFeePayment,
)

@admin.register(ApplicationPayment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'application', 'external_reference', 'created_at', 'transaction_id', 'status']
    search_fields = ['user__first_name', 'user__last_name', 'external_reference', 'payment_reference', 'transaction_id']
    list_filter = ['status', 'created_at', 'updated_at']

@admin.register(ApplicationFee)
class ApplicationFeeAdmin(admin.ModelAdmin):
    list_display = ['id', 'fee_type', 'nationality_type', 'amount', 'admission_period']

@admin.register(TuitionLedger)
class TuitionLedgerAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'student', 'amount', 'payment_date_time', 'source_payment_channel', 'student_registration_number', 'transaction_completion_status']
    search_fields = ['user__first_name', 'user__last_name', 'student_registration_number']
    list_filter = ['transaction_completion_status', 'created_at', 'synced_at']


@admin.register(BursarWeeklyReportSettings)
class BursarWeeklyReportSettingsAdmin(admin.ModelAdmin):
    list_display = ["is_enabled", "schedule_day", "schedule_hour", "schedule_minute", "last_sent_at"]


@admin.register(BursarWeeklyReportRecipient)
class BursarWeeklyReportRecipientAdmin(admin.ModelAdmin):
    list_display = ["email", "name", "is_active", "updated_at"]
    list_filter = ["is_active"]
    search_fields = ["email", "name"]


@admin.register(ExemptionFormFeePayment)
class ExemptionFormFeePaymentAdmin(admin.ModelAdmin):
    """Pending/paid UGX 50k Course Exemption form fees — complete like application payments."""

    list_display = [
        "id",
        "student_reg_no",
        "student_name",
        "amount",
        "status",
        "payment_method",
        "payment_reference",
        "paid_at",
        "verified_by",
        "created_at",
    ]
    list_filter = ["status", "payment_method", "created_at"]
    search_fields = [
        "student__reg_no",
        "student__student_id",
        "student__application__first_name",
        "student__application__last_name",
        "payment_reference",
        "transaction_id",
    ]
    readonly_fields = ["created_at", "updated_at", "verified_at"]
    autocomplete_fields = []
    raw_id_fields = ["student", "fee_head", "charged_by", "verified_by", "waived_by", "semester"]
    actions = ["mark_exemption_form_fee_paid"]
    ordering = ["-created_at"]

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related(
            "student",
            "student__application",
            "fee_head",
            "verified_by",
        )
        return qs.filter(source="ad_hoc", fee_head__code="EXEMPTION_FORM")

    @admin.display(description="Reg no", ordering="student__reg_no")
    def student_reg_no(self, obj):
        return getattr(obj.student, "reg_no", "") or ""

    @admin.display(description="Student")
    def student_name(self, obj):
        try:
            return obj.student.full_name or ""
        except Exception:
            return ""

    @admin.action(description="Mark selected exemption form fees as PAID")
    def mark_exemption_form_fee_paid(self, request, queryset):
        from admissions.exemption_form_fee_payment import manually_complete_exemption_form_fee

        done = 0
        skipped = 0
        for payment in queryset:
            try:
                if payment.status == "completed" and (payment.payment_reference or "").strip():
                    skipped += 1
                    continue
                manually_complete_exemption_form_fee(payment, actor=request.user)
                done += 1
            except ValueError:
                skipped += 1
        self.message_user(
            request,
            f"Marked {done} exemption form fee(s) as paid. Skipped {skipped}. "
            "If the student still has the pay dialog open, the exemption will submit. "
            "Otherwise they open Course Exemption and click Submit application.",
            messages.SUCCESS,
        )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if obj.status == "completed":
            from admissions.exemption_form_fee_payment import manually_complete_exemption_form_fee

            try:
                manually_complete_exemption_form_fee(obj, actor=request.user)
            except ValueError:
                pass
