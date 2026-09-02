from rest_framework import serializers

from messaging.models import Conversation, ConversationParticipant, Message


class MessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.SerializerMethodField()
    sender_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Message
        fields = ["id", "conversation", "sender_id", "sender_name", "body", "created_at"]
        read_only_fields = fields

    def get_sender_name(self, obj):
        u = obj.sender
        if not u:
            return ""
        return u.get_full_name() or u.username


class ConversationListSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    student_reg_no = serializers.CharField(source="student.reg_no", read_only=True)
    student_id_code = serializers.CharField(source="student.student_id", read_only=True)
    programme = serializers.SerializerMethodField()
    last_message_preview = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    peer_label = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            "id",
            "subject",
            "status",
            "student",
            "student_name",
            "student_reg_no",
            "student_id_code",
            "programme",
            "created_at",
            "last_message_at",
            "last_message_preview",
            "unread_count",
            "peer_label",
        ]

    def get_student_name(self, obj):
        try:
            return obj.student.application.full_name
        except Exception:
            return obj.student.reg_no or str(obj.student_id)

    def get_programme(self, obj):
        prog = getattr(obj.student, "admitted_program", None)
        return prog.name if prog else None

    def get_last_message_preview(self, obj):
        msg = obj.messages.order_by("-created_at").first()
        if not msg:
            return ""
        body = (msg.body or "").strip()
        return body[:120] + ("…" if len(body) > 120 else "")

    def get_unread_count(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        if not user:
            return 0
        part = next((p for p in obj.participants.all() if p.user_id == user.id), None)
        if part is None:
            return 0
        qs = obj.messages.exclude(sender=user)
        if part.last_read_at:
            qs = qs.filter(created_at__gt=part.last_read_at)
        return qs.count()

    def get_peer_label(self, obj):
        """For students: other staff names; for staff: student name."""
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        from messaging.access import user_is_student_portal

        if user and user_is_student_portal(user):
            names = []
            for p in obj.participants.all():
                if p.role == ConversationParticipant.ROLE_STAFF:
                    names.append(p.user.get_full_name() or p.user.username)
            return ", ".join(names) if names else "Staff"
        return self.get_student_name(obj)


class ConversationDetailSerializer(ConversationListSerializer):
    messages = serializers.SerializerMethodField()

    class Meta(ConversationListSerializer.Meta):
        fields = ConversationListSerializer.Meta.fields + ["messages"]

    def get_messages(self, obj):
        after = self.context.get("after_id")
        qs = obj.messages.select_related("sender").order_by("created_at")
        if after:
            qs = qs.filter(id__gt=int(after))
        return MessageSerializer(qs, many=True).data
