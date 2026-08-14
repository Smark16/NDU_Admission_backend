"""Admin broadcast: portal bell and/or email to students, lecturers, and admins."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from admissions.models import AdmittedStudent, PortalNotification
from ndu_portal.send_grid import send_configurable_email

User = get_user_model()
MAX_EMAIL_SENDS = 2500
AUDIENCES = ("students", "lecturers", "admins", "staff")


def _can_notify(user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    return user.has_perm("accounts.access_user_management") or user.has_perm("accounts.view_user")


def _personalise_text(text: str, *, first="", last="", reg_no="", student_id="") -> str:
    return (
        (text or "")
        .replace("{first_name}", first or "")
        .replace("{last_name}", last or "")
        .replace("{reg_no}", reg_no or "")
        .replace("{student_id}", student_id or "")
    )


def _personalise_student(text: str, student: AdmittedStudent) -> str:
    user = student.student_user
    first = (user.first_name if user else "") or (
        student.application.first_name if student.application_id else ""
    ) or ""
    last = (user.last_name if user else "") or (
        student.application.last_name if student.application_id else ""
    ) or ""
    return _personalise_text(
        text,
        first=first,
        last=last,
        reg_no=student.reg_no or "",
        student_id=student.student_id or "",
    )


def _personalise_user(text: str, user) -> str:
    return _personalise_text(text, first=user.first_name or "", last=user.last_name or "")


def _student_email(student: AdmittedStudent) -> str:
    user = student.student_user
    if user and (user.email or "").strip():
        return user.email.strip()
    if student.application_id and (student.application.email or "").strip():
        return student.application.email.strip()
    return ""


def _academic_batch_options(program_id) -> list[dict]:
    from Programs.models import ProgramBatch

    qs = ProgramBatch.objects.select_related("program").order_by("-start_date", "name")
    if program_id not in (None, "", "all"):
        try:
            qs = qs.filter(program_id=int(program_id))
        except (TypeError, ValueError):
            qs = qs.none()
    rows = []
    for b in qs[:300]:
        prog = getattr(b.program, "short_form", None) or getattr(b.program, "name", "") or ""
        rows.append(
            {
                "id": b.id,
                "name": b.name,
                "academic_year": b.academic_year or "",
                "program": prog,
            }
        )
    return rows


def _filtered_students(params) -> list[AdmittedStudent]:
    qs = (
        AdmittedStudent.objects.filter(student_user__isnull=False)
        .select_related(
            "student_user",
            "application",
            "admitted_program",
            "admitted_campus",
            "admitted_batch",
            "intended_program_batch",
        )
        .order_by("reg_no")
    )
    program_id = params.get("program_id")
    campus_id = params.get("campus_id")
    batch_id = params.get("batch_id") or params.get("intake_id")
    academic_batch_id = params.get("academic_batch_id")
    study_mode = (params.get("study_mode") or "").strip()
    registered = (params.get("registered") or "all").strip().lower()

    if program_id not in (None, "", "all"):
        try:
            qs = qs.filter(admitted_program_id=int(program_id))
        except (TypeError, ValueError):
            qs = qs.none()
    if campus_id not in (None, "", "all"):
        try:
            qs = qs.filter(admitted_campus_id=int(campus_id))
        except (TypeError, ValueError):
            qs = qs.none()
    if batch_id not in (None, "", "all"):
        try:
            qs = qs.filter(admitted_batch_id=int(batch_id))
        except (TypeError, ValueError):
            qs = qs.none()
    if academic_batch_id not in (None, "", "all"):
        try:
            aid = int(academic_batch_id)
            qs = qs.filter(
                Q(intended_program_batch_id=aid) | Q(programme_enrollment__program_batch_id=aid)
            ).distinct()
        except (TypeError, ValueError):
            qs = qs.none()
    if study_mode and study_mode.lower() != "all":
        qs = qs.filter(study_mode__iexact=study_mode)
    if registered == "registered":
        qs = qs.filter(is_registered=True)
    elif registered in ("unregistered", "not_registered"):
        qs = qs.filter(is_registered=False)

    raw_ids = params.get("user_ids")
    if raw_ids is not None:
        if not isinstance(raw_ids, list):
            return []
        try:
            ids = [int(x) for x in raw_ids if int(x) > 0]
        except (TypeError, ValueError):
            return []
        if ids:
            qs = qs.filter(student_user_id__in=ids)

    return list(qs)


def _filtered_staff(params, audience: str) -> list:
    qs = User.objects.filter(is_active=True)
    if audience == "lecturers":
        qs = qs.filter(is_lecturer=True)
    elif audience == "admins":
        qs = qs.filter(is_staff=True)
    else:
        qs = qs.filter(Q(is_staff=True) | Q(is_lecturer=True))
    raw_ids = params.get("user_ids")
    if raw_ids is not None:
        if not isinstance(raw_ids, list):
            return []
        try:
            ids = [int(x) for x in raw_ids if int(x) > 0]
        except (TypeError, ValueError):
            return []
        if ids:
            qs = qs.filter(id__in=ids)
    return list(qs.order_by("last_name", "first_name", "email"))


def _audience(params) -> str:
    a = (params.get("audience") or "students").strip().lower()
    return a if a in AUDIENCES else "students"


def _preview_students(students: list[AdmittedStudent], program_id) -> dict:
    sample = []
    for s in students[:8]:
        u = s.student_user
        sample.append(
            {
                "reg_no": s.reg_no,
                "name": f"{(u.first_name or '')} {(u.last_name or '')}".strip() or u.username,
                "email": _student_email(s) or None,
                "programme": getattr(s.admitted_program, "name", None),
                "intake": getattr(s.admitted_batch, "name", None),
            }
        )
    return {
        "audience": "students",
        "count": len(students),
        "with_email": sum(1 for s in students if _student_email(s)),
        "sample": sample,
        "academic_batches": _academic_batch_options(program_id),
    }


def _preview_staff(users: list, audience: str) -> dict:
    sample = []
    for u in users[:8]:
        sample.append(
            {
                "name": f"{(u.first_name or '')} {(u.last_name or '')}".strip() or u.username,
                "email": (u.email or "").strip() or None,
                "role": "lecturer" if getattr(u, "is_lecturer", False) else "admin",
            }
        )
    return {
        "audience": audience,
        "count": len(users),
        "with_email": sum(1 for u in users if (u.email or "").strip()),
        "sample": sample,
        "academic_batches": [],
    }


def _preview(params) -> dict:
    audience = _audience(params)
    if audience == "students":
        return _preview_students(_filtered_students(params), params.get("program_id"))
    return _preview_staff(_filtered_staff(params, audience), audience)


class StudentNotifyPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _can_notify(request.user):
            return Response({"detail": "You do not have permission to send notifications."}, status=403)
        return Response(_preview(request.query_params))

    def post(self, request):
        if not _can_notify(request.user):
            return Response({"detail": "You do not have permission to send notifications."}, status=403)
        return Response(_preview(request.data))


class StudentNotifySendView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not _can_notify(request.user):
            return Response({"detail": "You do not have permission to send notifications."}, status=403)

        title = (request.data.get("title") or request.data.get("subject") or "").strip()
        message = (request.data.get("message") or request.data.get("body") or "").strip()
        channel = (request.data.get("channel") or "portal").strip().lower()
        test_email = (request.data.get("test_email") or "").strip()
        audience = _audience(request.data)

        if not title or not message:
            return Response({"detail": "Title and message are required."}, status=400)
        if channel not in ("portal", "email", "both"):
            return Response({"detail": "channel must be portal, email, or both."}, status=400)

        if test_email:
            body = _personalise_text(
                message,
                first=request.user.first_name or "Colleague",
                last=request.user.last_name or "",
            )
            note = "\n\n---\n(This is a test. Placeholders used your staff name.)\n"
            if send_configurable_email(test_email, title, body + note):
                return Response({"detail": f"Test email sent to {test_email}."})
            return Response(
                {"detail": "Failed to send test email. Check SendGrid configuration."},
                status=502,
            )

        want_portal = channel in ("portal", "both")
        want_email = channel in ("email", "both")

        recipients: list[tuple] = []
        if audience == "students":
            students = _filtered_students(request.data)
            if not students:
                return Response(
                    {"detail": "No students with portal accounts match these filters."},
                    status=400,
                )
            for s in students:
                recipients.append(
                    (
                        s.student_user,
                        _personalise_student(title, s)[:200],
                        _personalise_student(message, s),
                        _student_email(s),
                    )
                )
        else:
            users = _filtered_staff(request.data, audience)
            if not users:
                return Response({"detail": "No matching staff accounts."}, status=400)
            for u in users:
                recipients.append(
                    (
                        u,
                        _personalise_user(title, u)[:200],
                        _personalise_user(message, u),
                        (u.email or "").strip(),
                    )
                )

        if want_email and len(recipients) > MAX_EMAIL_SENDS:
            return Response(
                {
                    "detail": (
                        f"Too many recipients for email ({len(recipients)}). "
                        f"Narrow the filters or send portal-only (limit {MAX_EMAIL_SENDS} emails)."
                    )
                },
                status=400,
            )

        portal_created = 0
        emailed = 0
        email_failed = 0
        skipped_no_email = 0

        if want_portal:
            rows = [
                PortalNotification(recipient=user, title=ttl, message=msg)
                for user, ttl, msg, _email in recipients
                if user is not None
            ]
            PortalNotification.objects.bulk_create(rows, batch_size=500)
            portal_created = len(rows)

        if want_email:
            for _user, ttl, msg, email in recipients:
                if not email:
                    skipped_no_email += 1
                    continue
                if send_configurable_email(email, ttl, msg):
                    emailed += 1
                else:
                    email_failed += 1

        parts = []
        if want_portal:
            parts.append(f"Portal bell: {portal_created}")
        if want_email:
            parts.append(f"Email sent: {emailed}")
            if skipped_no_email:
                parts.append(f"no email: {skipped_no_email}")
            if email_failed:
                parts.append(f"email failed: {email_failed}")

        return Response(
            {
                "detail": "Sent. " + "; ".join(parts) + ".",
                "count": len(recipients),
                "portal_created": portal_created,
                "emailed": emailed,
                "email_failed": email_failed,
                "skipped_no_email": skipped_no_email,
            }
        )
