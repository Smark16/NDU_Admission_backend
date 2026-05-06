"""
Staff-facing API for per-student ad-hoc charge management.

All charges are stored as StudentTuitionPayment rows with source='ad_hoc'.

Endpoints
---------
GET    /api/payments/admin/student/<student_id>/charges        — list all charges for student
POST   /api/payments/admin/student/<student_id>/charges        — create a new charge
GET    /api/payments/admin/charge/<pk>                         — retrieve one charge
PATCH  /api/payments/admin/charge/<pk>                         — update label/amount/notes
POST   /api/payments/admin/charge/<pk>/waive                   — soft-cancel (is_waived=True)
DELETE /api/payments/admin/charge/<pk>                         — hard delete (pending only)

FeeHead list (for dropdown)
GET    /api/payments/fee_heads                                  — list active FeeHeads
"""
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from admissions.models import AdmittedStudent
from .models import FeeHead, StudentTuitionPayment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _charge_to_dict(c: StudentTuitionPayment) -> dict:
    return {
        "id":            c.id,
        "source":        c.source,
        "fee_head_id":   c.fee_head_id,
        "fee_head_name": c.fee_head.name if c.fee_head_id else None,
        "fee_head_category": c.fee_head.category if c.fee_head_id else None,
        "label":         c.label,
        "amount":        float(c.amount),
        "currency":      c.currency,
        "status":        c.status,
        "payment_method": c.payment_method or "",
        "receipt_number": c.receipt_number or "",
        "paid_at":       c.paid_at.isoformat() if c.paid_at else None,
        "is_waived":     c.is_waived,
        "waived_by":     c.waived_by.get_full_name() if c.waived_by_id else None,
        "waived_at":     c.waived_at.isoformat() if c.waived_at else None,
        "notes":         c.notes,
        "charged_by":    c.charged_by.get_full_name() if c.charged_by_id else None,
        "created_at":    c.created_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

def _feehead_to_dict(h: FeeHead) -> dict:
    return {
        "id":               h.id,
        "code":             h.code,
        "name":             h.name,
        "category":         h.category,
        "category_display": h.get_category_display(),
        "description":      h.description,
        "is_active":        h.is_active,
        "created_at":       h.created_at.isoformat(),
        "updated_at":       h.updated_at.isoformat(),
    }


class FeeHeadListView(APIView):
    """
    GET  /api/payments/fee_heads   — list fee heads (active only for dropdown; all for management)
    POST /api/payments/fee_heads   — create a new fee head
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # ?all=true returns inactive too (management view); default returns active only
        show_all = request.query_params.get("all", "").lower() == "true"
        qs = FeeHead.objects.all() if show_all else FeeHead.objects.filter(is_active=True)
        return Response([_feehead_to_dict(h) for h in qs.order_by('category', 'name')])

    def post(self, request):
        if not request.user.is_staff:
            return Response({"detail": "Only staff can create fee heads."}, status=status.HTTP_403_FORBIDDEN)
        code = (request.data.get("code") or "").strip().upper()
        name = (request.data.get("name") or "").strip()
        category = (request.data.get("category") or "other").strip()
        description = (request.data.get("description") or "").strip()

        if not code:
            return Response({"detail": "code is required."}, status=status.HTTP_400_BAD_REQUEST)
        if not name:
            return Response({"detail": "name is required."}, status=status.HTTP_400_BAD_REQUEST)

        valid_categories = [c[0] for c in FeeHead.CATEGORY_CHOICES]
        if category not in valid_categories:
            return Response({"detail": f"Invalid category. Choices: {valid_categories}"}, status=status.HTTP_400_BAD_REQUEST)

        if FeeHead.objects.filter(code=code).exists():
            return Response({"detail": f"A fee head with code '{code}' already exists."}, status=status.HTTP_400_BAD_REQUEST)

        head = FeeHead.objects.create(code=code, name=name, category=category, description=description)
        return Response(_feehead_to_dict(head), status=status.HTTP_201_CREATED)


class FeeHeadDetailView(APIView):
    """
    GET    /api/payments/fee_heads/<pk>  — retrieve
    PATCH  /api/payments/fee_heads/<pk>  — update
    DELETE /api/payments/fee_heads/<pk>  — deactivate (soft delete)
    """
    permission_classes = [IsAdminUser]

    def _get(self, pk):
        return get_object_or_404(FeeHead, pk=pk)

    def get(self, request, pk):
        return Response(_feehead_to_dict(self._get(pk)))

    def patch(self, request, pk):
        head = self._get(pk)

        if "code" in request.data:
            new_code = (request.data["code"] or "").strip().upper()
            if not new_code:
                return Response({"detail": "code cannot be blank."}, status=status.HTTP_400_BAD_REQUEST)
            if FeeHead.objects.filter(code=new_code).exclude(pk=pk).exists():
                return Response({"detail": f"Code '{new_code}' already in use."}, status=status.HTTP_400_BAD_REQUEST)
            head.code = new_code

        if "name" in request.data:
            head.name = (request.data["name"] or "").strip()
        if "category" in request.data:
            cat = (request.data["category"] or "other").strip()
            valid_categories = [c[0] for c in FeeHead.CATEGORY_CHOICES]
            if cat not in valid_categories:
                return Response({"detail": f"Invalid category. Choices: {valid_categories}"}, status=status.HTTP_400_BAD_REQUEST)
            head.category = cat
        if "description" in request.data:
            head.description = request.data["description"]
        if "is_active" in request.data:
            head.is_active = bool(request.data["is_active"])

        head.save()
        return Response(_feehead_to_dict(head))

    def delete(self, request, pk):
        head = self._get(pk)
        # Soft delete — deactivate rather than destroy (preserves existing charge references)
        head.is_active = False
        head.save()
        return Response({"detail": f"Fee head '{head.name}' deactivated."}, status=status.HTTP_200_OK)


class StudentAdHocChargeListCreate(APIView):
    """
    GET  /api/payments/admin/student/<student_id>/charges — list charges
    POST /api/payments/admin/student/<student_id>/charges — create charge
    """
    permission_classes = [IsAdminUser]

    def get(self, request, student_id):
        student = get_object_or_404(AdmittedStudent, pk=student_id)
        charges = (
            StudentTuitionPayment.objects
            .filter(student=student, source='ad_hoc')
            .select_related('fee_head', 'charged_by', 'waived_by')
            .order_by('-created_at')
        )
        return Response({
            "student_id":   student.student_id,
            "reg_no":       student.reg_no,
            "student_name": student.full_name,
            "charges":      [_charge_to_dict(c) for c in charges],
            "total_count":  charges.count(),
        })

    def post(self, request, student_id):
        student = get_object_or_404(AdmittedStudent, pk=student_id)

        fee_head_id = request.data.get("fee_head_id")
        amount      = request.data.get("amount")
        label       = (request.data.get("label") or "").strip()
        currency    = (request.data.get("currency") or "UGX").strip().upper()
        notes       = request.data.get("notes", "")

        if not fee_head_id:
            return Response({"detail": "fee_head_id is required."}, status=status.HTTP_400_BAD_REQUEST)
        if not amount:
            return Response({"detail": "amount is required."}, status=status.HTTP_400_BAD_REQUEST)
        if not label:
            return Response({"detail": "label is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            amount = float(amount)
            if amount <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return Response({"detail": "amount must be a positive number."}, status=status.HTTP_400_BAD_REQUEST)

        fee_head = get_object_or_404(FeeHead, pk=fee_head_id, is_active=True)

        charge = StudentTuitionPayment.objects.create(
            student=student,
            source='ad_hoc',
            fee_head=fee_head,
            label=label,
            amount=amount,
            currency=currency,
            status='pending',
            payment_method='',
            notes=notes,
            charged_by=request.user,
        )

        return Response(_charge_to_dict(charge), status=status.HTTP_201_CREATED)


class StudentAdHocChargeDetailView(APIView):
    """
    GET    /api/payments/admin/charge/<pk>         — retrieve
    PATCH  /api/payments/admin/charge/<pk>         — update
    POST   /api/payments/admin/charge/<pk>/waive   — waive
    DELETE /api/payments/admin/charge/<pk>         — hard delete (pending only)
    """
    permission_classes = [IsAdminUser]

    def _get(self, pk):
        return get_object_or_404(
            StudentTuitionPayment.objects.select_related(
                'fee_head', 'charged_by', 'waived_by', 'student'
            ),
            pk=pk,
            source='ad_hoc',
        )

    def get(self, request, pk):
        return Response(_charge_to_dict(self._get(pk)))

    def patch(self, request, pk):
        charge = self._get(pk)

        if charge.status == 'completed':
            return Response(
                {"detail": "Completed charges cannot be edited. Waive and re-issue if needed."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        fee_head_id = request.data.get("fee_head_id")
        if fee_head_id:
            charge.fee_head = get_object_or_404(FeeHead, pk=fee_head_id, is_active=True)

        if "label" in request.data:
            charge.label = (request.data["label"] or "").strip()
        if "amount" in request.data:
            try:
                amt = float(request.data["amount"])
                if amt <= 0:
                    raise ValueError
                charge.amount = amt
            except (TypeError, ValueError):
                return Response({"detail": "amount must be a positive number."}, status=status.HTTP_400_BAD_REQUEST)
        if "currency" in request.data:
            charge.currency = (request.data["currency"] or "UGX").strip().upper()
        if "notes" in request.data:
            charge.notes = request.data["notes"]

        charge.save()
        return Response(_charge_to_dict(charge))

    def delete(self, request, pk):
        charge = self._get(pk)
        if charge.status != 'pending':
            return Response(
                {"detail": "Only pending charges can be deleted. Use waive to cancel a paid or active charge."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        label = charge.label
        charge.delete()
        return Response({"detail": f"Charge '{label}' deleted."}, status=status.HTTP_204_NO_CONTENT)


class StudentAdHocChargeWaiveView(APIView):
    """POST /api/payments/admin/charge/<pk>/waive"""
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        charge = get_object_or_404(
            StudentTuitionPayment, pk=pk, source='ad_hoc'
        )
        if charge.is_waived:
            return Response({"detail": "Charge is already waived."}, status=status.HTTP_400_BAD_REQUEST)

        charge.is_waived = True
        charge.waived_by = request.user
        charge.waived_at = timezone.now()
        if "notes" in request.data:
            charge.notes = request.data["notes"]
        charge.save()

        return Response({
            "detail": f"Charge '{charge.label}' has been waived.",
            **_charge_to_dict(charge),
        })
