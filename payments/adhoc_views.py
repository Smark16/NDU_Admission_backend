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
POST   /api/payments/admin/charge/<pk>/apply_credit            — settle from existing tuition/SchoolPay credit
DELETE /api/payments/admin/charge/<pk>                         — hard delete (pending only)

FeeHead list (for dropdown)
GET    /api/payments/fee_heads                                  — list active FeeHeads
"""
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from admissions.models import AdmittedStudent
from Programs.models import ProgramBatch, Semester
from Programs.permissions import (
    FeePlanConfigurationPermission,
    StudentChargesPermission,
    user_can_configure_fee_plans,
    user_can_manage_student_charges,
)

from .models import FeeHead, StudentTuitionPayment
from .fee_exemptions import active_fee_exemptions_for_student, exemption_to_dict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _semester_label(semester: Semester | None) -> str | None:
    if semester is None:
        return None
    if semester.year_of_study and semester.term_number:
        return f"Year {semester.year_of_study}, Term {semester.term_number} — {semester.name}"
    return semester.name


def _semester_to_dict(semester: Semester | None) -> dict | None:
    if semester is None:
        return None
    return {
        "id": semester.id,
        "name": semester.name,
        "year_of_study": semester.year_of_study,
        "term_number": semester.term_number,
        "label": _semester_label(semester),
    }


def _student_program_batch_id(student: AdmittedStudent) -> int | None:
    try:
        enrollment = student.programme_enrollment
        if enrollment is not None and enrollment.program_batch_id:
            return int(enrollment.program_batch_id)
    except Exception:
        pass
    if not student.admitted_program_id:
        return None
    fallback = (
        ProgramBatch.objects.filter(program_id=student.admitted_program_id, is_active=True)
        .order_by("-start_date", "name")
        .first()
    )
    return int(fallback.id) if fallback else None


def _student_charge_defaults(student: AdmittedStudent) -> dict:
    year = 1
    term = 1
    program_batch_id = _student_program_batch_id(student)
    try:
        enrollment = student.programme_enrollment
        if enrollment is not None:
            year = int(enrollment.current_year_of_study or 1)
            term = int(enrollment.current_term_number or 1)
    except Exception:
        pass
    return {
        "year_of_study": year,
        "term_number": term,
        "program_batch_id": program_batch_id,
    }


def _semester_options_for_student(student: AdmittedStudent) -> list[Semester]:
    program_batch_id = _student_program_batch_id(student)
    if not program_batch_id:
        return []
    return list(
        Semester.objects.filter(program_batch_id=program_batch_id, is_active=True).order_by(
            "year_of_study",
            "term_number",
            "order",
            "name",
        )
    )


def _resolve_charge_semester(student: AdmittedStudent, data) -> Semester | None:
    semester_id = data.get("semester_id")
    if semester_id not in (None, ""):
        try:
            semester_id = int(semester_id)
        except (TypeError, ValueError):
            return None
        program_batch_id = _student_program_batch_id(student)
        qs = Semester.objects.filter(pk=semester_id)
        if program_batch_id:
            qs = qs.filter(program_batch_id=program_batch_id)
        return qs.first()

    year = data.get("year_of_study")
    term = data.get("term_number")
    if year in (None, "") or term in (None, ""):
        defaults = _student_charge_defaults(student)
        year = defaults["year_of_study"]
        term = defaults["term_number"]

    try:
        year = int(year)
        term = int(term)
    except (TypeError, ValueError):
        return None

    program_batch_id = _student_program_batch_id(student)
    if not program_batch_id:
        return None
    return (
        Semester.objects.filter(
            program_batch_id=program_batch_id,
            year_of_study=year,
            term_number=term,
            is_active=True,
        )
        .order_by("order", "id")
        .first()
    )


def _charge_to_dict(c: StudentTuitionPayment) -> dict:
    from payments.billing_visibility import adhoc_charge_billing_date, adhoc_charge_billing_reached

    semester = getattr(c, "semester", None)
    billing_date = adhoc_charge_billing_date(c)
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
        "semester_id":   c.semester_id,
        "semester":      _semester_to_dict(semester),
        "year_of_study": semester.year_of_study if semester else None,
        "term_number":   semester.term_number if semester else None,
        "applies_to":    _semester_label(semester),
        # When tagged to a future semester, the charge only becomes due/visible to the
        # student on that term's billing date — not the moment it was created.
        "billing_date":  billing_date.isoformat() if billing_date else None,
        "billing_reached": adhoc_charge_billing_reached(c),
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
        if not (
            user_can_configure_fee_plans(request.user)
            or user_can_manage_student_charges(request.user)
        ):
            return Response(
                {"detail": "You do not have permission to create fee heads."},
                status=status.HTTP_403_FORBIDDEN,
            )
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
    permission_classes = [FeePlanConfigurationPermission]

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
    permission_classes = [StudentChargesPermission]

    def get(self, request, student_id):
        student = get_object_or_404(
            AdmittedStudent.objects.select_related(
                "admitted_program",
                "programme_enrollment",
                "programme_enrollment__program_batch",
            ),
            pk=student_id,
        )
        charges = (
            StudentTuitionPayment.objects
            .filter(student=student, source='ad_hoc')
            .select_related('fee_head', 'charged_by', 'waived_by', 'semester')
            .order_by('-created_at')
        )
        return Response({
            "student_id":   student.student_id,
            "reg_no":       student.reg_no,
            "student_name": student.full_name,
            "charge_defaults": _student_charge_defaults(student),
            "semester_options": [
                _semester_to_dict(semester) for semester in _semester_options_for_student(student)
            ],
            "charges":      [_charge_to_dict(c) for c in charges],
            "total_count":  charges.count(),
            "fee_exemptions": [
                exemption_to_dict(r) for r in active_fee_exemptions_for_student(student)
            ],
        })

    def post(self, request, student_id):
        student = get_object_or_404(
            AdmittedStudent.objects.select_related(
                "admitted_program",
                "programme_enrollment",
                "programme_enrollment__program_batch",
            ),
            pk=student_id,
        )

        # entry_kind:
        #   charge (default) — pending ad-hoc bill (increases balance)
        #   credit — completed payment credit (reduces balance; use for legacy
        #            prior-paid / write-downs). Never store negative amounts.
        entry_kind = (request.data.get("entry_kind") or "charge").strip().lower()
        if entry_kind not in ("charge", "credit"):
            return Response(
                {"detail": "entry_kind must be 'charge' or 'credit'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        fee_head_id = request.data.get("fee_head_id")
        amount      = request.data.get("amount")
        label       = (request.data.get("label") or "").strip()
        currency    = (request.data.get("currency") or "UGX").strip().upper()
        notes       = request.data.get("notes", "")
        reference   = (request.data.get("reference") or "").strip()

        if entry_kind == "charge" and not fee_head_id:
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
            return Response(
                {
                    "detail": (
                        "amount must be a positive number. "
                        "To reduce what a student owes, use entry_kind='credit' "
                        "(do not enter a negative bill)."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if entry_kind == "credit":
            fee_head = None
            if fee_head_id not in (None, ""):
                fee_head = get_object_or_404(FeeHead, pk=fee_head_id, is_active=True)
            ref = reference or f"manual-credit-{student.pk}-{timezone.now().strftime('%Y%m%d%H%M%S')}"
            txn_id = f"MANUAL-CREDIT-{student.pk}-{ref}"[:100]
            if StudentTuitionPayment.objects.filter(transaction_id=txn_id).exists():
                return Response(
                    {
                        "detail": (
                            f"A credit with reference '{ref}' already exists for this student. "
                            "Use a different reference."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            try:
                credit = StudentTuitionPayment.objects.create(
                    student=student,
                    source="scholarship",
                    fee_head=fee_head,
                    label=label[:200],
                    amount=amount,
                    currency=currency[:3],
                    payment_method="other",
                    status="completed",
                    transaction_id=txn_id,
                    payment_reference=ref[:100],
                    receipt_number=ref[:100],
                    paid_at=timezone.now(),
                    verified_by=request.user,
                    verified_at=timezone.now(),
                    notes=(
                        (notes or "").strip()
                        or "Manual credit / prior-paid adjustment (positive amount; reduces balance)."
                    ),
                    charged_by=request.user,
                )
            except Exception as exc:
                return Response(
                    {"detail": f"Could not create credit: {exc}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            payload = _charge_to_dict(credit)
            payload["entry_kind"] = "credit"
            return Response(payload, status=status.HTTP_201_CREATED)

        fee_head = get_object_or_404(FeeHead, pk=fee_head_id, is_active=True)

        raw_semester_id = request.data.get("semester_id")
        semester = _resolve_charge_semester(student, request.data)
        if raw_semester_id not in (None, "") and semester is None:
            return Response(
                {
                    "detail": (
                        "Selected academic period is not valid for this student's programme batch. "
                        "Pick a semester from the list, or leave it blank."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            charge = StudentTuitionPayment.objects.create(
                student=student,
                source='ad_hoc',
                fee_head=fee_head,
                label=label[:200],
                amount=amount,
                currency=currency[:3],
                status='pending',
                notes=notes or "",
                charged_by=request.user,
                semester=semester,
            )
        except Exception as exc:
            return Response(
                {"detail": f"Could not create charge: {exc}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        payload = _charge_to_dict(charge)
        payload["entry_kind"] = "charge"
        return Response(payload, status=status.HTTP_201_CREATED)


class StudentAdHocChargeDetailView(APIView):
    """
    GET    /api/payments/admin/charge/<pk>         — retrieve
    PATCH  /api/payments/admin/charge/<pk>         — update
    POST   /api/payments/admin/charge/<pk>/waive   — waive
    DELETE /api/payments/admin/charge/<pk>         — hard delete (pending only)
    """
    permission_classes = [StudentChargesPermission]

    def _get(self, pk):
        return get_object_or_404(
            StudentTuitionPayment.objects.select_related(
                'fee_head', 'charged_by', 'waived_by', 'semester',
                'student', 'student__programme_enrollment', 'student__admitted_program',
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
        if any(
            key in request.data
            for key in ("semester_id", "year_of_study", "term_number")
        ):
            charge.semester = _resolve_charge_semester(charge.student, request.data)

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

    def post(self, request, pk):
        """Settle from existing tuition/SchoolPay credit (Bonafide Finance)."""
        return _apply_existing_credit(request, self._get(pk))


class StudentAdHocChargeWaiveView(APIView):
    """POST /api/payments/admin/charge/<pk>/waive"""
    permission_classes = [StudentChargesPermission]

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


def _apply_existing_credit(request, charge: StudentTuitionPayment):
    import uuid
    from decimal import Decimal

    from payments.credit_allocation import CREDIT_ALLOCATION_TX_PREFIX
    from payments.student_payment_allocation import payment_credits_by_currency
    from payments.utils.tuition_payment_status import mark_tuition_payment_completed

    if charge.is_waived:
        return Response({"detail": "Charge is waived."}, status=status.HTTP_400_BAD_REQUEST)
    if charge.status == "completed":
        return Response({"detail": "Charge is already paid."}, status=status.HTTP_400_BAD_REQUEST)
    if charge.status != "pending":
        return Response(
            {"detail": "Only pending charges can be settled from existing credit."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    reason = str(request.data.get("reason") or "").strip()
    if not reason:
        return Response(
            {"detail": "Reason is required (e.g. student already paid tuition)."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    amount = charge.amount or Decimal("0")
    if amount <= 0:
        return Response({"detail": "Charge amount must be positive."}, status=400)

    student = charge.student
    credits = payment_credits_by_currency(student)
    ccy = (charge.currency or "UGX").strip().upper() or "UGX"
    available = Decimal(str(credits.get(ccy, 0)))
    if available < amount:
        return Response(
            {
                "detail": (
                    f"Not enough {ccy} on the student's SchoolPay/tuition ledger to move "
                    f"{amount:,.0f}. Available credit: {available:,.0f}."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    actor = request.user.get_full_name() or request.user.username
    note_line = (
        f"Applied from existing tuition/SchoolPay credit by {actor}. {reason}"
    ).strip()
    existing = (charge.notes or "").strip()
    charge.notes = f"{existing}\n{note_line}".strip() if existing else note_line
    charge.payment_method = "internal_credit"
    fee_code = (getattr(charge.fee_head, "code", None) or "FEE").upper()
    charge.transaction_id = (
        f"{CREDIT_ALLOCATION_TX_PREFIX}{fee_code[:8]}-{charge.pk}-{uuid.uuid4().hex[:8]}"
    )
    charge.save(update_fields=["notes", "payment_method", "transaction_id", "updated_at"])
    mark_tuition_payment_completed(charge)

    try:
        from admissions.exemption_form_fee_payment import (
            is_exemption_form_fee_charge,
            sync_exemption_form_fee_paid_at,
        )

        if is_exemption_form_fee_charge(charge):
            sync_exemption_form_fee_paid_at(charge)
    except Exception:
        pass

    charge.refresh_from_db()
    return Response(
        {
            "detail": (
                f"UGX {amount:,.0f} applied from existing tuition/SchoolPay credit to "
                f"'{charge.label}'. Tuition coverage is reduced by the same amount."
                if ccy == "UGX"
                else f"{ccy} {amount} applied from existing credit to '{charge.label}'."
            ),
            **_charge_to_dict(charge),
        }
    )


class StudentAdHocChargeApplyCreditView(APIView):
    """POST /api/payments/admin/charge/<pk>/apply_credit"""

    permission_classes = [StudentChargesPermission]

    def post(self, request, pk):
        charge = get_object_or_404(StudentTuitionPayment, pk=pk, source="ad_hoc")
        return _apply_existing_credit(request, charge)


def _semesters_for_split(student: AdmittedStudent, semester_ids: list[int]) -> list[Semester]:
    program_batch_id = _student_program_batch_id(student)
    semesters = list(
        Semester.objects.filter(pk__in=semester_ids, is_active=True).order_by(
            "year_of_study", "term_number", "order", "id"
        )
    )
    if program_batch_id:
        semesters = [s for s in semesters if s.program_batch_id == program_batch_id]
    return semesters


def _create_split_adhoc_charges(
    *,
    student: AdmittedStudent,
    fee_head: FeeHead,
    label_base: str,
    amount,
    currency: str,
    notes: str,
    semesters: list[Semester],
    charged_by,
) -> list[dict]:
    """Split one amount equally across semesters into pending ad-hoc charges."""
    from decimal import Decimal, ROUND_HALF_UP

    amount = Decimal(str(amount))
    n = len(semesters)
    if n < 1:
        raise ValueError("At least one semester is required.")
    if amount <= 0:
        raise ValueError("Amount must be positive.")

    per = (amount / Decimal(n)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    allocated = Decimal("0.00")
    created = []
    for idx, semester in enumerate(semesters):
        part = per if idx < n - 1 else (amount - allocated)
        allocated += part
        charge = StudentTuitionPayment.objects.create(
            student=student,
            source="ad_hoc",
            fee_head=fee_head,
            label=(f"{label_base} · {_semester_label(semester)}" if n > 1 else label_base)[:200],
            amount=part,
            currency=currency[:3] if currency else "UGX",
            status="pending",
            notes=(
                f"{notes} Split {idx + 1}/{n}."
                if notes
                else f"Manual ad-hoc charge; split {idx + 1}/{n}."
            )[:2000],
            charged_by=charged_by,
            semester=semester,
        )
        created.append(_charge_to_dict(charge))
    return created


class StudentBulkChargesCreateView(APIView):
    """
    POST /api/payments/admin/student/<student_id>/bulk_charges

    General manual billing (tuition top-ups, international differentials, etc.).

    Body:
      lines: [{ fee_head_id, label, amount, currency?, notes? }]
      semester_ids: [int, ...]  — each line amount split equally across these
    """

    permission_classes = [StudentChargesPermission]

    def post(self, request, student_id):
        student = get_object_or_404(
            AdmittedStudent.objects.select_related(
                "admitted_program",
                "programme_enrollment",
                "programme_enrollment__program_batch",
            ),
            pk=student_id,
        )

        lines = request.data.get("lines") or []
        semester_ids = request.data.get("semester_ids") or []

        if not lines:
            return Response(
                {"detail": "lines with fee_head_id, label, and amount are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not semester_ids:
            return Response(
                {"detail": "Select at least one semester to bill against."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            semester_ids = [int(x) for x in semester_ids]
        except (TypeError, ValueError):
            return Response(
                {"detail": "semester_ids must be integers."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        semesters = _semesters_for_split(student, semester_ids)
        if not semesters:
            return Response(
                {"detail": "No valid semesters found for this student."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        created = []
        for raw in lines:
            fee_head_id = raw.get("fee_head_id")
            label = (raw.get("label") or "").strip()
            if not fee_head_id:
                return Response(
                    {"detail": "Each line needs fee_head_id."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not label:
                return Response(
                    {"detail": "Each line needs a label."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            try:
                fee_head = FeeHead.objects.get(pk=fee_head_id, is_active=True)
            except FeeHead.DoesNotExist:
                return Response(
                    {"detail": f"Fee head {fee_head_id} not found."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            currency = (raw.get("currency") or "UGX").strip().upper() or "UGX"
            notes = (raw.get("notes") or "").strip()
            try:
                created.extend(
                    _create_split_adhoc_charges(
                        student=student,
                        fee_head=fee_head,
                        label_base=label,
                        amount=raw.get("amount"),
                        currency=currency,
                        notes=notes,
                        semesters=semesters,
                        charged_by=request.user,
                    )
                )
            except ValueError as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "detail": f"Created {len(created)} charge(s).",
                "charges": created,
            },
            status=status.HTTP_201_CREATED,
        )


class StudentExemptionChargesCreateView(APIView):
    """
    POST /api/payments/admin/student/<student_id>/exemption_charges

    Body:
      change_request_id: int
      lines: [
        { line_kind?: "exemption"|"remaining_tuition",
          curriculum_line_id?, course_code?, course_name?,
          year_of_study?, term_number?, semester_id?, amount? }
      ]
      semester_ids: [int, ...]  — EXEMPTION_COURSE total spread across these
      replace_pending: bool — delete pending charges for this change request

    Exempted papers → EXEMPTION_COURSE (flat alumnus/external fee), spread.
    Remaining tuition → EXEMPT_REMAIN_TUIT one charge per remaining paper:
      semester tuition ÷ 6 — posted by Accounts.
    """

    permission_classes = [StudentChargesPermission]

    def post(self, request, student_id):
        from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
        import logging

        from admissions.exemption_services import (
            EXEMPTION_COURSE_FEE_CODE,
            EXEMPTION_REMAINING_TUITION_CODE,
            ensure_exemption_fee_heads,
            ensure_exemption_remaining_tuition_fee_head,
            exemption_billing_lines_for_request,
            exemption_course_fee_for_paper,
            exemption_remaining_curriculum_lines_for_request,
        )
        from admissions.models import AdmissionChangeRequest, ExemptionRequestLine
        from django.db import DataError, DatabaseError, IntegrityError, transaction

        logger = logging.getLogger(__name__)

        def _text(value, default: str = "") -> str:
            if value is None:
                return default
            return str(value).strip() or default

        def _safe_int(value):
            if value in (None, ""):
                return None
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        student = get_object_or_404(
            AdmittedStudent.objects.select_related(
                "admitted_program",
                "programme_enrollment",
                "programme_enrollment__program_batch",
            ),
            pk=student_id,
        )

        change_request_id = request.data.get("change_request_id")
        lines = request.data.get("lines") or []
        semester_ids = request.data.get("semester_ids") or []
        replace_pending = bool(request.data.get("replace_pending"))

        if not change_request_id:
            return Response(
                {"detail": "change_request_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        req = get_object_or_404(
            AdmissionChangeRequest.objects.prefetch_related(
                "exemption_lines__curriculum_line"
            ),
            pk=change_request_id,
            admitted_student=student,
            change_type="exemption",
        )
        if req.hod_status != "approved":
            return Response(
                {
                    "detail": (
                        "Exemption request must be HOD-approved before billing. "
                        "Dean/AR confirmation can continue in parallel."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        def _is_remaining_kind(raw: dict) -> bool:
            kind = str(raw.get("line_kind") or "").strip().lower()
            return kind in ("remaining", "remaining_tuition", "remaining_papers")

        if not isinstance(lines, list):
            lines = []

        has_remaining_kind = any(
            isinstance(r, dict) and _is_remaining_kind(r) for r in lines
        )
        exemption_raw = [
            r for r in lines if isinstance(r, dict) and not _is_remaining_kind(r)
        ]
        remaining_raw = [
            r for r in lines if isinstance(r, dict) and _is_remaining_kind(r)
        ]
        # Older clients only send exempted papers — still bill remaining tuition.
        if not has_remaining_kind:
            remaining_raw = exemption_remaining_curriculum_lines_for_request(req)

        if not exemption_raw and not remaining_raw:
            exemption_raw = [
                {
                    "curriculum_line_id": r.get("curriculum_line_id"),
                    "course_code": r.get("course_code"),
                    "course_name": r.get("course_name"),
                    "year_of_study": r.get("year_of_study"),
                    "term_number": r.get("term_number"),
                    "amount": r.get("amount"),
                    "exemption_line_id": r.get("exemption_line_id"),
                    "line_kind": "exemption",
                }
                for r in exemption_billing_lines_for_request(req)
            ]
            remaining_raw = exemption_remaining_curriculum_lines_for_request(req)

        try:
            semester_ids = [int(x) for x in (semester_ids or [])]
        except (TypeError, ValueError):
            return Response(
                {"detail": "semester_ids must be integers."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        preview_by_key: dict[str, dict] = {}
        for row in exemption_billing_lines_for_request(req):
            key = str(row.get("curriculum_line_id") or row.get("course_code") or "")
            preview_by_key[key] = row
            if row.get("exemption_line_id"):
                preview_by_key[f"line:{row['exemption_line_id']}"] = row

        paper_total = Decimal("0.00")
        paper_count = 0
        paper_labels: list[str] = []

        for raw in exemption_raw:
            code = _text(raw.get("course_code"))
            name = _text(raw.get("course_name"))
            line_id = _safe_int(raw.get("curriculum_line_id"))
            exemption_line_id = _safe_int(raw.get("exemption_line_id"))
            year = raw.get("year_of_study")
            term = raw.get("term_number")

            match = None
            if exemption_line_id is not None:
                match = next(
                    (
                        el
                        for el in req.exemption_lines.all()
                        if el.id == exemption_line_id
                    ),
                    None,
                )
            elif line_id is not None:
                match = next(
                    (
                        el
                        for el in req.exemption_lines.all()
                        if el.curriculum_line_id == line_id
                    ),
                    None,
                )
            if match:
                code = code or _text(match.course_code)
                name = name or _text(match.course_name)
                if year in (None, ""):
                    year = match.year_of_study
                if term in (None, ""):
                    term = match.term_number
                if (
                    (year in (None, "") or term in (None, ""))
                    and match.curriculum_line_id
                    and match.curriculum_line
                ):
                    year = match.curriculum_line.year_of_study
                    term = match.curriculum_line.term_number
                if match.decision == ExemptionRequestLine.DECISION_REJECTED:
                    continue

            preview = None
            if exemption_line_id is not None:
                preview = preview_by_key.get(f"line:{exemption_line_id}")
            if preview is None and line_id is not None:
                preview = preview_by_key.get(str(line_id))
            if preview is None and code:
                preview = preview_by_key.get(code)

            if year in (None, "") and preview:
                year = preview.get("year_of_study")
            if term in (None, "") and preview:
                term = preview.get("term_number")

            raw_amount = raw.get("amount")
            try:
                if raw_amount in (None, ""):
                    if preview and preview.get("amount") is not None:
                        amount = Decimal(str(preview["amount"]))
                    else:
                        if year in (None, "") or term in (None, ""):
                            return Response(
                                {
                                    "detail": (
                                        f"Paper {code or 'unit'} needs year/term "
                                        "to compute the exemption fee."
                                    )
                                },
                                status=status.HTTP_400_BAD_REQUEST,
                            )
                        amount = exemption_course_fee_for_paper(
                            student,
                            year_of_study=int(year) if year not in (None, "") else None,
                            term_number=int(term) if term not in (None, "") else None,
                            change_request=req,
                        )
                else:
                    amount = Decimal(str(raw_amount)).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
            except (TypeError, ValueError, InvalidOperation) as exc:
                return Response(
                    {"detail": f"Invalid amount for {code or 'unit'}: {exc}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if amount <= 0:
                continue

            paper_total += amount
            paper_count += 1
            label = code or "unit"
            if name:
                label = f"{label} ({name})"
            paper_labels.append(label)

        program_batch_id = _student_program_batch_id(student)

        def _resolve_semester_for_remaining(raw: dict) -> Semester | None:
            sid = raw.get("semester_id")
            if sid not in (None, ""):
                try:
                    sem = Semester.objects.filter(pk=int(sid), is_active=True).first()
                    if sem and (not program_batch_id or sem.program_batch_id == program_batch_id):
                        return sem
                except (TypeError, ValueError):
                    pass
            try:
                y = int(raw.get("year_of_study") or 0)
                t = int(raw.get("term_number") or 0)
            except (TypeError, ValueError):
                return None
            if y < 1 or t < 1 or not program_batch_id:
                return None
            return (
                Semester.objects.filter(
                    program_batch_id=program_batch_id,
                    year_of_study=y,
                    term_number=t,
                    is_active=True,
                )
                .order_by("order", "id")
                .first()
            )

        remaining_resolved: list[tuple[dict, Semester, Decimal]] = []
        for raw in remaining_raw:
            code = _text(
                raw.get("course_code") or raw.get("paper_code"),
                default="Remaining",
            )
            raw_amount = raw.get("amount")
            try:
                if raw_amount in (None, ""):
                    continue
                amount = Decimal(str(raw_amount)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
            except (TypeError, ValueError, InvalidOperation) as exc:
                return Response(
                    {"detail": f"Invalid remaining tuition amount for {code}: {exc}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if amount <= 0:
                continue
            sem = _resolve_semester_for_remaining(raw)
            if sem is None:
                return Response(
                    {
                        "detail": (
                            f"Could not resolve semester for remaining tuition "
                            f"({code}). Set year/term or semester_id."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            remaining_resolved.append((raw, sem, amount))

        if paper_count < 1 and not remaining_resolved:
            return Response(
                {"detail": "No billable exemption or remaining-tuition amounts."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        semesters: list[Semester] = []
        if paper_count > 0:
            if not semester_ids:
                return Response(
                    {
                        "detail": (
                            "Select at least one semester to spread the "
                            "exemption total across."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            semesters = _semesters_for_split(student, semester_ids)
            if not semesters:
                return Response(
                    {"detail": "No valid semesters found for this student."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        try:
            _, course_head = ensure_exemption_fee_heads()
            remaining_head = (
                ensure_exemption_remaining_tuition_fee_head()
                if remaining_resolved
                else None
            )
        except (DataError, IntegrityError, ValueError) as exc:
            logger.exception("Exemption fee-head setup failed for student %s", student_id)
            return Response(
                {"detail": f"Could not prepare exemption fee heads: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        note_marker = f"Exemption change request #{req.id}"

        created = []
        deleted_count = 0
        promotion_applied = False
        try:
            with transaction.atomic():
                if replace_pending:
                    head_ids = [course_head.id]
                    if remaining_head is not None:
                        head_ids.append(remaining_head.id)
                    doomed = StudentTuitionPayment.objects.filter(
                        student=student,
                        source="ad_hoc",
                        status="pending",
                        is_waived=False,
                        fee_head_id__in=head_ids,
                        notes__icontains=note_marker,
                    )
                    deleted_count = doomed.count()
                    doomed.delete()

                if paper_count > 0 and paper_total > 0:
                    label_base = f"Course exemption fees ({paper_count} paper(s))"
                    notes = (
                        f"{note_marker}; fee head {EXEMPTION_COURSE_FEE_CODE}; "
                        f"total UGX {paper_total} = sum of per-paper exemption fees; "
                        f"spread across {len(semesters)} semester(s). "
                        f"Papers: {', '.join(paper_labels[:20])}"
                        + ("…" if len(paper_labels) > 20 else "")
                    )[:2000]
                    created.extend(
                        _create_split_adhoc_charges(
                            student=student,
                            fee_head=course_head,
                            label_base=label_base,
                            amount=paper_total,
                            currency="UGX",
                            notes=notes,
                            semesters=semesters,
                            charged_by=request.user,
                        )
                    )

                for raw, sem, amount in remaining_resolved:
                    if remaining_head is None:
                        raise ValueError(
                            "Remaining tuition fee head is missing — cannot bill remaining papers."
                        )
                    code = _text(
                        raw.get("course_code") or raw.get("paper_code"),
                        default="Remaining",
                    )
                    name = _text(raw.get("course_name") or raw.get("paper_name"))
                    label = (
                        _text(raw.get("label"))
                        or (
                            f"Remaining tuition — {name}"
                            if name
                            else f"Remaining tuition — {code}"
                        )
                    )[:200]
                    notes = (
                        f"{note_marker}; fee head {EXEMPTION_REMAINING_TUITION_CODE}; "
                        f"remaining_tuition; papers={code}; "
                        f"{_text(raw.get('notes') or raw.get('note'))}"
                    ).strip()[:2000]
                    charge = StudentTuitionPayment.objects.create(
                        student=student,
                        source="ad_hoc",
                        fee_head=remaining_head,
                        label=label,
                        amount=amount,
                        currency="UGX",
                        status="pending",
                        notes=notes,
                        charged_by=request.user if request.user.is_authenticated else None,
                        semester=sem,
                    )
                    created.append(_charge_to_dict(charge))

                from django.utils import timezone
                from admissions.exemption_services import apply_stored_exemption_promotion

                req.accounts_status = "billed"
                req.accounts_reviewed_by = request.user
                req.accounts_reviewed_at = timezone.now()
                req.save(
                    update_fields=[
                        "accounts_status",
                        "accounts_reviewed_by",
                        "accounts_reviewed_at",
                    ]
                )
                # Cutover: move SPE to confirmed year/term so new tuition structure opens
                # only after exemption charges exist.
                try:
                    promotion_applied = apply_stored_exemption_promotion(
                        req, decided_by=request.user
                    )
                except ValueError as promo_exc:
                    raise ValueError(
                        f"Exemption charges were prepared but promotion failed: {promo_exc}"
                    ) from promo_exc
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except (DataError, IntegrityError, DatabaseError) as exc:
            logger.exception(
                "Exemption charge create failed for student %s request %s",
                student_id,
                change_request_id,
            )
            return Response(
                {"detail": f"Could not create exemption charges: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception as exc:
            logger.exception(
                "Unexpected exemption charge failure for student %s request %s",
                student_id,
                change_request_id,
            )
            return Response(
                {
                    "detail": (
                        f"Could not create exemption charges "
                        f"({exc.__class__.__name__}: {exc})."
                    )
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        parts = []
        if paper_count > 0:
            parts.append(
                f"exemption UGX {paper_total:,.2f} across {len(semesters)} semester(s) "
                f"({paper_count} paper(s))"
            )
        if remaining_resolved:
            rem_total = sum((a for _, _, a in remaining_resolved), Decimal("0.00"))
            parts.append(
                f"remaining tuition UGX {rem_total:,.2f} "
                f"({len(remaining_resolved)} paper(s))"
            )
        detail = "Posted " + "; ".join(parts) + "."
        if deleted_count:
            detail = f"Removed {deleted_count} pending charge(s). {detail}"
        if promotion_applied:
            detail += (
                f" Student promoted to Year {req.exemption_promotion_year} "
                f"Term {req.exemption_promotion_term} (new fee structure now applies)."
            )
        return Response(
            {
                "detail": detail,
                "change_request_id": req.id,
                "paper_count": paper_count,
                "total_amount": float(paper_total),
                "remaining_count": len(remaining_resolved),
                "remaining_total": float(
                    sum((a for _, _, a in remaining_resolved), Decimal("0.00"))
                ),
                "deleted_pending": deleted_count,
                "promotion_applied": promotion_applied,
                "charges": created,
            },
            status=status.HTTP_201_CREATED,
        )



def _is_manual_account_credit(payment: StudentTuitionPayment) -> bool:
    tid = (payment.transaction_id or "").strip()
    pref = (payment.payment_reference or "").strip()
    receipt = (payment.receipt_number or "").strip()
    return (
        tid.startswith("MANUAL-CREDIT")
        or pref.startswith("MANUAL-CREDIT")
        or receipt.startswith("MANUAL-CREDIT")
    )


class ManualAccountCreditDeleteView(APIView):
    """
    DELETE /api/payments/admin/account-credit/<pk>/

    Super Admin only — reverse an Accounts MANUAL-CREDIT row from Bonafide Finance.
    """

    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        from accounts.super_admin import user_is_super_admin

        if not user_is_super_admin(request.user):
            return Response(
                {"detail": "Only Super Admin can delete Accounts manual credits."},
                status=status.HTTP_403_FORBIDDEN,
            )

        reason = str(
            (request.data or {}).get("reason")
            or request.query_params.get("reason")
            or ""
        ).strip()
        if len(reason) < 5:
            return Response(
                {"detail": "A reason is required (at least 5 characters) to remove an Accounts credit."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        payment = get_object_or_404(
            StudentTuitionPayment.objects.select_related("student", "charged_by"),
            pk=pk,
        )
        if not _is_manual_account_credit(payment):
            return Response(
                {
                    "detail": (
                        "This is not an Accounts manual credit. "
                        "Bank payments use the bank-payment tools; "
                        "SchoolPay rows cannot be deleted here."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if payment.is_waived:
            return Response(
                {"detail": "This Accounts credit was already removed."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        label = (payment.label or payment.transaction_id or f"#{payment.pk}").strip()
        amount = float(payment.amount or 0)
        poster = ""
        if payment.charged_by_id:
            poster = (
                payment.charged_by.get_full_name() or payment.charged_by.username or ""
            ).strip()

        # Soft-remove so poster + Super Admin reason remain auditable.
        actor_name = request.user.get_full_name() or request.user.username
        prior_notes = (payment.notes or "").strip()
        payment.is_waived = True
        payment.waived_by = request.user
        payment.waived_at = timezone.now()
        payment.notes = (
            f"{prior_notes}\n\n[REMOVED by Super Admin {actor_name}] "
            f"{timezone.now().isoformat()} — Reason: {reason}"
        ).strip()
        payment.save(
            update_fields=[
                "is_waived",
                "waived_by",
                "waived_at",
                "notes",
                "updated_at",
            ]
        )

        return Response(
            {
                "detail": (
                    f"Account credit '{label}' ({amount:,.0f}) removed from paid totals"
                    + (f" (was posted by {poster})" if poster else "")
                    + "."
                ),
                "deleted_id": payment.pk,
                "deleted_amount": amount,
                "posted_by": poster or None,
                "reason": reason,
                "deleted_by": actor_name,
                "soft_deleted": True,
            },
            status=status.HTTP_200_OK,
        )
