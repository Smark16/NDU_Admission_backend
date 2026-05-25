from rest_framework import serializers

from .models import GraduationAssignment, GraduationCeremony, GraduationSession


class GraduationCeremonySerializer(serializers.ModelSerializer):
    session_count = serializers.SerializerMethodField()
    assigned_count = serializers.SerializerMethodField()

    class Meta:
        model = GraduationCeremony
        fields = [
            "id",
            "name",
            "completion_date",
            "show_marks_on_transcript",
            "is_active",
            "notes",
            "session_count",
            "assigned_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_session_count(self, obj):
        return obj.sessions.count()

    def get_assigned_count(self, obj):
        return GraduationAssignment.objects.filter(session__ceremony=obj).count()


class GraduationSessionSerializer(serializers.ModelSerializer):
    ceremony_name = serializers.CharField(source="ceremony.name", read_only=True)
    assigned_count = serializers.SerializerMethodField()

    class Meta:
        model = GraduationSession
        fields = [
            "id",
            "ceremony",
            "ceremony_name",
            "name",
            "graduation_date",
            "venue",
            "notes",
            "assigned_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_assigned_count(self, obj):
        return obj.assignments.count()


class GraduationAssignmentSerializer(serializers.ModelSerializer):
    reg_no = serializers.CharField(source="student.reg_no", read_only=True)
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    program_name = serializers.SerializerMethodField()
    session_name = serializers.CharField(source="session.name", read_only=True)
    graduation_date = serializers.DateField(source="session.graduation_date", read_only=True)

    class Meta:
        model = GraduationAssignment
        fields = [
            "id",
            "session",
            "student",
            "reg_no",
            "student_name",
            "program_name",
            "session_name",
            "graduation_date",
            "cgpa_at_assignment",
            "credit_units_at_assignment",
            "award_class",
            "enrollment_completed",
            "assigned_at",
        ]

    def get_program_name(self, obj):
        try:
            return obj.student.programme_enrollment.program.name
        except Exception:
            return None
