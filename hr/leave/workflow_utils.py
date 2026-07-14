"""Shared leave workflow helpers for HTML views and REST API."""
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from .models import LeaveApproval, LeaveBalance


def get_staff_supervisor(staff):
    assignment = staff.assigned_supervisors.select_related("supervisor").first()
    return assignment.supervisor if assignment else None


def generate_approval_workflow(leave_request):
    staff = leave_request.staff
    workflow = []
    level = 1
    supervisor = get_staff_supervisor(staff)

    if supervisor:
        workflow.append({
            "level": level,
            "approver_role": "SUPERVISOR",
            "approver": supervisor,
            "is_current": True,
        })
        level += 1

    if staff.org_unit_id:
        director = staff.org_unit.managed_by.first()
        if director and director != staff and director != supervisor:
            workflow.append({
                "level": level,
                "approver_role": "DIRECTOR",
                "approver": director,
                "is_current": level == 1,
            })
            level += 1

    workflow.append({
        "level": level,
        "approver_role": "HR_ADMIN",
        "approver": None,
        "is_current": level == 1,
    })

    for item in workflow:
        LeaveApproval.objects.create(leave_request=leave_request, **item)


def update_balance_pending(leave_request, action):
    try:
        balance = LeaveBalance.objects.get(
            staff=leave_request.staff,
            leave_type=leave_request.leave_type,
            year=leave_request.start_date.year,
        )
        if action == "add":
            balance.pending += Decimal(str(leave_request.total_days))
        elif action == "remove":
            balance.pending -= Decimal(str(leave_request.total_days))
            if balance.pending < 0:
                balance.pending = 0
        balance.save()
    except LeaveBalance.DoesNotExist:
        pass


def process_leave_approval(approval, action, comments=""):
    from .models import LeaveRequest

    leave_request = approval.leave_request
    approval.status = action
    approval.decision_date = timezone.now()
    approval.is_current = False
    if comments:
        approval.comments = comments
    approval.save()

    if action == "APPROVED":
        next_approval = (
            LeaveApproval.objects.filter(
                leave_request=leave_request,
                level__gt=approval.level,
                status="PENDING",
            )
            .order_by("level")
            .first()
        )
        if next_approval:
            next_approval.is_current = True
            next_approval.save()
            return "forwarded"
        leave_request.status = "APPROVED"
        leave_request.save()
        update_balance_pending(leave_request, "remove")
        return "approved"
    else:
        leave_request.status = "REJECTED"
        leave_request.can_appeal = True
        leave_request.appeal_deadline = timezone.now().date() + timedelta(days=3)
        leave_request.save()
        update_balance_pending(leave_request, "remove")
        return "rejected"


def create_appeal_approval(leave_request):
    """Create appeal approval record for next higher authority."""
    rejection = leave_request.approvals.filter(status="REJECTED").first()
    if not rejection:
        return

    approver = None
    role = "HR_ADMIN"
    if rejection.approver_role == "SUPERVISOR":
        org_unit = leave_request.staff.org_unit
        director = org_unit.managed_by.first() if org_unit else None
        approver = director
        role = "DIRECTOR"
    elif rejection.approver_role == "DIRECTOR":
        approver = rejection.approver.supervisor if rejection.approver else None
        role = "DVC" if approver else "HR_ADMIN"

    LeaveApproval.objects.create(
        leave_request=leave_request,
        level=rejection.level + 0.5,
        approver_role=role,
        approver=approver,
        status="PENDING",
        is_current=True,
        is_appeal_review=True,
    )
