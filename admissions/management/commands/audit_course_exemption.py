"""
Audit a course-exemption request after Accounts billing / promotion.

Usage:
  python manage.py audit_course_exemption --schoolpay-code 1012203813
  python manage.py audit_course_exemption --student-id 1012203813
  python manage.py audit_course_exemption --pk 4627
  python manage.py audit_course_exemption --request-id 490
  python manage.py audit_course_exemption --recent 5
"""
from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q, Sum

from admissions.exemption_services import (
    EXEMPTION_COURSE_FEE_CODE,
    EXEMPTION_FORM_FEE_CODE,
    EXEMPTION_REMAINING_TUITION_CODE,
    exemption_effects_applied,
    exemption_promotion_applied,
    exemption_promotion_pending_accounts,
    exemption_promotion_proposed,
    student_has_paid_exemption_form_fee,
)
from admissions.models import AdmissionChangeRequest, AdmittedStudent, ExemptionRequestLine
from payments.models import StudentTuitionPayment


def _find_student(*, schoolpay_code="", student_id="", pk=None, reg_no=""):
    qs = AdmittedStudent.objects.select_related(
        "application",
        "admitted_program",
        "programme_enrollment",
        "programme_enrollment__program_batch",
    )
    if pk:
        return qs.filter(pk=pk).first()
    if schoolpay_code:
        code = schoolpay_code.strip()
        return qs.filter(Q(schoolpay_code=code) | Q(student_id=code)).first()
    if student_id:
        return qs.filter(student_id__iexact=student_id.strip()).first()
    if reg_no:
        return qs.filter(reg_no__iexact=reg_no.strip()).first()
    return None


def _money(n) -> str:
    try:
        return f"UGX {Decimal(str(n)):,.2f}"
    except Exception:
        return str(n)


class Command(BaseCommand):
    help = "Audit course-exemption pipeline: stages, charges, SPE promotion, overrides."

    def add_arguments(self, parser):
        parser.add_argument("--schoolpay-code", default="")
        parser.add_argument("--student-id", default="")
        parser.add_argument("--reg-no", default="")
        parser.add_argument("--pk", type=int, default=None)
        parser.add_argument("--request-id", type=int, default=None)
        parser.add_argument(
            "--recent",
            type=int,
            default=0,
            help="Audit the N most recently Accounts-touched exemption requests.",
        )

    def handle(self, *args, **options):
        request_id = options.get("request_id")
        recent = int(options.get("recent") or 0)

        if request_id:
            reqs = list(
                AdmissionChangeRequest.objects.filter(
                    pk=request_id, change_type="exemption"
                ).select_related(
                    "admitted_student",
                    "admitted_student__programme_enrollment",
                )
            )
            if not reqs:
                raise CommandError(f"Exemption request #{request_id} not found.")
        elif recent > 0:
            reqs = list(
                AdmissionChangeRequest.objects.filter(change_type="exemption")
                .exclude(accounts_status="pending")
                .select_related(
                    "admitted_student",
                    "admitted_student__programme_enrollment",
                )
                .order_by("-accounts_reviewed_at", "-id")[:recent]
            )
            if not reqs:
                reqs = list(
                    AdmissionChangeRequest.objects.filter(change_type="exemption")
                    .select_related(
                        "admitted_student",
                        "admitted_student__programme_enrollment",
                    )
                    .order_by("-updated_at", "-id")[:recent]
                )
            if not reqs:
                raise CommandError("No exemption requests found.")
        else:
            student = _find_student(
                schoolpay_code=options.get("schoolpay_code") or "",
                student_id=options.get("student_id") or "",
                pk=options.get("pk"),
                reg_no=options.get("reg_no") or "",
            )
            if student is None:
                raise CommandError(
                    "Provide --schoolpay-code / --student-id / --pk / --reg-no "
                    "or --request-id / --recent."
                )
            reqs = list(
                AdmissionChangeRequest.objects.filter(
                    admitted_student=student, change_type="exemption"
                )
                .select_related("admitted_student__programme_enrollment")
                .order_by("-id")
            )
            if not reqs:
                raise CommandError(
                    f"No exemption requests for {student.full_name} "
                    f"({student.student_id})."
                )

        for req in reqs:
            self._audit_one(req)

    def _audit_one(self, req: AdmissionChangeRequest) -> None:
        from Programs.models import StudentCurriculumOverride

        w = self.stdout.write
        s = req.admitted_student
        pe = getattr(s, "programme_enrollment", None)
        findings: list[tuple[str, str]] = []  # (PASS|WARN|FAIL, message)

        w("")
        w("=" * 78)
        w(
            f"CR #{req.id}  |  {s.full_name}  |  student_id={s.student_id}  "
            f"pk={s.pk}  reg={s.reg_no}"
        )
        w(
            f"Programme: {getattr(s.admitted_program, 'name', '—')}  "
            f"SchoolPay: {s.schoolpay_code or s.student_id}"
        )
        w("=" * 78)

        w("\n--- Pipeline ---")
        w(
            f"  overall={req.status}  hod={req.hod_status}  dean={req.dean_status}  "
            f"ar={req.ar_status}  accounts={req.accounts_status}"
        )
        w(f"  accounts_reviewed_at={req.accounts_reviewed_at}")
        w(f"  form_fee_paid_at={req.form_fee_paid_at}  "
          f"student_form_fee_counts={student_has_paid_exemption_form_fee(s)}")

        if req.hod_status != "approved":
            findings.append(("FAIL", "HOD has not approved — billing/promotion invalid."))
        elif req.accounts_status in ("billed", "confirmed"):
            findings.append(("PASS", f"Accounts status is {req.accounts_status}."))
        elif req.accounts_status == "pending":
            findings.append(("WARN", "Accounts still pending (not marked billed)."))
        else:
            findings.append(("WARN", f"Unexpected accounts_status={req.accounts_status}."))

        lines = list(req.exemption_lines.all())
        hod_ok = [
            l for l in lines if l.decision == ExemptionRequestLine.DECISION_APPROVED
        ]
        hod_rej = [
            l for l in lines if l.decision == ExemptionRequestLine.DECISION_REJECTED
        ]
        w(f"\n--- Papers ({len(lines)}) — HOD approved {len(hod_ok)}, rejected {len(hod_rej)} ---")
        for l in lines:
            miss = "  << MISSING SCORE" if not (l.score_obtained or "").strip() else ""
            w(
                f"  {l.course_code:<12} Y{l.year_of_study}T{l.term_number}  "
                f"score={l.score_obtained or '—'!r:<8}  "
                f"hod={l.decision} dean={l.dean_decision} ar={l.ar_decision}{miss}"
            )
            if l.decision == ExemptionRequestLine.DECISION_APPROVED and not (
                l.score_obtained or ""
            ).strip():
                findings.append(("WARN", f"{l.course_code} approved with blank score."))

        if not hod_ok:
            findings.append(("FAIL", "No HOD-approved papers."))

        w("\n--- Promotion ---")
        proposed = exemption_promotion_proposed(req)
        pending_acc = exemption_promotion_pending_accounts(req)
        applied = exemption_promotion_applied(req)
        w(f"  proposed={proposed}  pending_accounts_billing={pending_acc}  applied={applied}")
        w(
            f"  target Y{req.exemption_promotion_year}T{req.exemption_promotion_term}  "
            f"from Y{req.exemption_promotion_from_year}T{req.exemption_promotion_from_term}  "
            f"at={req.exemption_promotion_at}"
        )
        if pe:
            w(
                f"  SPE now: Y{pe.current_year_of_study}T{pe.current_term_number}  "
                f"entry Y{pe.entry_year_of_study}T{pe.entry_term_number}"
            )
            if proposed and applied:
                target = (
                    int(req.exemption_promotion_year),
                    int(req.exemption_promotion_term),
                )
                now = (int(pe.current_year_of_study), int(pe.current_term_number))
                if now == target:
                    findings.append(("PASS", f"SPE matches promotion target Y{target[0]}T{target[1]}."))
                else:
                    findings.append(
                        (
                            "FAIL",
                            f"SPE is Y{now[0]}T{now[1]} but promotion target is "
                            f"Y{target[0]}T{target[1]}.",
                        )
                    )
            elif proposed and pending_acc:
                findings.append(
                    (
                        "WARN",
                        "Promotion confirmed but waiting for Accounts bill — SPE should still be old term.",
                    )
                )
            elif proposed and not applied and req.accounts_status in ("billed", "confirmed"):
                findings.append(
                    (
                        "FAIL",
                        "Accounts billed but SPE has not moved to promotion target.",
                    )
                )
            elif not proposed and req.accounts_status in ("billed", "confirmed"):
                findings.append(
                    (
                        "WARN",
                        "Accounts billed with no promotion target — student stays at current Year/Term.",
                    )
                )
            if applied and req.accounts_status == "pending":
                findings.append(
                    (
                        "FAIL",
                        "SPE already promoted but accounts_status is still pending "
                        "(promotion applied before billing — legacy/manual path).",
                    )
                )
        else:
            findings.append(("FAIL", "No programme enrollment (SPE) — cannot promote."))

        w(f"\n--- AR curriculum effects ---")
        w(f"  exemption_effects_applied_at={req.exemption_effects_applied_at}  "
          f"fn={exemption_effects_applied(req)}")
        overrides = []
        if pe:
            overrides = list(
                StudentCurriculumOverride.objects.filter(
                    enrollment=pe, override_type="exempted"
                ).select_related("curriculum_line__catalog_course")
            )
        w(f"  exempted overrides: {len(overrides)}")
        for o in overrides[:25]:
            code = getattr(
                getattr(o.curriculum_line, "catalog_course", None), "code", None
            )
            w(f"    #{o.id} curriculum_line={o.curriculum_line_id} code={code}")
        if req.ar_status == "approved" and exemption_effects_applied(req):
            if len(overrides) >= len(hod_ok):
                findings.append(("PASS", f"Curriculum overrides present ({len(overrides)})."))
            else:
                findings.append(
                    (
                        "WARN",
                        f"AR effects stamped but only {len(overrides)} overrides vs "
                        f"{len(hod_ok)} HOD-approved papers.",
                    )
                )
        elif req.ar_status == "approved" and not exemption_effects_applied(req):
            findings.append(("WARN", "AR approved but exemption_effects_applied_at is empty."))
        elif req.accounts_status in ("billed", "confirmed") and req.ar_status != "approved":
            findings.append(
                (
                    "WARN",
                    "Accounts billed while AR not yet approved — overrides may be incomplete.",
                )
            )

        note_marker = f"Exemption change request #{req.id}"
        charges = list(
            StudentTuitionPayment.objects.filter(student=s, source="ad_hoc")
            .filter(
                Q(notes__icontains=note_marker)
                | Q(fee_head__code__in=[
                    EXEMPTION_COURSE_FEE_CODE,
                    EXEMPTION_REMAINING_TUITION_CODE,
                    EXEMPTION_FORM_FEE_CODE,
                    "EXEMPTION_REMAINING_TUITION",  # legacy oversize code if any
                ])
            )
            .select_related("fee_head", "semester")
            .order_by("fee_head__code", "id")
        )
        course = [c for c in charges if (c.fee_head and c.fee_head.code) == EXEMPTION_COURSE_FEE_CODE]
        remain = [
            c for c in charges
            if c.fee_head and c.fee_head.code in (
                EXEMPTION_REMAINING_TUITION_CODE,
                "EXEMPTION_REMAINING_TUITION",
            )
        ]
        form = [c for c in charges if (c.fee_head and c.fee_head.code) == EXEMPTION_FORM_FEE_CODE]
        linked = [c for c in charges if note_marker in (c.notes or "")]

        w(f"\n--- Ad-hoc charges linked to CR #{req.id} or exemption fee heads ---")
        w(f"  EXEMPTION_COURSE: {len(course)}  remaining-tuition: {len(remain)}  "
          f"FORM: {len(form)}  notes-linked: {len(linked)}")
        for c in charges:
            code = c.fee_head.code if c.fee_head_id else "—"
            sem = (
                f"Y{c.semester.year_of_study}T{c.semester.term_number}"
                if c.semester_id
                else "—"
            )
            linked_flag = " [CR-linked]" if note_marker in (c.notes or "") else ""
            w(
                f"  #{c.id} {code:<20} {_money(c.amount):<18} {c.status:<10} "
                f"sem={sem:<6} {c.label[:50]}{linked_flag}"
            )

        course_total = sum((c.amount for c in course if c.status != "cancelled"), Decimal("0"))
        remain_total = sum((c.amount for c in remain if c.status != "cancelled"), Decimal("0"))
        w(f"  course total={_money(course_total)}  remaining total={_money(remain_total)}")

        if req.accounts_status in ("billed", "confirmed"):
            if course or remain:
                findings.append(
                    (
                        "PASS",
                        f"Exemption charges exist "
                        f"(course={_money(course_total)}, remaining={_money(remain_total)}).",
                    )
                )
            else:
                findings.append(
                    (
                        "FAIL",
                        "Accounts marked billed but no EXEMPTION_COURSE / remaining-tuition charges found.",
                    )
                )
            if linked:
                findings.append(("PASS", f"{len(linked)} charge(s) note-linked to CR #{req.id}."))
            elif course or remain:
                findings.append(
                    (
                        "WARN",
                        "Charges exist but notes do not mention this change request id "
                        "(harder to replace_pending / audit).",
                    )
                )
        else:
            if course or remain:
                findings.append(
                    (
                        "WARN",
                        "Exemption course/remaining charges exist while accounts_status "
                        f"is {req.accounts_status}.",
                    )
                )

        w("\n--- Verdict ---")
        fails = [m for lvl, m in findings if lvl == "FAIL"]
        warns = [m for lvl, m in findings if lvl == "WARN"]
        passes = [m for lvl, m in findings if lvl == "PASS"]
        for lvl, msg in findings:
            style = {
                "PASS": self.style.SUCCESS,
                "WARN": self.style.WARNING,
                "FAIL": self.style.ERROR,
            }.get(lvl, lambda x: x)
            w(style(f"  [{lvl}] {msg}"))
        w(
            f"\n  Summary: {len(passes)} pass, {len(warns)} warn, {len(fails)} fail"
        )
        if fails:
            w(self.style.ERROR("  RESULT: NEEDS ATTENTION"))
        elif warns:
            w(self.style.WARNING("  RESULT: OK WITH WARNINGS"))
        else:
            w(self.style.SUCCESS("  RESULT: CLEAN"))
