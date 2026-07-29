from rest_framework import serializers
from .models import *
import json

class AuditLogSerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = ['id', 'user', 'action', 'description', 'user_agent', 'timestamp']

    def get_user(self, obj):
        u = obj.user
        if not u:
            return "System"
        return getattr(u, "full_name", None) or u.get_full_name() or u.email or str(u.pk)


class LogSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    user = serializers.SerializerMethodField()
    action = serializers.SerializerMethodField()
    target = serializers.SerializerMethodField()
    details = serializers.SerializerMethodField()
    timestamp = serializers.DateTimeField(source='datetime')

    def get_user(self, obj):
        if obj.user:
            return (
                getattr(obj.user, "full_name", None)
                or obj.user.get_full_name()
                or obj.user.email
                or str(obj.user_id)
            )
        return "System user"

    def get_action(self, obj):
        try:
            return obj.get_event_type_display()
        except Exception:
            return str(getattr(obj, "event_type", "") or "Event")

    def get_target(self, obj):
        if not obj.content_type:
            return f"Deleted Object '{obj.object_id}'"
        model_name = obj.content_type.model.replace('_', ' ').title()
        return f"{model_name} '{obj.object_repr}'"

    def get_details(self, obj):
        if not obj.changed_fields or obj.changed_fields in ('null', '', '[]', '{}'):
            return None
        try:
            changes = json.loads(obj.changed_fields)
            if not changes:
                return None
            details = []
            for field, values in changes.items():
                if field == 'password':
                    continue
                if isinstance(values, list) and len(values) == 2:
                    old, new = values
                    if old != new:
                        details.append(f"{field}: '{old}' → '{new}'")
            return "; ".join(details) if details else None
        except Exception:
            return None

