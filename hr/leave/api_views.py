from django.db import transaction
from django.utils import timezone
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated, DjangoModelPermissions
from rest_framework.response import Response
from rest_framework.views import APIView

from hr.staff.utils.profile_sync import resolve_staff_profile_for_user

from .models import LeaveApproval, LeaveBalance, LeavePolicy, LeaveRequest, LeaveType, PublicHoliday
from .serializers import (
    LeaveApprovalListSerializer,
    LeavePolicySerializer,
    LeaveRequestCreateSerializer,
    LeaveRequestListSerializer,
    LeaveTypeSerializer,
    PublicHolidaySerializer,
)
from .workflow_utils import (
    create_appeal_approval,
    generate_approval_workflow,
    process_leave_approval,
    update_balance_pending,
)


def _user_is_hr(user):
    return user.is_superuser or user.has_perm("leave.change_leaverequest")


def _get_staff_for_user(user, staff_id=None):
    if staff_id and _user_is_hr(user):
        from hr.staff.models import StaffProfile

        return StaffProfile.objects.filter(pk=staff_id).first()
    return resolve_staff_profile_for_user(user)


class LeaveTypeListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LeaveTypeSerializer
    queryset = LeaveType.objects.filter(is_active=True).order_by("sort_order", "name")


class LeaveRequestListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = LeaveRequestListSerializer
    queryset = LeaveRequest.objects.select_related("staff", "leave_type").order_by("-request_date")

    def list(self, request, *args, **kwargs):
        if not request.user.has_perm("leave.view_leaverequest"):
            return Response({"detail": "You do not have permission to view leave requests."}, status=403)
        return super().list(request, *args, **kwargs)


class MyLeaveRequestsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        staff = _get_staff_for_user(request.user)
        if not staff:
            return Response({"detail": "Staff profile not linked to your account."}, status=400)
        requests = LeaveRequest.objects.filter(staff=staff).select_related("leave_type").order_by("-request_date")
        return Response(LeaveRequestListSerializer(requests, many=True).data)


class MyLeaveBalancesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        staff = _get_staff_for_user(request.user)
        if not staff:
            return Response({"detail": "Staff profile not linked to your account."}, status=400)
        year = request.query_params.get("year")
        balances = LeaveBalance.objects.filter(staff=staff).select_related("leave_type")
        if year:
            balances = balances.filter(year=year)
        data = [
            {
                "leave_type": b.leave_type.name,
                "leave_type_id": str(b.leave_type_id),
                "year": b.year,
                "entitled_days": float(b.total_entitled),
                "used_days": float(b.taken),
                "pending_days": float(b.pending),
                "available_days": b.available,
            }
            for b in balances.order_by("-year", "leave_type__sort_order")
        ]
        return Response(data)


class LeaveRequestCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        if not request.user.has_perm("leave.add_leaverequest"):
            return Response({"detail": "You do not have permission to submit leave."}, status=403)

        serializer = LeaveRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        staff_id = data.pop("staff_id", None)
        staff = _get_staff_for_user(request.user, staff_id)
        if not staff:
            if _user_is_hr(request.user) and not staff_id:
                return Response({"detail": "Select a staff member for this leave request."}, status=400)
            return Response(
                {"detail": "Staff profile required. Link your account or select a staff member."},
                status=400,
            )

        start = data["start_date"]
        end = data["end_date"]
        leave_request = LeaveRequest.objects.create(
            staff=staff,
            status="PENDING",
            total_days=(end - start).days + 1,
            **data,
        )
        generate_approval_workflow(leave_request)
        update_balance_pending(leave_request, "add")
        return Response(LeaveRequestListSerializer(leave_request).data, status=201)


class PendingApprovalsListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        staff = _get_staff_for_user(request.user)
        if not staff and not _user_is_hr(request.user):
            return Response({"detail": "Staff profile not found."}, status=400)

        approvals = LeaveApproval.objects.none()
        if staff:
            approvals = LeaveApproval.objects.filter(
                approver=staff,
                status="PENDING",
                is_current=True,
            )
        if _user_is_hr(request.user):
            hr_approvals = LeaveApproval.objects.filter(
                approver__isnull=True,
                approver_role="HR_ADMIN",
                status="PENDING",
                is_current=True,
            )
            approvals = (approvals | hr_approvals).distinct()

        approvals = approvals.select_related(
            "leave_request", "leave_request__staff", "leave_request__leave_type"
        ).order_by("-leave_request__request_date")

        return Response(LeaveApprovalListSerializer(approvals, many=True).data)


class LeaveApprovalActionView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, approval_id):
        action = request.data.get("action")
        comments = request.data.get("comments", "")
        if action not in ("APPROVED", "REJECTED"):
            return Response({"detail": "action must be APPROVED or REJECTED."}, status=400)

        approval = LeaveApproval.objects.select_related("leave_request").filter(pk=approval_id).first()
        if not approval:
            return Response({"detail": "Approval not found."}, status=404)

        staff = _get_staff_for_user(request.user)
        can_approve = (
            (staff and approval.approver_id == staff.id)
            or (approval.approver is None and _user_is_hr(request.user))
        )
        if not can_approve:
            return Response({"detail": "You cannot review this approval."}, status=403)

        result = process_leave_approval(approval, action, comments)
        return Response({"detail": result, "status": approval.leave_request.status})


class LeaveRequestCancelView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, request_id):
        staff = _get_staff_for_user(request.user)
        if not staff:
            return Response({"detail": "Staff profile not linked."}, status=400)

        leave_request = LeaveRequest.objects.filter(pk=request_id, staff=staff).first()
        if not leave_request:
            return Response({"detail": "Leave request not found."}, status=404)
        if leave_request.status != "PENDING":
            return Response({"detail": "Only pending requests can be cancelled."}, status=400)

        leave_request.status = "CANCELLED"
        leave_request.save(update_fields=["status"])
        update_balance_pending(leave_request, "remove")
        return Response(LeaveRequestListSerializer(leave_request).data)


class LeaveRequestAppealView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, request_id):
        staff = _get_staff_for_user(request.user)
        if not staff:
            return Response({"detail": "Staff profile not linked."}, status=400)

        leave_request = LeaveRequest.objects.filter(pk=request_id, staff=staff).first()
        if not leave_request:
            return Response({"detail": "Leave request not found."}, status=404)
        if not leave_request.can_appeal:
            return Response({"detail": "This request cannot be appealed."}, status=400)
        if leave_request.appeal_deadline and timezone.now().date() > leave_request.appeal_deadline:
            return Response({"detail": "Appeal deadline has passed."}, status=400)

        appeal_reason = (request.data.get("appeal_reason") or "").strip()
        if not appeal_reason:
            return Response({"detail": "Appeal reason is required."}, status=400)

        leave_request.status = "UNDER_APPEAL"
        leave_request.appeal_reason = appeal_reason
        leave_request.appeal_date = timezone.now()
        leave_request.can_appeal = False
        leave_request.save()
        create_appeal_approval(leave_request)
        return Response(LeaveRequestListSerializer(leave_request).data)


class HrLeaveBalancesListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _user_is_hr(request.user):
            return Response({"detail": "Permission denied."}, status=403)

        year = request.query_params.get("year")
        balances = LeaveBalance.objects.select_related("staff", "leave_type").order_by(
            "-year", "staff__last_name", "leave_type__sort_order"
        )
        if year:
            balances = balances.filter(year=year)

        data = [
            {
                "staff_name": b.staff.get_full_name,
                "leave_type": b.leave_type.name,
                "year": b.year,
                "entitled_days": float(b.total_entitled),
                "used_days": float(b.taken),
                "pending_days": float(b.pending),
                "available_days": b.available,
            }
            for b in balances
        ]
        return Response(data)


class LeavePolicyListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = LeavePolicySerializer
    queryset = LeavePolicy.objects.select_related("campus", "leave_type").order_by("campus__name", "leave_type__name")


class LeavePolicyDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = LeavePolicySerializer
    queryset = LeavePolicy.objects.all()
    lookup_url_kwarg = "policy_id"


class PublicHolidayListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = PublicHolidaySerializer
    queryset = PublicHoliday.objects.select_related("campus").order_by("-date")


class PublicHolidayDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = PublicHolidaySerializer
    queryset = PublicHoliday.objects.all()
    lookup_url_kwarg = "holiday_id"
