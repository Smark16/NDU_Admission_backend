"""Portal messaging API views."""
from __future__ import annotations

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from admissions.models import AdmittedStudent
from admissions.utils.notification import create_notification
from messaging.access import (
    admitted_student_for_user,
    conversations_for_user,
    ensure_student_user,
    faculty_inbox_contacts,
    faculty_inbox_group_names,
    lecturer_can_message_student,
    lecturers_for_student,
    search_admitted_students,
    student_can_message_faculty_staff,
    student_can_message_lecturer,
    user_can_use_staff_inbox,
    user_is_lecturer_portal,
    user_is_student_portal,
)
from messaging.models import Conversation, ConversationParticipant, Message
from messaging.serializers import (
    ConversationDetailSerializer,
    ConversationListSerializer,
    MessageSerializer,
)


def _participant_or_403(user, conversation: Conversation) -> ConversationParticipant | None:
    return conversation.participants.filter(user=user).first()


def _notify_peer(recipient, *, title: str, preview: str) -> None:
    if recipient is None:
        return
    try:
        create_notification(recipient, title, (preview or "")[:500])
    except Exception:
        pass


class ConversationListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = conversations_for_user(request.user).order_by(
            "-last_message_at", "-created_at"
        )
        status_filter = (request.query_params.get("status") or "").strip().lower()
        if status_filter in (Conversation.STATUS_OPEN, Conversation.STATUS_CLOSED):
            qs = qs.filter(status=status_filter)
        data = ConversationListSerializer(
            qs[:100], many=True, context={"request": request}
        ).data
        return Response(data)

    def post(self, request):
        """
        Start a conversation.

        Staff/Admin body: { student_id: int, body: str, subject?: str }
        Lecturer: same, student must be on their course.
        Student body: { lecturer_id | staff_id: int, body: str, subject?: str }
        """
        body = (request.data.get("body") or "").strip()
        if not body:
            return Response({"detail": "Message body is required."}, status=400)
        subject = (request.data.get("subject") or "").strip()[:200]

        try:
            with transaction.atomic():
                if user_is_student_portal(request.user) and not user_can_use_staff_inbox(
                    request.user
                ):
                    conversation = self._student_start(request, body=body, subject=subject)
                else:
                    conversation = self._staff_start(request, body=body, subject=subject)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=403)

        ser = ConversationDetailSerializer(conversation, context={"request": request})
        return Response(ser.data, status=status.HTTP_201_CREATED)

    def _staff_start(self, request, *, body: str, subject: str) -> Conversation:
        try:
            student_pk = int(request.data.get("student_id"))
        except (TypeError, ValueError):
            raise ValueError("student_id is required.")

        student = get_object_or_404(
            AdmittedStudent.objects.select_related("application", "student_user"),
            pk=student_pk,
            is_admitted=True,
        )

        if user_is_lecturer_portal(request.user) and not user_can_use_staff_inbox(
            request.user
        ):
            if not lecturer_can_message_student(request.user, student):
                raise PermissionError(
                    "You can only message students enrolled on your courses."
                )

        student_user = ensure_student_user(student)
        if student_user is None:
            raise ValueError(
                "This student has no portal account yet. Generate their portal login first."
            )

        # Reuse open conversation between this staff user and student if present.
        existing = (
            Conversation.objects.filter(
                student=student,
                status=Conversation.STATUS_OPEN,
                participants__user=request.user,
            )
            .distinct()
            .first()
        )
        if existing:
            conversation = existing
        else:
            conversation = Conversation.objects.create(
                student=student,
                subject=subject,
                created_by=request.user,
                last_message_at=timezone.now(),
            )
            ConversationParticipant.objects.create(
                conversation=conversation,
                user=request.user,
                role=ConversationParticipant.ROLE_STAFF,
                last_read_at=timezone.now(),
            )
            ConversationParticipant.objects.get_or_create(
                conversation=conversation,
                user=student_user,
                defaults={
                    "role": ConversationParticipant.ROLE_STUDENT,
                },
            )

        if subject and not conversation.subject:
            conversation.subject = subject
            conversation.save(update_fields=["subject", "updated_at"])

        msg = Message.objects.create(
            conversation=conversation, sender=request.user, body=body
        )
        conversation.last_message_at = msg.created_at
        conversation.save(update_fields=["last_message_at", "updated_at"])
        ConversationParticipant.objects.filter(
            conversation=conversation, user=request.user
        ).update(last_read_at=timezone.now())

        _notify_peer(
            student_user,
            title="New message from staff",
            preview=body,
        )
        return conversation

    def _student_start(self, request, *, body: str, subject: str) -> Conversation:
        from accounts.models import User

        raw_lecturer = request.data.get("lecturer_id")
        raw_staff = request.data.get("staff_id")
        peer = None
        peer_kind = "lecturer"

        if raw_staff not in (None, ""):
            try:
                peer = get_object_or_404(User, pk=int(raw_staff))
            except (TypeError, ValueError):
                raise ValueError("staff_id must be an integer.")
            peer_kind = "faculty"
        elif raw_lecturer not in (None, ""):
            try:
                peer = get_object_or_404(User, pk=int(raw_lecturer))
            except (TypeError, ValueError):
                raise ValueError("lecturer_id must be an integer.")
        else:
            raise ValueError("lecturer_id or staff_id is required.")

        admitted = admitted_student_for_user(request.user)
        if admitted is None:
            raise ValueError("No admitted student record is linked to your account.")

        if peer_kind == "faculty":
            if not student_can_message_faculty_staff(request.user, peer):
                raise PermissionError(
                    "You can only message Faculty / Registry contacts."
                )
        elif not student_can_message_lecturer(request.user, peer):
            raise PermissionError(
                "You can only message lecturers of courses you are enrolled on."
            )

        existing = (
            Conversation.objects.filter(
                student=admitted,
                status=Conversation.STATUS_OPEN,
                participants__user=peer,
            )
            .distinct()
            .first()
        )
        if existing:
            conversation = existing
        else:
            conversation = Conversation.objects.create(
                student=admitted,
                subject=subject,
                created_by=request.user,
                last_message_at=timezone.now(),
            )
            ConversationParticipant.objects.create(
                conversation=conversation,
                user=request.user,
                role=ConversationParticipant.ROLE_STUDENT,
                last_read_at=timezone.now(),
            )
            ConversationParticipant.objects.create(
                conversation=conversation,
                user=peer,
                role=ConversationParticipant.ROLE_STAFF,
            )

        msg = Message.objects.create(
            conversation=conversation, sender=request.user, body=body
        )
        conversation.last_message_at = msg.created_at
        if subject and not conversation.subject:
            conversation.subject = subject
        conversation.save(update_fields=["last_message_at", "subject", "updated_at"])
        _notify_peer(peer, title="New message from a student", preview=body)
        return conversation


class ConversationDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        conversation = get_object_or_404(
            conversations_for_user(request.user), pk=pk
        )
        after = request.query_params.get("after")
        ctx = {"request": request}
        if after:
            try:
                ctx["after_id"] = int(after)
            except (TypeError, ValueError):
                pass
        return Response(
            ConversationDetailSerializer(conversation, context=ctx).data
        )


class ConversationMessagesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        conversation = get_object_or_404(
            conversations_for_user(request.user), pk=pk
        )
        after = request.query_params.get("after")
        qs = conversation.messages.select_related("sender").order_by("created_at")
        if after:
            try:
                qs = qs.filter(id__gt=int(after))
            except (TypeError, ValueError):
                pass
        return Response(MessageSerializer(qs, many=True).data)

    def post(self, request, pk):
        conversation = get_object_or_404(
            conversations_for_user(request.user), pk=pk
        )
        part = _participant_or_403(request.user, conversation)
        if part is None:
            return Response({"detail": "Not a participant."}, status=403)
        if conversation.status == Conversation.STATUS_CLOSED:
            return Response(
                {"detail": "This conversation is closed."}, status=400
            )
        body = (request.data.get("body") or "").strip()
        if not body:
            return Response({"detail": "Message body is required."}, status=400)

        msg = Message.objects.create(
            conversation=conversation, sender=request.user, body=body
        )
        conversation.last_message_at = msg.created_at
        conversation.save(update_fields=["last_message_at", "updated_at"])
        part.last_read_at = timezone.now()
        part.save(update_fields=["last_read_at"])

        for peer in conversation.participants.exclude(user=request.user):
            _notify_peer(
                peer.user,
                title="New portal message",
                preview=body,
            )

        return Response(MessageSerializer(msg).data, status=status.HTTP_201_CREATED)


class ConversationReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        conversation = get_object_or_404(
            conversations_for_user(request.user), pk=pk
        )
        part = _participant_or_403(request.user, conversation)
        if part is None:
            return Response({"detail": "Not a participant."}, status=403)
        part.last_read_at = timezone.now()
        part.save(update_fields=["last_read_at"])
        return Response({"ok": True, "last_read_at": part.last_read_at})


class ConversationCloseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        conversation = get_object_or_404(
            conversations_for_user(request.user), pk=pk
        )
        if user_is_student_portal(request.user) and not user_can_use_staff_inbox(
            request.user
        ):
            return Response(
                {"detail": "Only staff can close conversations."}, status=403
            )
        conversation.status = Conversation.STATUS_CLOSED
        conversation.save(update_fields=["status", "updated_at"])
        return Response({"ok": True, "status": conversation.status})


class UnreadCountView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from messaging.models import ConversationParticipant as CP

        parts = CP.objects.filter(user=request.user).select_related("conversation")
        total = 0
        for part in parts:
            qs = part.conversation.messages.exclude(sender=request.user)
            if part.last_read_at:
                qs = qs.filter(created_at__gt=part.last_read_at)
            total += qs.count()
        return Response({"unread_count": total})


class StudentSearchView(APIView):
    """Staff / lecturer: search admitted students to start a chat."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if user_is_student_portal(request.user) and not user_can_use_staff_inbox(
            request.user
        ):
            return Response({"detail": "Not allowed."}, status=403)

        q = request.query_params.get("q") or request.query_params.get("search") or ""
        rows = search_admitted_students(q, limit=25)

        if user_is_lecturer_portal(request.user) and not user_can_use_staff_inbox(
            request.user
        ):
            allowed_ids = set(
                AdmittedStudent.objects.filter(
                    course_unit_enrollments__status="enrolled",
                    course_unit_enrollments__course_unit__is_active=True,
                    course_unit_enrollments__course_unit__lecturers=request.user,
                ).values_list("pk", flat=True)
            )
            rows = [s for s in rows if s.pk in allowed_ids]

        out = []
        for s in rows:
            try:
                name = s.application.full_name
            except Exception:
                name = s.reg_no
            out.append(
                {
                    "id": s.id,
                    "name": name,
                    "reg_no": s.reg_no,
                    "student_id": s.student_id,
                    "programme": (
                        s.admitted_program.name if s.admitted_program_id else None
                    ),
                    "has_portal_user": bool(s.student_user_id),
                }
            )
        return Response(out)


class MyLecturersView(APIView):
    """Student: lecturers of enrolled courses (to start a chat)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        admitted = admitted_student_for_user(request.user)
        if admitted is None:
            return Response([])
        lecturers = lecturers_for_student(admitted)
        out = []
        for u in lecturers:
            out.append(
                {
                    "id": u.id,
                    "name": u.get_full_name() or u.username,
                    "email": u.email or "",
                    "kind": "lecturer",
                }
            )
        return Response(out)


class FacultyContactsView(APIView):
    """Student: Faculty / Registry staff contacts (configurable groups)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not user_is_student_portal(request.user):
            # Staff may preview the same list when testing.
            if not user_can_use_staff_inbox(request.user):
                return Response({"detail": "Not allowed."}, status=403)
        out = []
        for u in faculty_inbox_contacts():
            role_label = (
                u.groups.filter(name__in=faculty_inbox_group_names())
                .order_by("name")
                .values_list("name", flat=True)
                .first()
                or "Faculty / Registry"
            )
            out.append(
                {
                    "id": u.id,
                    "name": u.get_full_name() or u.username,
                    "email": u.email or "",
                    "kind": "faculty",
                    "role_label": role_label,
                }
            )
        return Response(out)
