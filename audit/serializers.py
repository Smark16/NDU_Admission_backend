from rest_framework import serializers
from .models import *
import json

class AuditLogSerializer(serializers.ModelSerializer):
    user = serializers.CharField(source='user.full_name', read_only=True)
    class Meta:
        model = AuditLog
        fields = ['id', 'user', 'action', 'description', 'user_agent', 'timestamp']

class LogSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    user = serializers.SerializerMethodField()
    action = serializers.CharField(source='get_event_type_display')
    target = serializers.SerializerMethodField()
    details = serializers.SerializerMethodField()
    timestamp = serializers.DateTimeField(source='datetime')

    def get_user(self, obj):
        if obj.user:
            return obj.user.full_name
        return "System user"

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
        except:
            return None
        
