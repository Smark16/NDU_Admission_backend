from rest_framework import serializers

from .models import Bed, Building, Floor, Hostel, HostelAllocation, Room


class HostelSerializer(serializers.ModelSerializer):
    campus_name = serializers.CharField(source="campus.name", read_only=True)

    class Meta:
        model = Hostel
        fields = [
            "id",
            "campus",
            "campus_name",
            "code",
            "name",
            "gender",
            "is_active",
            "created_at",
            "updated_at",
        ]


class BuildingSerializer(serializers.ModelSerializer):
    hostel_name = serializers.CharField(source="hostel.name", read_only=True)
    hostel_gender = serializers.CharField(source="hostel.gender", read_only=True)

    class Meta:
        model = Building
        fields = [
            "id",
            "hostel",
            "hostel_name",
            "hostel_gender",
            "code",
            "name",
            "external_block_id",
            "is_active",
            "created_at",
            "updated_at",
        ]


class FloorSerializer(serializers.ModelSerializer):
    building_name = serializers.CharField(source="building.name", read_only=True)

    class Meta:
        model = Floor
        fields = [
            "id",
            "building",
            "building_name",
            "code",
            "name",
            "sort_order",
            "created_at",
            "updated_at",
        ]


class BedSerializer(serializers.ModelSerializer):
    room_code = serializers.CharField(source="room.code", read_only=True)

    class Meta:
        model = Bed
        fields = [
            "id",
            "room",
            "room_code",
            "label",
            "status",
            "created_at",
            "updated_at",
        ]


class RoomSerializer(serializers.ModelSerializer):
    floor_name = serializers.CharField(source="floor.name", read_only=True)
    building_id = serializers.IntegerField(source="floor.building_id", read_only=True)
    building_name = serializers.CharField(source="floor.building.name", read_only=True)
    hostel_id = serializers.IntegerField(source="floor.building.hostel_id", read_only=True)
    beds = BedSerializer(many=True, read_only=True)
    occupied_beds = serializers.SerializerMethodField()

    class Meta:
        model = Room
        fields = [
            "id",
            "floor",
            "floor_name",
            "building_id",
            "building_name",
            "hostel_id",
            "code",
            "display_name",
            "room_kind",
            "capacity",
            "notes",
            "is_active",
            "beds",
            "occupied_beds",
            "created_at",
            "updated_at",
        ]

    def get_occupied_beds(self, obj):
        return sum(1 for b in obj.beds.all() if b.status == Bed.STATUS_OCCUPIED)


class HostelAllocationSerializer(serializers.ModelSerializer):
    student_reg_no = serializers.CharField(source="student.reg_no", read_only=True)
    student_number = serializers.CharField(source="student.student_id", read_only=True)
    student_name = serializers.SerializerMethodField()
    gender = serializers.SerializerMethodField()
    program = serializers.SerializerMethodField()
    program_code = serializers.SerializerMethodField()
    faculty = serializers.SerializerMethodField()
    campus = serializers.SerializerMethodField()
    bed_label = serializers.CharField(source="bed.label", read_only=True)
    room_code = serializers.CharField(source="bed.room.code", read_only=True)
    building_name = serializers.CharField(
        source="bed.room.floor.building.name", read_only=True
    )
    building_code = serializers.CharField(
        source="bed.room.floor.building.code", read_only=True
    )
    block_id = serializers.CharField(
        source="bed.room.floor.building.external_block_id", read_only=True
    )
    floor_name = serializers.CharField(source="bed.room.floor.name", read_only=True)
    floor_code = serializers.CharField(source="bed.room.floor.code", read_only=True)
    hostel_name = serializers.CharField(
        source="bed.room.floor.building.hostel.name", read_only=True
    )
    assigned_by_name = serializers.SerializerMethodField()

    class Meta:
        model = HostelAllocation
        fields = [
            "id",
            "student",
            "student_reg_no",
            "student_number",
            "student_name",
            "gender",
            "program",
            "program_code",
            "faculty",
            "campus",
            "bed",
            "bed_label",
            "room_code",
            "building_name",
            "building_code",
            "block_id",
            "floor_name",
            "floor_code",
            "hostel_name",
            "academic_year",
            "term_number",
            "status",
            "check_in",
            "check_out",
            "notes",
            "assigned_by",
            "assigned_by_name",
            "assigned_at",
            "ended_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_student_name(self, obj):
        s = obj.student
        app = getattr(s, "application", None)
        if app:
            parts = [app.first_name or "", app.middle_name or "", app.last_name or ""]
            return " ".join(p for p in parts if p).strip() or (s.reg_no or str(s.pk))
        return s.reg_no or str(s.pk)

    def get_gender(self, obj):
        app = getattr(obj.student, "application", None)
        return getattr(app, "gender", None) if app else None

    def get_program(self, obj):
        prog = getattr(obj.student, "admitted_program", None)
        return prog.name if prog else None

    def get_program_code(self, obj):
        prog = getattr(obj.student, "admitted_program", None)
        return getattr(prog, "code", None) if prog else None

    def get_faculty(self, obj):
        prog = getattr(obj.student, "admitted_program", None)
        fac = getattr(prog, "faculty", None) if prog else None
        return fac.name if fac else None

    def get_campus(self, obj):
        campus = getattr(obj.student, "admitted_campus", None)
        return campus.name if campus else None

    def get_assigned_by_name(self, obj):
        u = obj.assigned_by
        if not u:
            return None
        return u.get_full_name() or u.username
