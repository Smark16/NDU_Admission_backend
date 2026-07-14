from rest_framework import serializers
from accounts.models import Campus

from .models import *
from .models import PayScale  # explicit — required for PayScaleSerializer at import time


class CampusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Campus
        fields = "__all__"

# staff serializers
class StaffProfileSerializer(serializers.ModelSerializer):
    campus = serializers.PrimaryKeyRelatedField(
        queryset=Campus.objects.all(),
        many=True,
        required=False,
    )
    teams_supervised = serializers.PrimaryKeyRelatedField(
        queryset=DepartmentTeams.objects.all(),
        many=True,
        required=False
    )

    staff_members_supervised = serializers.PrimaryKeyRelatedField(
        queryset=StaffProfile.objects.all(),
        many=True,
        required=False
    )

    managed_org_units = serializers.PrimaryKeyRelatedField(
        queryset=Department.objects.all(),
        many=True,
        required=False
    )

    class Meta:
        model = StaffProfile
        fields = "__all__"

    def create(self, validated_data):
        # 🔥 POP relational fields FIRST
        teams_supervised = validated_data.pop("teams_supervised", [])
        # Members are derived from supervised teams — ignore direct member picks.
        validated_data.pop("staff_members_supervised", None)
        managed_org_units = validated_data.pop("managed_org_units", [])
        campus = validated_data.pop("campus", [])
        if not campus:
            default_campus = Campus.objects.first()
            if default_campus:
                campus = [default_campus]

        # ✅ Create staff FIRST
        staff = StaffProfile.objects.create(**validated_data)

        if managed_org_units:
            staff.managed_org_units.set(managed_org_units)

        if campus:
            staff.campus.set(campus)

        # Directors manage whole departments — no team assignments.
        if staff.is_director:
            if not managed_org_units:
                raise serializers.ValidationError(
                    "Director must manage at least one organizational unit."
                )
            return staff

        # Supervisors supervise teams only (members come from those teams).
        if staff.is_supervisor:
            if not teams_supervised:
                raise serializers.ValidationError(
                    "Supervisor must supervise at least one team."
                )
            for team in teams_supervised:
                SupervisionAssignment.objects.create(
                    supervisor=staff,
                    team=team
                )

        return staff

    def _sync_supervision_assignments(self, instance, teams_supervised, staff_members_supervised=None):
        # Directors never hold team/member supervision rows.
        if instance.is_director or not instance.is_supervisor:
            SupervisionAssignment.objects.filter(supervisor=instance).delete()
            return

        if teams_supervised is None:
            return

        teams = teams_supervised
        if not teams:
            raise serializers.ValidationError(
                "Supervisor must supervise at least one team."
            )

        SupervisionAssignment.objects.filter(supervisor=instance).delete()
        for team in teams:
            SupervisionAssignment.objects.create(supervisor=instance, team=team)

    def update(self, instance, validated_data):
        teams_supervised = validated_data.pop("teams_supervised", None)
        validated_data.pop("staff_members_supervised", None)
        managed_org_units = validated_data.pop("managed_org_units", None)
        campus = validated_data.pop("campus", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if managed_org_units is not None:
            instance.managed_org_units.set(managed_org_units)
        if campus is not None:
            instance.campus.set(campus)

        if instance.is_director:
            if not instance.managed_org_units.exists():
                raise serializers.ValidationError(
                    "Director must manage at least one organizational unit."
                )
            # Clear any legacy team/member assignments.
            SupervisionAssignment.objects.filter(supervisor=instance).delete()
            return instance

        self._sync_supervision_assignments(instance, teams_supervised)

        return instance
    
# simplified staff serializer
class ListStaffSerializer(serializers.ModelSerializer):
    class Meta:
        model = StaffProfile
        fields = ['id', 'get_full_name']

# all staff serializer
class AllStaffSerializer(serializers.ModelSerializer):
    department = serializers.SerializerMethodField()
    is_active = serializers.SerializerMethodField()

    class Meta:
        model = StaffProfile
        fields = ['id', 'get_full_name', 'university_email', 'staff_no', 'department', 'is_active', 'user']

    def get_department(self, obj):
        return obj.org_unit.name if obj.org_unit else None

    def get_is_active(self, obj):
        return bool(obj.user and obj.user.is_active)

# Detailed Staff Serializer
class DetailStaffSerializer(serializers.ModelSerializer):
    teams_supervised = serializers.SerializerMethodField()
    staff_members_supervised = serializers.SerializerMethodField()
    class Meta:
        model = StaffProfile
        fields = ['id', 'is_supervisor', 'is_hr', 'is_director', 'first_name', 'last_name', 'nssf_no',
                  'tin_no', 'university_email', 'personal_email', 'passport_photo', 'job_title',
                  'system_login', 'user', 'teams_supervised', 'staff_members_supervised']
        
    def get_teams_supervised(self, instance):
        teams = DepartmentTeams.objects.filter(
            asigned_teams__supervisor=instance
        ).distinct()

        return TeamsMiniSerializer(teams, many=True).data
    
    def get_staff_members_supervised(self, instance):
        staff = StaffProfile.objects.filter(
            assigned_supervisors__supervisor=instance
        ).distinct()

        return AllStaffSerializer(staff, many=True).data

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response['org_unit'] = (
            DepartmentSerializer(instance.org_unit).data if instance.org_unit else None
        )
        response['staff_type'] = (
            UnitTypeSerializer(instance.staff_type).data if instance.staff_type else None
        )
        response['position_level'] = (
            PositionLevelSerializer(instance.position_level).data if instance.position_level else None
        )
        response['pay_scale'] = (
            PayScaleSerializer(instance.pay_scale).data if instance.pay_scale else None
        )
        response['managed_org_units'] = DepartmentSerializer(instance.managed_org_units.all(), many=True).data
        response['team'] = (
            DepartmentTeamsSerializer(instance.team).data if instance.team else None
        )
        response['campus'] = CampusSerializer(instance.campus.all(), many=True).data
        return response

# mini staff serializer
class MiniStaffSerializer(serializers.ModelSerializer):
    department = serializers.SerializerMethodField()
    team = serializers.SerializerMethodField()

    class Meta:
        model = StaffProfile
        fields = ['id', 'is_supervisor', 'is_hr', 'is_director', 'first_name', 'last_name', 'nssf_no',
                  'tin_no', 'university_email', 'personal_email', 'passport_photo', 'job_title',
                  'user', 'department', 'team']

    def get_department(self, obj):
        return obj.org_unit.name if obj.org_unit else None

    def get_team(self, obj):
        return obj.team.team_name if obj.team else None 

class UnitTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = StaffType
        fields = '__all__'

class PositionLevelSerializer(serializers.ModelSerializer):
     class Meta:
        model = PositonLevel
        fields = '__all__'

class PayScaleSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source="get_category_display", read_only=True)

    class Meta:
        model = PayScale
        fields = "__all__"

# teams serializer
class DepartmentTeamsSerializer(serializers.ModelSerializer):
    class Meta:
        model = DepartmentTeams
        fields = '__all__'

# mini teams serializer
class TeamsMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = DepartmentTeams
        fields = ['id', 'team_name']

class ListDepartmentTeamsSerializer(serializers.ModelSerializer):
    memberCount = serializers.SerializerMethodField()

    class Meta:
        model = DepartmentTeams
        fields = [
            "id",
            "team_name",
            "description",
            "memberCount",
            "created_at",
        ]

    def get_memberCount(self, obj):
        return obj.members.count()

# department serializers
class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = '__all__'

class ListDepartmentSerializer(serializers.ModelSerializer):
    teams = ListDepartmentTeamsSerializer(many=True, read_only=True)

    class Meta:
        model = Department
        fields = [
            "id",
            "name",
            "code",
            "description",
            "created_at",
            "teams",
        ]

# bulk upload serializer
class BulkUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = BulkUploadStaff
        fields = '__all__'

# staff contract serializer
class StaffContractSerializer(serializers.ModelSerializer):
    staff_name = serializers.CharField(source="staff.get_full_name", read_only=True)
    department_name = serializers.SerializerMethodField()
    pay_scale_code = serializers.SerializerMethodField()
    contract_file = serializers.FileField(write_only=True, required=False)

    class Meta:
        model = StaffContract
        fields = [
            "id",
            "staff",
            "staff_name",
            "contract_type",
            "contract_number",
            "start_date",
            "end_date",
            "position",
            "department",
            "department_name",
            "salary",
            "pay_scale",
            "pay_scale_code",
            "pay_step",
            "status",
            "contract_file",
        ]
        read_only_fields = ["contract_number"]

    def get_department_name(self, obj):
        return obj.department.name if obj.department else None

    def get_pay_scale_code(self, obj):
        return obj.pay_scale.code if obj.pay_scale_id else None

    def create(self, validated_data):
        import uuid
        from django.core.files.base import ContentFile

        contract_file = validated_data.pop("contract_file", None)
        if not contract_file:
            contract_file = ContentFile(
                b"Contract document placeholder - replace with signed contract.",
                name="contract_pending.pdf",
            )
        validated_data["contract_file"] = contract_file
        if not validated_data.get("contract_number"):
            validated_data["contract_number"] = f"CTR-{uuid.uuid4().hex[:8].upper()}"
        return super().create(validated_data)

# supervision 
class SupervisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupervisionAssignment
        fields = '__all__'